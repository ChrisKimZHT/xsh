"""session.py - 会话对象，维护会话状态并保存会话文件"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xsh.messages import Message, ToolCall

_FORMAT_VERSION = 1


def _read_events(path: Path) -> list[dict[str, Any]]:
    """逐行读取并解析会话事件，同时修复末尾不完整记录。

    JSONL 记录写成 "行 + \\n"，且 JSON 内部换行会被转义，因此每条完整记录占用一行。
    若进程在写入最后一条记录时被中断，末尾会留下半行 JSON。这里会丢弃并**物理截断**
    该残片，避免它在下次追加后不再是末行、导致会话无法恢复。中间位置的损坏仍会报错。
    采用逐行流式读取，避免把整份（可能很大）会话文件一次性读入内存。
    """
    events: list[dict[str, Any]] = []
    truncate_at: int | None = None
    with path.open("rb") as handle:
        while True:
            start = handle.tell()
            line = handle.readline()
            if not line:  # 文件结束
                break
            if not line.endswith(b"\n"):
                # 末尾没有换行符：可能是被中断的半行，也可能是缺少换行的完整记录。
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        truncate_at = start
                    else:
                        with path.open("ab") as append_handle:
                            append_handle.write(b"\n")
                break
            if line.strip():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    raise ValueError("Corrupt session event in a complete line") from None

    if truncate_at is not None:
        with path.open("r+b") as handle:
            handle.truncate(truncate_at)
    return events


class Session:
    """会话对象，在对象中维护会话状态，同时用 JSONL 保存会话"""

    def __init__(self, path: Path, workspace: Path):
        self.path = path
        self.workspace = workspace.resolve()
        self.messages: list[Message] = []
        self.turn_count = 0  # 从原始用户消息计数，摘要不增加轮次。
        self.step_count = 0  # 从原始助手消息计数，摘要不增加步骤。
        self.message_positions: list[tuple[int, int] | None] = []  # None 表示系统消息，(turn, step) 表示原始消息的轮次和步骤
        self.pending: dict[str, ToolCall] = {}  # 尚未收到结果的工具调用
        self.started: set[str] = set()          # 已记录开始执行、尚未收到结果的调用 ID
        self.non_stop_task: dict[str, Any] | None = None
        self.todos: list[dict[str, Any]] = []  # 任务清单（todo 工具维护），随会话持久化
        self.recovered_tool_calls = 0  # 恢复会话时补齐的未完成工具调用数量

    @classmethod
    def create(cls, path: Path, workspace: Path, system_prompt: str) -> "Session":
        """创建会话对象并创建对应的会话文件，然后初始化会话状态"""
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass  # 使用 x 模式，防止覆盖已有会话。

        session = cls(path, workspace)
        session.record("session", {"version": _FORMAT_VERSION, "workspace": str(session.workspace)})  # 写入会话头
        session.append(Message(role="system", content=system_prompt))  # 写入系统提示
        return session

    @classmethod
    def load(cls, path: Path, *, repair: bool = True) -> "Session":
        """恢复会话；repair=True 时为中断的工具调用补齐错误结果。"""
        # 读取会话 JSONL 文件。进程可能在校验最后一行写入时被中断，因此允许
        # 丢弃末尾一条不完整记录；中间位置的损坏仍然视为错误。
        path = path.resolve()
        events = _read_events(path)

        # 读取并检查会话头
        if not events or events[0].get("type") != "session":
            raise ValueError("Missing session header")
        header = events[0]["data"]
        if header["version"] != _FORMAT_VERSION:
            raise ValueError("Unsupported session version")

        # 创建会话对象
        session = cls(path, Path(header["workspace"]))

        # 按事件顺序重建消息及工具调用状态，不重新写入已有记录。
        for event in events[1:]:
            if event["type"] == "non_stop_task":
                session.non_stop_task = event["data"]
            elif event["type"] == "todos":  # 恢复任务清单，便于跨重启续作
                todos = event["data"].get("todos")
                if isinstance(todos, list):
                    session.todos = todos
            elif event["type"] == "message":
                session._accept(Message.model_validate(event["data"]))
            elif event["type"] == "system_prompt":  # 如果在 1: 后找到系统提示词事件，则是更新了系统提示词，替换旧的系统消息
                if not session.messages or session.messages[0].role != "system":
                    raise ValueError("Missing system prompt")
                session.messages[0] = Message(role="system", content=event["data"]["content"])
            elif event["type"] == "tool_start":
                call_id = event["data"]["id"]
                if call_id not in session.pending:
                    raise ValueError("Tool start without a pending call")
                session.started.add(call_id)
            elif event["type"] == "compaction":  # 读取到压缩事件时生效压缩到内存中
                data = event["data"]
                session._apply_compaction(data["end"], Message.model_validate(data["summary"]))

        # 会话第一个消息必须是系统提示
        if not session.messages or session.messages[0].role != "system":
            raise ValueError("Missing system prompt")

        # 中断前可能已产生副作用，恢复时不自动重跑工具。
        if repair:
            session.recovered_tool_calls = session.repair_pending()
        return session

    def update_system_prompt(self, content: str) -> None:
        """记录系统提示词更新事件，并立即替换内存中的系统消息。"""
        if not self.messages or self.messages[0].role != "system":
            raise ValueError("Missing system prompt")
        if self.messages[0].content != content:
            self.record("system_prompt", {"content": content})  # 若更新，则 JSONL 里会出现新的 system_prompt 事件，加载时会替换旧的系统消息
            self.messages[0] = Message(role="system", content=content)

    def record(self, kind: str, data: dict[str, Any]) -> None:
        """向会话文件追加带时间戳的事件"""
        event = {"time": datetime.now(UTC).isoformat(), "type": kind, "data": data}
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(line + "\n")

    def append(self, message: Message) -> None:
        """校验并保存消息，再更新内存状态"""
        self._validate_next(message)
        self.record("message", message.model_dump())
        self._accept(message)

    def _validate_next(self, message: Message) -> None:
        """确保工具调用与结果配对，结果补齐后才能接收其他消息"""
        if self.pending and message.role != "tool":
            raise ValueError("Tool calls must receive results before the next message")
        if message.role == "tool" and message.tool_call_id not in self.pending:
            raise ValueError("Tool result has no matching pending call")

    def _accept(self, message: Message) -> None:
        """接收消息，并更新待完成和已开始的工具调用状态"""
        self._validate_next(message)
        self.messages.append(message)
        if message.role == "user":
            self.turn_count += 1
            self.step_count = 0
        elif message.role == "assistant":
            self.step_count += 1
        self.message_positions.append(None if message.role == "system" else (self.turn_count, self.step_count))
        if message.tool_calls:  # 如果是工具调用，则加入待完成列表
            self.pending = {call.id: call for call in message.tool_calls}
        if message.tool_call_id:  # 如果是工具结果，则从待完成列表中移除，并从已开始列表中移除
            self.pending.pop(message.tool_call_id)
            self.started.discard(message.tool_call_id)

    def compact(self, end: int, summary: Message) -> None:
        """用摘要替换 [1, end)；先追加一个完整检查点，再更新内存，原始日志保留。"""
        self._validate_compaction(end, summary)
        self.record("compaction", {"end": end, "summary": summary.model_dump()})
        self._apply_compaction(end, summary)

    def _validate_compaction(self, end: int, summary: Message) -> None:
        """检查压缩范围和摘要消息的合法性"""
        if self.pending or type(end) is not int or not 1 < end <= len(self.messages):
            raise ValueError("Invalid compaction range or pending tool calls")
        if summary.role != "user" or not (summary.content or "").strip():
            raise ValueError("Compaction requires a non-empty user checkpoint")
        pending: set[str] = set()
        for message in self.messages[1:end]:
            pending.update(call.id for call in message.tool_calls)
            if message.tool_call_id:
                pending.remove(message.tool_call_id)
        if pending:
            raise ValueError("Compaction would split tool calls and results")

    def _apply_compaction(self, end: int, summary: Message) -> None:
        """将 [1, end) 替换为摘要消息，更新内存状态"""
        self._validate_compaction(end, summary)
        self.messages[1:end] = [summary]
        self.message_positions[1:end] = [None]

    def start_tool(self, call: ToolCall) -> None:
        """在执行工具前记录开始事件。"""
        self.record("tool_start", {"id": call.id, "name": call.name})
        self.started.add(call.id)

    def repair_pending(self) -> int:
        """为未完成的工具调用补写错误结果，不重新执行，返回补齐的调用数量。"""
        repaired = 0
        for call in list(self.pending.values()):
            if call.id in self.started:  # 已开始的调用无法确定是否完成，需要用户检查实际状态。
                detail = (
                    "TOOL_OUTCOME_UNKNOWN: execution was interrupted. Its side effects may "
                    "have occurred. Inspect external state before retrying a mutation."
                )
            else:
                detail = "TOOL_NOT_STARTED: this call was interrupted before dispatch."
            self.append(Message(role="tool", tool_call_id=call.id, content="Error: " + detail))
            repaired += 1
        return repaired
