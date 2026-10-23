"""Tests for message and tool-call validation / wire conversion."""

import pytest
from pydantic import ValidationError

from xsh.messages import Message, ToolCall


def test_assistant_with_tool_calls_is_valid() -> None:
    call = ToolCall(id="1", name="shell", arguments="{}")
    message = Message(role="assistant", content=None, tool_calls=[call])
    wire = message.to_wire()
    assert wire["tool_calls"][0]["function"]["name"] == "shell"
    assert wire["tool_calls"][0]["type"] == "function"


def test_tool_calls_only_allowed_on_assistant() -> None:
    call = ToolCall(id="1", name="shell", arguments="{}")
    with pytest.raises(ValidationError):
        Message(role="user", content="hi", tool_calls=[call])


def test_duplicate_tool_call_ids_rejected() -> None:
    calls = [ToolCall(id="x", name="a", arguments="{}"), ToolCall(id="x", name="b", arguments="{}")]
    with pytest.raises(ValidationError):
        Message(role="assistant", tool_calls=calls)


def test_tool_call_id_only_on_tool_messages() -> None:
    with pytest.raises(ValidationError):
        Message(role="tool", content="result")  # 缺少 tool_call_id
    with pytest.raises(ValidationError):
        Message(role="user", content="hi", tool_call_id="1")  # 非 tool 不允许
    assert Message(role="tool", content="result", tool_call_id="1").to_wire()["tool_call_id"] == "1"


def test_non_assistant_requires_content() -> None:
    with pytest.raises(ValidationError):
        Message(role="user")


def test_reasoning_content_only_on_assistant() -> None:
    with pytest.raises(ValidationError):
        Message(role="user", content="hi", reasoning_content="why")


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(role="user", content="hi", unexpected=1)


def test_tool_call_requires_id_and_name() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="", name="shell", arguments="{}")
    with pytest.raises(ValidationError):
        ToolCall(id="1", name="", arguments="{}")
