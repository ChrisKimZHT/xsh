"""Tests for non-stop task parsing."""

import pytest

from xsh.non_stop import NonStopTask


def test_plain_task_has_no_continuation() -> None:
    task = NonStopTask.parse("  do the thing  ")
    assert task.prompt == "do the thing"
    assert task.continuation == ""
    assert task.next_prompt == "do the thing"


def test_task_with_continuation_block() -> None:
    text = "primary task\n\n<continue-prompt>\nkeep going\n</continue-prompt>"
    task = NonStopTask.parse(text)
    assert task.prompt == "primary task"
    assert task.continuation == "keep going"
    assert task.next_prompt == "primary task\n\nkeep going"


def test_legacy_promot_block_is_still_accepted() -> None:
    text = "primary task\n\n<continue-promot>\nkeep going\n</continue-promot>"
    task = NonStopTask.parse(text)
    assert task.prompt == "primary task"
    assert task.continuation == "keep going"


def test_continuation_block_must_end_the_prompt() -> None:
    with pytest.raises(ValueError):
        NonStopTask.parse("task\n<continue-prompt>go</continue-prompt>\ntrailing")


def test_empty_task_is_rejected() -> None:
    with pytest.raises(ValueError):
        NonStopTask.parse("   ")


def test_from_stored_splits_legacy_unsplit_prompt() -> None:
    stored = "task\n\n<continue-prompt>\nresume now\n</continue-prompt>"
    task = NonStopTask.from_stored(stored, "")
    assert task.prompt == "task"
    assert task.continuation == "resume now"


def test_from_stored_keeps_explicit_continuation() -> None:
    task = NonStopTask.from_stored("task", "keep going")
    assert task.prompt == "task"
    assert task.continuation == "keep going"

    plain = NonStopTask.from_stored("just a task", "")
    assert plain.prompt == "just a task"
    assert plain.continuation == ""
