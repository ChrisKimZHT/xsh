"""Tests for the optional foreground shell tool."""

from pathlib import Path

import pytest

from xsh.tools.shell import ShellArgs, ShellTools


@pytest.fixture
def shell(tmp_path: Path) -> ShellTools:
    return ShellTools(tmp_path)


def test_successful_command_returns_output_and_zero_code(shell: ShellTools) -> None:
    out = shell.execute(ShellArgs(command="echo hello"))
    assert out.startswith("[exit code: 0]")
    assert "hello" in out


def test_failing_command_reports_nonzero_code(shell: ShellTools) -> None:
    out = shell.execute(ShellArgs(command="exit 3"))
    assert out.startswith("[exit code: 3]")


def test_command_runs_in_workspace(shell: ShellTools, tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    out = shell.execute(ShellArgs(command="ls"))
    assert "marker.txt" in out


def test_timeout_is_flagged(shell: ShellTools) -> None:
    out = shell.execute(ShellArgs(command="sleep 5", timeout_seconds=1))
    assert "[timed out" in out


def test_shell_requires_an_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ValueError, match="required"):
        ShellTools(tmp_path)
