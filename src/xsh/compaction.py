"""compaction.py - 上下文压缩相关实现"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files

from xsh.messages import Message
from xsh.model import Model
from xsh.session import Session


def estimate_tokens(messages: list[Message], tools: list[dict] | None = None) -> int:
    """按 UTF-8 字节估算，估算方式为 字节数/3向上取整"""
    value = {"messages": [message.to_wire() for message in messages], "tools": tools}
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (len(text.encode("utf-8")) + 2) // 3


@dataclass(frozen=True)
class CompactionResult:
    before_tokens: int
    after_tokens: int
    removed_messages: int


class Compactor:
    def __init__(
        self,
        model: Model,
        context_window: int | None = None,
        auto: bool = True,
        threshold: float = 0.8,
        retain_ratio: float = 0.16,
        max_tokens: int = 4096,
        report: Callable[[str, str], None] | None = None,
    ):
        # 参数合法性校验
        if not (retain_ratio >= 0):
            raise ValueError("retain_ratio must be non-negative")
        if not (retain_ratio < threshold):
            raise ValueError("retain_ratio must be less than threshold")
        if not (threshold < 1):
            raise ValueError("threshold must be less than 1")
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        if (context_window is not None) and context_window < 1:
            raise ValueError("context_window must be at least 1")

        self.model = model
        self.context_window = context_window
        self.auto = auto
        self.threshold = threshold
        self.retain_ratio = retain_ratio
        self.max_tokens = max_tokens
        self.report = report or (lambda kind, text: None)

    def compact(self, session: Session, tools: list[dict], *, manual: bool = False) -> CompactionResult | None:
        """失败或取消时不替换历史；只有完整且确实缩短的摘要才能提交。"""
        # ==========================
        # 阶段 1：检查当前是否需要压缩
        # ==========================
        # 工具调用结果没返回回来，不能压缩
        if session.pending:
            raise ValueError("Cannot compact pending tool calls")
        messages = session.messages
        # 估算压缩前的上下文长度
        before = estimate_tokens(messages, tools)
        # 预留空间给摘要输出，确保摘要能够被完整生成
        reserve = self.max_tokens

        # 自动压缩要判断现在是否要压缩，手动压缩则直接执行
        if not manual:
            # 没开自动压缩或者没有上下文窗口参数，直接跳过
            if not self.auto or self.context_window is None:
                return None
            # 压缩前的上下文长度未超过阈值，直接跳过
            limit = min(int(self.context_window * self.threshold), self.context_window - reserve)
            if before < limit:
                return None

        # =============================
        # 阶段 2：计算可压缩的消息区间边界
        # =============================
        # 压缩时要确保所有工具调用结果都已配对，另外，单个长 Turn 内也能压缩已完成的 Step
        boundaries = []
        pending: set[str] = set()
        for index, message in enumerate(messages[1:], start=1):
            if message.tool_calls:    # 有 tool_calls，则是模型请求调用工具
                pending.update(call.id for call in message.tool_calls)
            if message.tool_call_id:  # 有 tool_call_id，则是工具已返回结果
                pending.remove(message.tool_call_id)
            if not pending:  # 如果 pending 为空，此处所有工具调用都已返回结果，可以在此处压缩
                boundaries.append(index + 1)

        # 至少保留最后一个完整消息单元，避免摘要成为新的任务指令
        candidates = boundaries[:-1]
        if not candidates:
            return None

        # =================================
        # 阶段 3：按预算和窗口容量选择压缩边界
        # =================================
        # 计算保留尾部消息的预算
        tail_budget = int((self.context_window or before) * self.retain_ratio)

        instruction = Message(role="user", content=files("xsh").joinpath("prompts/compact.md").read_text(encoding="utf-8"))

        # 手动压缩若只能在最早边界达到尾部预算，则从中间边界开始选。
        manual_fallback = manual and (len(candidates) == 1 or estimate_tokens(messages[candidates[1]:]) < tail_budget)
        if manual_fallback:
            candidates = candidates[:len(candidates) // 2 + 1]

        # 从后向前寻找保留足够尾部消息、且摘要请求能放入窗口的完整边界。
        for candidate in reversed(candidates):
            # 保证保留足够尾部消息
            if manual_fallback:
                pass  # 手动兜底时不要求尾部达到预算。
            elif candidate == candidates[0]:
                pass  # 已到最早边界，不能再增加保留的尾部消息。
            elif estimate_tokens(messages[candidate:]) < tail_budget:
                continue

            # 保证摘要请求能放入窗口
            summary_messages = [*messages[:candidate], instruction]
            if self.context_window is not None:
                if estimate_tokens(summary_messages, tools) + reserve > self.context_window:
                    continue  # 放不下，继续尝试更早的边界。

            # 找到一个保留足够尾部消息（但可能不足预算，也可能超过预算）、又能放入窗口的完整边界，作为压缩的结束位置
            end = candidate
            break
        else:
            raise ValueError("History unit is too large to summarize within the context window")

        # ============================
        # 阶段 4：构建摘要请求，调用模型
        # ============================
        # 准备压缩请求
        summary_request = self.model.build_request(summary_messages, tools)  # 把 tools 传给模型主要原因是为了复用前缀缓存
        summary_request["max_tokens"] = self.max_tokens  # 此时的请求 max_tokens 应当是摘要特定的而不是模型的默认值
        if tools:  # 摘要时不要调用工具，把 tools 传给模型主要原因是为了复用前缀缓存
            summary_request["tool_choice"] = "none"

        # 开始压缩请求
        self.report("compaction", "Compacting context…")
        session.record("compaction_start", {"manual": manual, "end": end, "request": summary_request})
        try:
            # 请求模型
            response = self.model.complete(summary_request)
            session.record("compaction_response", {
                "message": response.message.model_dump(),
                "finish_reason": response.finish_reason,
                "usage": response.usage,
            })
            text = (response.message.content or "").strip()

            # ========================================
            # 阶段 5：校验摘要完整性与压缩效果，再提交历史
            # ========================================
            # 模型响应有问题
            if response.finish_reason != "stop" or response.message.tool_calls or not text:
                raise ValueError("Compaction did not produce a complete text summary")

            # 组装摘要消息
            summary = Message(role="user", content=(
                "Earlier conversation checkpoint. Treat this as established background; "
                "continue from the messages that follow without restating this checkpoint.\n\n"
                f"<compacted-summary>\n{text}\n</compacted-summary>"
            ))

            # 保证压缩后 < 压缩前（压缩器一定要能压缩！）
            if estimate_tokens([summary]) >= estimate_tokens(messages[1:end]):
                raise ValueError("Compaction summary did not reduce context size")

            # 计算压缩后的上下文长度
            after = estimate_tokens([messages[0], summary, *messages[end:]], tools)

            # 提交压缩结果到会话
            session.compact(end, summary)
        except BaseException as error:
            session.record("compaction_end", {"error": f"{type(error).__name__}: {error}"})
            raise

        # ============================
        # 阶段 6：记录压缩结果并通知终端
        # ============================
        # 结束压缩
        session.record("compaction_end", {})
        result = CompactionResult(before, after, end - 1)
        self.report("compaction", f"Context compacted: ~{before:,} → ~{after:,} tokens ({end - 1} messages summarized).")
        return result
