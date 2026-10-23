"""Tests for CLI-level helpers."""

import pytest

from xsh.cli import _handle_sigterm, parser


def test_sigterm_handler_raises_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        _handle_sigterm(15, None)


def test_version_flag_exits_cleanly(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parser().parse_args(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("xsh ")
