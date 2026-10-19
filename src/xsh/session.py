"""Append-only JSONL plus a small in-memory message projection; single writer only."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xsh.messages import Message, ToolCall


class Session:
    def __init__(self, path: Path, workspace: Path):
        """Initialize session storage and in-memory message state."""
        self.path = path
        self.workspace = workspace.resolve()
        self.messages: list[Message] = []
        self.pending: dict[str, ToolCall] = {}
        self.started: set[str] = set()

    @classmethod
    def create(cls, path: Path, workspace: Path, system_prompt: str) -> "Session":
        """Create a new session file with a header and system prompt."""
        # prepare session file
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass  # Never overwrite an existing session accidentally.

        # create session and initialize with system prompt
        session = cls(path, workspace)
        session.record("session", {"version": 1, "workspace": str(session.workspace)})
        session.append(Message(role="system", content=system_prompt))
        return session

    @classmethod
    def load(cls, path: Path) -> "Session":
        """Restore a recorded session and repair interrupted tool calls."""
        path = path.resolve()
        with path.open(encoding="utf-8") as file:
            events = [json.loads(line) for line in file]
        if not events or events[0].get("type") != "session":
            raise ValueError("Missing session header")
        header = events[0]["data"]
        if header["version"] != 1:
            raise ValueError("Unsupported session version")
        session = cls(path, Path(header["workspace"]))
        for event in events[1:]:
            if event["type"] == "message":
                session._accept(Message.model_validate(event["data"]))
            elif event["type"] == "tool_start":
                call_id = event["data"]["id"]
                if call_id not in session.pending:
                    raise ValueError("Tool start without a pending call")
                session.started.add(call_id)
        if not session.messages or session.messages[0].role != "system":
            raise ValueError("Missing system prompt")
        # Do not replay operations whose side effects may already have occurred.
        session.repair_pending()
        return session

    def record(self, kind: str, data: dict[str, Any]) -> None:
        """Append a timestamped event to the session file."""
        event = {"time": datetime.now(UTC).isoformat(), "type": kind, "data": data}
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(line + "\n")

    def append(self, message: Message) -> None:
        """Validate, persist, and accept a message."""
        self._validate_next(message)
        self.record("message", message.model_dump())
        self._accept(message)

    def _validate_next(self, message: Message) -> None:
        """Ensure the message preserves tool-call and result pairing."""
        if self.pending and message.role != "tool":
            raise ValueError("Tool calls must receive results before the next message")
        if message.role == "tool" and message.tool_call_id not in self.pending:
            raise ValueError("Tool result has no matching pending call")

    def _accept(self, message: Message) -> None:
        """Add a message to memory and update pending tool calls."""
        self._validate_next(message)
        self.messages.append(message)
        if message.tool_calls:
            self.pending = {call.id: call for call in message.tool_calls}
        if message.tool_call_id:
            self.pending.pop(message.tool_call_id)
            self.started.discard(message.tool_call_id)

    def start_tool(self, call: ToolCall) -> None:
        """Record that a tool call is about to execute."""
        self.record("tool_start", {"id": call.id, "name": call.name})
        self.started.add(call.id)

    def repair_pending(self) -> None:
        """Close interrupted tool calls with error results without replaying them."""
        for call in list(self.pending.values()):
            if call.id in self.started:
                detail = (
                    "TOOL_OUTCOME_UNKNOWN: execution was interrupted. Its side effects may "
                    "have occurred. Inspect external state before retrying a mutation."
                )
            else:
                detail = "TOOL_NOT_STARTED: this call was interrupted before dispatch."
            self.append(Message(role="tool", tool_call_id=call.id, content="Error: " + detail))
