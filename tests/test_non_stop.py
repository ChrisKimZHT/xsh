"""Tests for non-stop task parsing and Turn scheduling."""

import pytest

import xsh.non_stop as non_stop
from xsh.agent import TurnResult, is_transient_error
from xsh.non_stop import NonStopTask, run_non_stop


class _FakeAgent:
    def __init__(self, results: list[TurnResult]) -> None:
        self.results = list(results)
        self.prompts: list[str] = []

    def run(self, prompt: str) -> TurnResult:
        self.prompts.append(prompt)
        return self.results.pop(0)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(non_stop.time, "sleep", slept.append)
    return slept


def _run(agent: _FakeAgent, **kwargs) -> int:
    return run_non_stop(agent, NonStopTask("task"), lambda result: None, **kwargs)


def test_transient_error_is_retried(no_sleep: list[float]) -> None:
    agent = _FakeAgent([
        TurnResult("error", steps=1, error="RateLimitError: 429", retryable=True),
        TurnResult("completed", steps=1, text="done"),
        TurnResult("cancelled", steps=0),
    ])
    assert _run(agent) == 130
    assert len(agent.prompts) == 3
    assert no_sleep == [15.0]


def test_transient_error_gives_up_after_limit(no_sleep: list[float]) -> None:
    agent = _FakeAgent([
        TurnResult("error", steps=1, error="RateLimitError: 429", retryable=True)
        for _ in range(non_stop._MAX_TRANSIENT_RETRIES + 1)
    ])
    assert _run(agent, report=lambda kind, text: None) == 1
    assert len(agent.prompts) == non_stop._MAX_TRANSIENT_RETRIES + 1
    assert len(no_sleep) == non_stop._MAX_TRANSIENT_RETRIES


def test_non_retryable_error_then_recovers(no_sleep: list[float]) -> None:
    agent = _FakeAgent([
        TurnResult("error", steps=1, error="ValueError: bad", retryable=False),
        TurnResult("completed", steps=1, text="ok"),
        TurnResult("cancelled", steps=0),
    ])
    assert _run(agent) == 130
    assert len(agent.prompts) == 3
    assert no_sleep == [non_stop._FAILURE_BACKOFF_SECONDS]


def test_non_retryable_error_gives_up_after_limit(no_sleep: list[float]) -> None:
    agent = _FakeAgent([
        TurnResult("error", steps=1, error="ValueError: bad", retryable=False)
        for _ in range(non_stop._MAX_CONSECUTIVE_FAILURES + 1)
    ])
    assert _run(agent) == 1
    assert len(agent.prompts) == non_stop._MAX_CONSECUTIVE_FAILURES + 1
    assert no_sleep == [non_stop._FAILURE_BACKOFF_SECONDS] * non_stop._MAX_CONSECUTIVE_FAILURES


def test_cancelled_stops(no_sleep: list[float]) -> None:
    agent = _FakeAgent([TurnResult("cancelled", steps=0)])
    assert _run(agent) == 130


def test_is_transient_error_classification() -> None:
    import httpx
    from openai import APIStatusError, APITimeoutError

    request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
    assert is_transient_error(APITimeoutError(request=request)) is True
    assert is_transient_error(APIStatusError("rate limited", response=httpx.Response(429, request=request), body=None)) is True
    assert is_transient_error(APIStatusError("bad request", response=httpx.Response(400, request=request), body=None)) is False
    assert is_transient_error(ValueError("nope")) is False


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
