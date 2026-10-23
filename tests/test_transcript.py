"""Tests for Markdown transcript export."""

from pathlib import Path

import pytest

from xsh.messages import Message, ToolCall
from xsh.session import Session
from xsh.transcript import export_transcript, render_transcript


def test_render_transcript_includes_roles_and_tools(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="hello"))
    session.append(Message(role="assistant", content="hi", tool_calls=[ToolCall(id="1", name="read", arguments='{"file_path": "a"}')]))

    text = render_transcript(session.messages)
    assert "# xsh transcript" in text
    assert "## 1. system" in text
    assert "## 2. user" in text
    assert "hello" in text
    assert "`read`" in text


def test_export_writes_file_and_confines_path(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="body"))

    path = export_transcript(session, tmp_path, "notes/out.md")
    assert path == (tmp_path / "notes" / "out.md").resolve()
    assert "body" in path.read_text(encoding="utf-8")

    default = export_transcript(session, tmp_path)
    assert default.is_file() and default.name.startswith("xsh-transcript-")

    with pytest.raises(ValueError, match="inside the workspace"):
        export_transcript(session, tmp_path, "../escape.md")


def test_render_transcript_appends_extra_sections(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    session.append(Message(role="user", content="body"))
    text = render_transcript(session.messages, [("Todos", "[x] done"), ("Memory", "note")])
    assert "## Todos" in text and "[x] done" in text
    assert "## Memory" in text and "note" in text
