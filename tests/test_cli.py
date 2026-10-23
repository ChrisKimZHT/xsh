"""Tests for CLI-level helpers."""

from pathlib import Path

import pytest

from xsh.cli import _handle_sigterm, fork_session, list_sessions, main, parser, resolve_session
from xsh.messages import Message
from xsh.session import Session


def test_sigterm_handler_raises_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        _handle_sigterm(15, None)


def test_version_flag_exits_cleanly(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parser().parse_args(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("xsh ")


def test_list_sessions_returns_sorted_entries(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir()
    (directory / "a.jsonl").write_text("x", encoding="utf-8")
    (directory / "b.jsonl").write_text("yy", encoding="utf-8")
    entries = list_sessions(directory)
    assert {entry[2] for entry in entries} == {"a.jsonl", "b.jsonl"}
    assert list_sessions(tmp_path / "missing") == []


def test_list_sessions_flag_prints_and_exits(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    directory = tmp_path / ".xsh" / "sessions"
    directory.mkdir(parents=True)
    (directory / "session-1.jsonl").write_text("x\n", encoding="utf-8")
    assert main(["--list-sessions", "--workspace", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "session-1.jsonl" in out


def test_fork_session_copies_and_isolates(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    source = Session.create(directory / "orig.jsonl", tmp_path, "system prompt")
    source.append(Message(role="user", content="hi"))

    forked = fork_session(source.path, directory)
    assert forked != source.path and forked.is_file()
    loaded = Session.load(forked)
    assert loaded.turn_count == 1

    loaded.append(Message(role="assistant", content="only in fork"))
    assert Session.load(source.path).turn_count == 1  # 原会话未受影响


def test_fork_session_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Session not found"):
        fork_session(tmp_path / "nope.jsonl", tmp_path / "sessions")


def test_dump_prompt_prints_system_prompt(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSH_BASE_URL", "https://example/v1")
    monkeypatch.setenv("XSH_MODEL", "m")
    monkeypatch.setenv("XSH_API_KEY", "k")
    assert main(["--dump-prompt", "--workspace", str(tmp_path)]) == 0
    assert "You are an AI agent powered by xsh." in capsys.readouterr().out


def test_list_tools_prints_names(tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSH_BASE_URL", "https://example/v1")
    monkeypatch.setenv("XSH_MODEL", "m")
    monkeypatch.setenv("XSH_API_KEY", "k")
    assert main(["--list-tools", "--workspace", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "read\t" in out
    assert "todo\t" in out


def test_resolve_session_by_name_prefix(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir()
    (directory / "20260101-000000-aaaa.jsonl").write_text("x", encoding="utf-8")
    newer = directory / "20260102-000000-bbbb.jsonl"
    newer.write_text("y", encoding="utf-8")

    assert resolve_session(Path("20260102"), directory) == newer.resolve()
    assert resolve_session(newer, directory) == newer.resolve()
    assert resolve_session(Path("2026"), directory) == newer.resolve()  # 多个前缀匹配时取最新
    with pytest.raises(ValueError, match="Session not found"):
        resolve_session(Path("nope"), directory)
