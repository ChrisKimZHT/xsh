"""Tests for terminal event rendering, using an injected in-memory console."""

import io
from pathlib import Path

import pytest
from rich.console import Console

import xsh.terminal as terminal_module
from xsh.agent import TurnResult
from xsh.messages import Message
from xsh.session import Session
from xsh.terminal import Terminal


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> tuple[Terminal, io.StringIO]:
    buffer = io.StringIO()

    def factory(*args, **kwargs):  # noqa: ANN001
        kwargs.pop("stderr", None)
        return Console(file=buffer, force_terminal=True, width=100, height=40)

    monkeypatch.setattr(terminal_module, "Console", factory)
    return Terminal(), buffer


def test_report_events_render_without_crashing(terminal: tuple[Terminal, io.StringIO]) -> None:
    term, buffer = terminal
    for kind, text in [
        ("turn_start", ""),
        ("readiness", "[xsh] ready"),
        ("retry", "Transient error; retry 1/10"),
        ("recovery", "Recovered 1 tool call"),
        ("compaction", "compacting"),
        ("step", "Turn 1, Step 1"),
        ("tool", "shell"),
        ("tool_start", ""),
        ("tool_end", ""),
    ]:
        term.report(kind, text)
    output = buffer.getvalue()
    assert "Turn 1, Step 1" in output
    assert "[xsh] ready" in output


def test_outcome_and_history_render(terminal: tuple[Terminal, io.StringIO], tmp_path: Path) -> None:
    term, buffer = terminal
    result = TurnResult(status="completed", steps=2, text="hi", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}, context_tokens=5)
    term.context_window = 1000
    term.outcome(result)

    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="hello"))
    session.append(Message(role="assistant", content="world"))
    term.history(session)

    output = buffer.getvalue()
    assert "Status: Completed" in output
    assert "hello" in output
    assert "Turn 1" in output


def test_error_goes_to_its_console(terminal: tuple[Terminal, io.StringIO]) -> None:
    term, buffer = terminal
    term.error("boom")
    assert "boom" in buffer.getvalue()


def test_find_reports_matches(terminal: tuple[Terminal, io.StringIO], tmp_path: Path) -> None:
    term, buffer = terminal
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="find this HELLO"))
    term.find(session, "hello")
    assert "match" in buffer.getvalue()
    term.find(session, "absent-token")
    assert "No matches" in buffer.getvalue()


def test_find_matches_tool_call_arguments(terminal: tuple[Terminal, io.StringIO], tmp_path: Path) -> None:
    from xsh.messages import ToolCall

    term, buffer = terminal
    session = Session.create(tmp_path / "t.jsonl", tmp_path, "system prompt")
    session.append(Message(role="assistant", content=None, tool_calls=[ToolCall(id="1", name="read", arguments='{"file_path": "unique_path.txt"}')]))
    term.find(session, "unique_path")
    assert "match" in buffer.getvalue()


def test_usage_renders_totals(terminal: tuple[Terminal, io.StringIO], tmp_path: Path) -> None:
    term, buffer = terminal
    term.context_window = 1000
    session = Session.create(tmp_path / "u.jsonl", tmp_path, "system prompt")
    session.record("turn_end", {"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
    term.usage(session)
    assert "Session usage" in buffer.getvalue()
    assert "10" in buffer.getvalue()
    assert "Context window: 1,000 tokens" in buffer.getvalue()


def test_sessions_renders_entries(terminal: tuple[Terminal, io.StringIO]) -> None:
    term, buffer = terminal
    term.sessions([])
    assert "No saved sessions" in buffer.getvalue()
    term.sessions([(1_700_000_000_000_000_000, 123, "a.jsonl")])
    assert "a.jsonl" in buffer.getvalue()
    term.sessions([(1_700_000_000_000_000_000, 123, "cur.jsonl")], current="cur.jsonl")
    assert "*" in buffer.getvalue()


def test_stats_renders_overview(terminal: tuple[Terminal, io.StringIO], tmp_path: Path) -> None:
    from xsh.messages import ToolCall

    term, buffer = terminal
    session = Session.create(tmp_path / "st.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="hi"))
    session.append(Message(role="assistant", content=None, tool_calls=[ToolCall(id="1", name="read", arguments="{}")]))
    term.stats(session)
    out = buffer.getvalue()
    assert "Session stats" in out and "Tool calls: 1" in out
    assert "Session file:" in out


def test_report_unknown_kind_is_printed(terminal: tuple[Terminal, io.StringIO]) -> None:
    term, buffer = terminal
    term.report("custom-kind", "hello custom")
    assert "hello custom" in buffer.getvalue()
