"""Tests for the Agent Step loop and session logging."""

import json
from pathlib import Path

from xsh.agent import Agent
from xsh.messages import Message, ModelResponse, ToolCall
from xsh.session import Session
from xsh.tools.base import Tool, ToolArgs, ToolRegistry


class _StubModel:
    def build_request(self, messages, tools):  # noqa: ANN001
        return {"model": "stub", "messages": [m.to_wire() for m in messages], "tools": tools}

    def complete(self, request, on_text=None, on_reasoning=None):  # noqa: ANN001
        return ModelResponse(
            message=Message(role="assistant", content="done"),
            finish_reason="stop",
            usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        )


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


def _agent(tmp_path: Path) -> Agent:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    return Agent(model=_StubModel(), session=session, tools=ToolRegistry([]), max_steps=3)


def test_turn_completes_and_counts_progress(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = agent.run("hello")
    assert result.status == "completed"
    assert result.text == "done"
    assert agent.session.turn_count == 1
    assert agent.session.step_count == 1
    assert [m.role for m in agent.session.messages] == ["system", "user", "assistant"]


def test_request_event_stores_a_summary_not_the_full_body(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    agent.run("hello")
    events = [json.loads(line) for line in agent.session.path.read_text(encoding="utf-8").splitlines()]
    requests = [event for event in events if event["type"] == "request"]
    assert requests, "a request event should be recorded"
    data = requests[0]["data"]
    assert "body" not in data  # 不再落盘完整请求体，避免 O(n^2) 膨胀
    assert data["messages"] >= 2

    # 恢复会话仍然成功。
    reloaded = Session.load(agent.session.path)
    assert reloaded.messages[-1].content == "done"


def test_tool_execution_is_recorded_with_timing(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    registry = ToolRegistry([Tool("echo", "echo", _EchoArgs, lambda args: f"echo:{args.value}")])
    agent = Agent(model=_ToolModel(), session=session, tools=registry, max_steps=5)

    result = agent.run("use the tool")
    assert result.status == "completed"

    events = [json.loads(line) for line in session.path.read_text(encoding="utf-8").splitlines()]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert ends
    assert ends[0]["data"]["name"] == "echo"
    assert ends[0]["data"]["chars"] == len("echo:hi")
    assert ends[0]["data"]["seconds"] >= 0
