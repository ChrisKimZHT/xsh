"""Tests for context compaction (estimate, validation, and a full manual compaction)."""

from pathlib import Path

import pytest

from xsh.compaction import Compactor, estimate_tokens
from xsh.messages import Message, ModelResponse, ToolCall
from xsh.session import Session


class _StubModel:
    """Minimal Model implementation returning a fixed summary."""

    def __init__(self, summary: str = "SUMMARY") -> None:
        self.summary = summary

    def build_request(self, messages, tools):  # noqa: ANN001 - matches Model protocol
        return {"model": "stub", "messages": [m.to_wire() for m in messages]}

    def complete(self, request, on_text=None, on_reasoning=None):  # noqa: ANN001
        return ModelResponse(message=Message(role="assistant", content=self.summary), finish_reason="stop", usage={})


def _session_with_history(tmp_path: Path, turns: int = 3) -> Session:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    for index in range(turns):
        session.append(Message(role="user", content=f"user {index} " + "x" * 200))
        session.append(Message(role="assistant", content=f"assistant {index} " + "y" * 200))
    return session


def test_estimate_tokens_scales_with_content() -> None:
    small = estimate_tokens([Message(role="user", content="hi")])
    large = estimate_tokens([Message(role="user", content="hi" * 1000)])
    assert small > 0
    assert large > small


@pytest.mark.parametrize(
    "kwargs",
    [
        {"retain_ratio": 0.9, "threshold": 0.5},
        {"threshold": 1.0},
        {"max_tokens": 0},
        {"context_window": 0},
    ],
)
def test_compactor_rejects_invalid_arguments(tmp_path: Path, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        Compactor(_StubModel(), **kwargs)


def test_auto_compaction_skips_below_threshold(tmp_path: Path) -> None:
    session = _session_with_history(tmp_path)
    compactor = Compactor(_StubModel(), context_window=10**9, auto=True, threshold=0.8, retain_ratio=0.16)
    assert compactor.compact(session, tools=[], manual=False) is None


def test_manual_compaction_replaces_older_messages(tmp_path: Path) -> None:
    session = _session_with_history(tmp_path)
    before_messages = len(session.messages)
    compactor = Compactor(_StubModel(), context_window=None, auto=False, threshold=0.8, retain_ratio=0.16)

    result = compactor.compact(session, tools=[], manual=True)
    assert result is not None
    assert result.removed_messages > 0
    assert len(session.messages) < before_messages
    assert session.messages[0].role == "system"
    assert "compacted-summary" in (session.messages[1].content or "")
    # 原始日志保留，且可重新加载。
    reloaded = Session.load(session.path)
    assert "compacted-summary" in (reloaded.messages[1].content or "")


def test_compaction_refuses_pending_tool_calls(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="do it"))
    session.append(Message(role="assistant", tool_calls=[ToolCall(id="1", name="shell", arguments="{}")]))
    compactor = Compactor(_StubModel(), context_window=None, auto=False)
    with pytest.raises(ValueError, match="pending tool calls"):
        compactor.compact(session, tools=[], manual=True)


def test_auto_compaction_triggers_when_over_threshold(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    pad = "z" * 1200
    for index in range(12):
        role = "user" if index % 2 == 0 else "assistant"
        session.append(Message(role=role, content=f"m{index} {pad}"))

    compactor = Compactor(_StubModel(), context_window=4000, auto=True, threshold=0.8, retain_ratio=0.16, max_tokens=200)
    result = compactor.compact(session, tools=[], manual=False)
    assert result is not None
    assert result.removed_messages > 0
    assert result.after_tokens < result.before_tokens
    assert "compacted-summary" in (session.messages[1].content or "")


def test_compaction_returns_none_without_enough_history(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="only one message"))
    compactor = Compactor(_StubModel(), context_window=None, auto=False)
    assert compactor.compact(session, tools=[], manual=True) is None


def test_compaction_keeps_tool_calls_paired_in_long_turn(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="run many tools " + "y" * 600))
    for index in range(4):
        call = ToolCall(id=f"c{index}", name="shell", arguments="{}")
        session.append(Message(role="assistant", content="step " + "z" * 400, tool_calls=[call]))
        session.append(Message(role="tool", tool_call_id=call.id, content="result " + "r" * 400))

    compactor = Compactor(_StubModel(), context_window=None, auto=False)
    result = compactor.compact(session, tools=[], manual=True)
    assert result is not None
    # 压缩后没有悬空工具调用，会话仍可加载。
    assert not session.pending
    reloaded = Session.load(session.path)
    assert not reloaded.pending
    assert all(
        not (message.tool_calls and not any(m.tool_call_id in {c.id for c in message.tool_calls} for m in reloaded.messages))
        for message in reloaded.messages
    )

