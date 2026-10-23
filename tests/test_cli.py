"""Tests for CLI-level helpers."""

import pytest

from xsh.cli import _handle_sigterm


def test_sigterm_handler_raises_keyboard_interrupt() -> None:
    with pytest.raises(KeyboardInterrupt):
        _handle_sigterm(15, None)
