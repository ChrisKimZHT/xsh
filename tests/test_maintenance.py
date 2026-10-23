"""Tests for the offline session-file compaction utility."""

import json
from pathlib import Path

from xsh.maintenance import compact_session_file
from xsh.messages import Message
from xsh.session import Session


def _session(tmp_path: Path) -> Session:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="hi"))
    session.append(Message(role="assistant", content="ok"))
    session.record("request", {"step": 1, "messages": 2, "tools": 0})
    session.record("response", {"step": 1, "finish_reason": "stop", "usage": {}})
    session.record("custom_future_event", {"x": 1})
    return session


def test_compact_drops_redundant_events_and_keeps_unknown(tmp_path: Path) -> None:
    session = _session(tmp_path)
    stats = compact_session_file(session.path)
    assert stats["changed"] is True
    assert stats["events_after"] < stats["events_before"]

    types = [json.loads(line)["type"] for line in session.path.read_text(encoding="utf-8").splitlines()]
    assert "request" not in types
    assert "response" not in types
    assert "custom_future_event" in types  # 未知事件必须保留

    loaded = Session.load(session.path)
    assert loaded.turn_count == 1
    assert loaded.messages[-1].content == "ok"
    assert (tmp_path / "s.jsonl.bak").is_file()


def test_compact_is_noop_when_nothing_to_drop(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "n.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="hi"))
    stats = compact_session_file(session.path)
    assert stats["changed"] is False
    assert not (tmp_path / "n.jsonl.bak").exists()
