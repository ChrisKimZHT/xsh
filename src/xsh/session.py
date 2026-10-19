"""session.py - 会话对象，维护会话状态并保存会话文件"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xsh.messages import Message, ToolCall


class Session:
    """会话对象，在对象中维护会话状态，同时用 JSONL 保存会话"""

    def __init__(self, path: Path, workspace: Path):
        self.path = path
        self.workspace = workspace.resolve()
        self.messages: list[Message] = []
        self.pending: dict[str, ToolCall] = {}  # 尚未收到结果的工具调用
        self.started: set[str] = set()          # 已记录开始执行、尚未收到结果的调用 ID

    @classmethod
    def create(cls, path: Path, workspace: Path, system_prompt: str) -> "Session":
        """创建会话对象并创建对应的会话文件，然后初始化会话状态"""
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass  # 使用 x 模式，防止覆盖已有会话。

        session = cls(path, workspace)
        session.record("session", {"version": 1, "workspace": str(session.workspace)})  # 写入会话头
        session.append(Message(role="system", content=system_prompt))  # 写入系统提示
        return session

    @classmethod
    def load(cls, path: Path) -> "Session":
        """恢复会话，并为中断的工具调用补齐错误结果"""
        # 读取会话 JSONL 文件
        path = path.resolve()
        with path.open(encoding="utf-8") as file:
            events = [json.loads(line) for line in file]

        # 读取并检查会话头
        if not events or events[0].get("type") != "session":
            raise ValueError("Missing session header")
        header = events[0]["data"]
        if header["version"] != 1:
            raise ValueError("Unsupported session version")

        # 创建会话对象
        session = cls(path, Path(header["workspace"]))

        # 按事件顺序重建消息及工具调用状态，不重新写入已有记录。
        for event in events[1:]:
            if event["type"] == "message":
                session._accept(Message.model_validate(event["data"]))
            elif event["type"] == "tool_start":
                call_id = event["data"]["id"]
                if call_id not in session.pending:
                    raise ValueError("Tool start without a pending call")
                session.started.add(call_id)

        # 会话第一个消息必须是系统提示
        if not session.messages or session.messages[0].role != "system":
            raise ValueError("Missing system prompt")

        # 中断前可能已产生副作用，恢复时不自动重跑工具。
        session.repair_pending()
        return session

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
        if message.tool_calls:  # 如果是工具调用，则加入待完成列表
            self.pending = {call.id: call for call in message.tool_calls}
        if message.tool_call_id:  # 如果是工具结果，则从待完成列表中移除，并从已开始列表中移除
            self.pending.pop(message.tool_call_id)
            self.started.discard(message.tool_call_id)

    def start_tool(self, call: ToolCall) -> None:
        """在执行工具前记录开始事件。"""
        self.record("tool_start", {"id": call.id, "name": call.name})
        self.started.add(call.id)

    def repair_pending(self) -> None:
        """为未完成的工具调用补写错误结果，不重新执行。"""
        for call in list(self.pending.values()):
            if call.id in self.started:  # 已开始的调用无法确定是否完成，需要用户检查实际状态。
                detail = (
                    "TOOL_OUTCOME_UNKNOWN: execution was interrupted. Its side effects may "
                    "have occurred. Inspect external state before retrying a mutation."
                )
            else:
                detail = "TOOL_NOT_STARTED: this call was interrupted before dispatch."
            self.append(Message(role="tool", tool_call_id=call.id, content="Error: " + detail))
