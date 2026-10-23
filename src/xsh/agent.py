"""agent.py - Agent 对象，维护 Agent 的 Step 循环"""

from collections.abc import Callable
from dataclasses import dataclass, field

from xsh.compaction import CompactionResult, Compactor
from xsh.messages import Message
from xsh.model import Model
from xsh.session import Session
from xsh.tools.base import ToolRegistry


@dataclass(frozen=True)
class TurnResult:
    """单轮运行结果摘要，包含状态、步数、输出文本和错误信息"""
    status: str
    steps: int
    text: str = ""
    error: str = ""
    retryable: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    usage_partial: bool = False
    context_tokens: int | None = None
    cache_hit_rate: float | None = None
    cache_partial: bool = False


# 与模型服务交互时可能出现的暂时性故障，适合稍后重试而不是直接结束进程。
_TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def is_transient_error(error: BaseException) -> bool:
    """判断异常是否为可重试的暂时性故障（限流、超时、连接中断、5xx）。"""
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except Exception:  # openai 不可用时不影响主流程
        return False
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code in _TRANSIENT_STATUS_CODES
    return False


class Agent:
    """Agent 对象，维护 Agent 的 Step 循环"""

    def __init__(
        self,
        model: Model,
        session: Session,
        tools: ToolRegistry,
        max_steps: int,
        report: Callable[[str, str], None] | None = None,
        compactor: Compactor | None = None,
    ):
        if max_steps < 1:
            raise ValueError("Agent limits must be positive")
        self.model = model
        self.session = session
        self.tools = tools
        self.max_steps = max_steps
        self.report = report or (lambda kind, text: None)
        self.compactor = compactor

    def compact(self) -> CompactionResult | None:
        """轮次间的手动压缩，不新增用户消息或执行工具。"""
        self.session.repair_pending()
        if self.compactor is None:
            raise ValueError("Context compaction is not configured")
        return self.compactor.compact(self.session, self.tools.schemas(), manual=True)

    def run(self, prompt: str) -> TurnResult:
        if not prompt.strip():
            raise ValueError("Prompt must not be empty")

        # ======================
        # 初始化本轮计数与用量统计
        # ======================
        step = 0
        usage: dict[str, int] = {}
        usage_partial = False
        context_tokens = None
        cached_tokens = 0
        cache_prompt_tokens = 0
        cache_steps = 0

        # =================================
        # 统一收尾函数，汇总结果并记录轮次结束
        # =================================
        def finish(status: str, text: str = "", error: str = "", retryable: bool = False) -> TurnResult:
            """结束该 Turn：生成结果、停止工具状态刷新并落盘 turn_end"""
            result = TurnResult(
                status=status,
                steps=step,
                text=text,
                error=error,
                retryable=retryable,
                usage=usage.copy(),
                usage_partial=usage_partial,
                context_tokens=context_tokens,
                cache_hit_rate=cached_tokens / cache_prompt_tokens if cache_prompt_tokens else None,
                cache_partial=cache_steps < step,
            )
            # 无论正常结束还是中断、异常，都停止工具状态刷新，避免影响后续终端输出。
            self.report("tool_end", "")
            self.session.record(
                "turn_end",
                {
                    "status": result.status,
                    "steps": result.steps,
                    "error": result.error,
                    "retryable": result.retryable,
                    "usage": result.usage,
                    "usage_partial": result.usage_partial,
                    "context_tokens": result.context_tokens,
                    "cache_hit_rate": result.cache_hit_rate,
                    "cache_partial": result.cache_partial,
                },
            )
            return result

        # ===============
        # 轮次在此正式开始
        # ===============
        try:
            self.report("turn_start", "")
            self.session.repair_pending()  # 为未收到结果的工具调用补写错误结果，不重新执行
            self.session.append(Message(role="user", content=prompt))  # 添加用户输入到会话中
            # 每条用户消息对应一个 Turn，从会话历史计数以支持恢复后继续编号。
            turn = self.session.turn_count

            # ※ Agent Step 循环
            for step in range(1, self.max_steps + 1):
                # ==========================
                # 阶段 1：压缩上下文，准备请求
                # ==========================
                # 每 Step 之前都尝试压缩，未达到压缩条件，压缩器会自动跳过
                if self.compactor:
                    self.compactor.compact(self.session, self.tools.schemas())
                # 准备模型请求参数，取出会话消息和工具列表
                request = self.model.build_request(self.session.messages, self.tools.schemas())
                self.session.record("request", {"step": step, "body": request})
                self.report("step", f"Turn {turn}, Step {step}")

                # ===============
                # 阶段 2：请求模型
                # ===============
                self.report("assistant_start", "")
                context_tokens = None
                try:
                    response = self.model.complete(
                        request,
                        on_text=lambda text: self.report("assistant_delta", text),
                        on_reasoning=lambda text: self.report("assistant_reasoning_delta", text),
                    )
                except BaseException:
                    usage_partial = True
                    raise
                finally:
                    self.report("assistant_end", "")

                # ========================
                # 阶段 3：累计用量，记录响应
                # ========================
                # Usage 累计整轮请求，Context 只取最后一次请求的输入量。
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = response.usage.get(key)
                    if type(value) is int and value >= 0:
                        usage[key] = usage.get(key, 0) + value
                        if key == "prompt_tokens":
                            context_tokens = value
                    else:
                        usage_partial = True
                # 兼容标准 cached_tokens 和 DeepSeek 的缓存命中字段。
                details = response.usage.get("prompt_tokens_details")
                cached = details.get("cached_tokens") if isinstance(details, dict) else None
                if cached is None:
                    cached = response.usage.get("prompt_cache_hit_tokens")
                prompt_tokens = response.usage.get("prompt_tokens")
                if type(prompt_tokens) is int and type(cached) is int and 0 <= cached <= prompt_tokens:
                    cached_tokens += cached
                    cache_prompt_tokens += prompt_tokens
                    cache_steps += 1

                self.session.record(
                    "response",
                    {
                        "step": step,
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                    },
                )
                message = response.message

                # ============================
                # 阶段 4：保存消息，判断是否结束
                # ============================
                # 检查结束原因，若异常结束则丢弃不可靠的工具调用
                if response.finish_reason not in {"stop", "tool_calls"}:
                    message = message.model_copy(update={"tool_calls": []})

                # 储存模型响应到会话中
                self.session.append(message)

                # 检查结束原因，若异常结束则该 Turn 直接结束
                if response.finish_reason not in {"stop", "tool_calls"}:
                    return finish(
                        "max_tokens" if response.finish_reason == "length" else "stopped",
                        message.content or "",
                    )

                # 如果没有工具调用，则该 Turn 结束
                if not message.tool_calls:
                    return finish("completed", message.content or "")

                # ==========================================
                # 阶段 5：没有结束，执行工具调用，进入下一 Step
                # ==========================================
                # 如果有工具调用，则依次执行工具调用
                for call in message.tool_calls:
                    self.report("tool", call.name)  # 通知终端已收到当前工具调用
                    self.session.start_tool(call)
                    self.report("tool_start", call.name)  # 开始记录落盘后、实际执行前更新运行状态
                    result = self.tools.execute(call)
                    self.session.append(result)
                    self.report("tool_result", result.content or "")

            # 循环跑完了，说明 Step 超限，该 Turn 可能未完成，但必须结束
            return finish("step_limit", error="Maximum model steps reached; completed tool results are saved.")

        # =============
        # 中断与异常收尾
        # =============
        except KeyboardInterrupt:
            self.session.repair_pending()
            return finish("cancelled", error="Interrupted by user.")

        except Exception as error:
            self.session.repair_pending()
            return finish("error", error=f"{type(error).__name__}: {error}", retryable=is_transient_error(error))
