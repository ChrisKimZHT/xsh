"""Tests for CLI-level helpers."""

from pathlib import Path

import pytest

from xsh.cli import _handle_sigterm, list_sessions, main, parser


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
