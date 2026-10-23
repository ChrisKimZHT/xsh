"""Tests for the model request establishment retry loop."""

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, RateLimitError

import xsh.model as model_module
from xsh.model import OpenAIModel


class _Delta:
    def __init__(self, content=None):
        self.content = content
        self.reasoning_content = None
        self.refusal = None
        self.tool_calls = None


class _Choice:
    def __init__(self, finish_reason, delta):
        self.finish_reason = finish_reason
        self.delta = delta


class _Usage:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


class _Chunk:
    def __init__(self, content, finish_reason, usage):
        self.usage = _Usage(usage)
        self.choices = [_Choice(finish_reason, _Delta(content))]


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Completions:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return _Stream([_Chunk("hello", "stop", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})])


class _Client:
    def __init__(self, errors):
        self.chat = type("Chat", (), {"completions": _Completions(errors)})()


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(model_module.time, "sleep", slept.append)
    return slept


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def test_complete_retries_connection_and_429_then_succeeds(no_sleep) -> None:
    errors = [
        APIConnectionError(request=_request()),
        RateLimitError("slow down", response=httpx.Response(429, request=_request()), body=None),
    ]
    client = _Client(errors)
    response = OpenAIModel(client, "m", 100).complete({})
    assert response.message.content == "hello"
    assert client.chat.completions.calls == 3
    assert len(no_sleep) == 2


def test_complete_does_not_retry_non_429_status(no_sleep) -> None:
    client = _Client([APIStatusError("bad", response=httpx.Response(400, request=_request()), body=None)])
    with pytest.raises(APIStatusError):
        OpenAIModel(client, "m", 100).complete({})
    assert client.chat.completions.calls == 1
    assert no_sleep == []


def test_complete_gives_up_after_retry_limit(no_sleep, monkeypatch) -> None:
    monkeypatch.setattr(model_module, "_MAX_RATE_LIMIT_RETRIES", 2)
    client = _Client([RateLimitError("again", response=httpx.Response(429, request=_request()), body=None) for _ in range(5)])
    with pytest.raises(RateLimitError):
        OpenAIModel(client, "m", 100).complete({})
    assert client.chat.completions.calls == 3  # 初始 1 次 + 2 次重试
