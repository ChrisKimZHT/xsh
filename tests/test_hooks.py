"""Tests for optional pre/post tool-use hooks."""

import json
from pathlib import Path

from xsh.agent import Agent
from xsh.hooks import Hooks
from xsh.messages import Message, ModelResponse, ToolCall
from xsh.session import Session
from xsh.tools.base import Tool, ToolArgs, ToolRegistry


class _EchoArgs(ToolArgs):
    value: str


class _ToolModel:
    def __init__(self) -> None:
        self.calls = 0

    def build_request(self, messages, tools):  # noqa: ANN001
        return {"model": "stub", "messages": [m.to_wire() for m in messages], "tools": tools}

    def complete(self, request, on_text=None, on_reasoning=None):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                message=Message(role="assistant", content=None, tool_calls=[ToolCall(id="t1", name="echo", arguments='{"value": "hi"}')]),
                finish_reason="tool_calls",
                usage={},
            )
        return ModelResponse(message=Message(role="assistant", content="done"), finish_reason="stop", usage={})


def test_load_returns_none_when_disabled_or_missing(tmp_path: Path) -> None:
    assert Hooks.load(tmp_path / "hooks.json", enabled=False) is None
    assert Hooks.load(tmp_path / "hooks.json", enabled=True) is None


def test_load_parses_config_and_workspace(tmp_path: Path) -> None:
    directory = tmp_path / ".xsh"
    directory.mkdir()
    (directory / "hooks.json").write_text(json.dumps({"pre_tool": "true", "post_tool": ""}), encoding="utf-8")
    hooks = Hooks.load(directory / "hooks.json", enabled=True)
    assert hooks is not None
    assert hooks.workspace == tmp_path
    assert "pre_tool" in hooks.commands and "post_tool" not in hooks.commands  # 空命令被忽略


def test_run_reports_exit_code_and_output(tmp_path: Path) -> None:
    hooks = Hooks({"pre_tool": "exit 3", "post_tool": "echo done"}, tmp_path)
    assert hooks.run("pre_tool", name="read", arguments="{}")[0] == 3
    code, output = hooks.run("post_tool", name="read", arguments="{}")
    assert code == 0 and output == "done"


def test_agent_blocks_tool_on_failing_pre_hook(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    registry = ToolRegistry([Tool("echo", "echo", _EchoArgs, lambda args: f"echo:{args.value}")])
    agent = Agent(model=_ToolModel(), session=session, tools=registry, max_steps=5, hooks=Hooks({"pre_tool": "exit 7"}, tmp_path))

    assert agent.run("go").status == "completed"
    tool_messages = [message for message in session.messages if message.role == "tool"]
    assert "blocked by pre_tool hook" in (tool_messages[0].content or "")

    events = [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]
    hook_events = [event for event in events if event["type"] == "hook"]
    assert hook_events and hook_events[0]["data"]["phase"] == "pre_tool"
    assert hook_events[0]["data"]["exit"] == 7
