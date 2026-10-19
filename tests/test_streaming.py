from contextlib import AbstractContextManager
from io import StringIO
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionChunk
from rich.console import Console

from xsh.cli_output import CliOutput
from xsh.model import OpenAIModel


class Stream(AbstractContextManager):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def __exit__(self, *args):
        self.closed = True


def chunk(delta=None, finish=None, usage=None):
    return ChatCompletionChunk.model_validate(dict(
        id="test", object="chat.completion.chunk", created=0, model="test",
        choices=[] if delta is None else [dict(index=0, delta=delta, finish_reason=finish)],
        usage=usage,
    ))


def model_for(chunks):
    stream = Stream(chunks)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: stream)))
    return OpenAIModel(client, "test"), stream


def test_stream_assembles_text_reasoning_tools_and_usage():
    model, stream = model_for([
        chunk(dict(content="Hello", reasoning_content="think", tool_calls=[dict(index=0, id="call_1", type="function", function=dict(name="read", arguments='{'))])),
        chunk(dict(content=" world", tool_calls=[dict(index=0, function=dict(arguments='"path":"a"}'))])),
        chunk({}, "tool_calls"),
        chunk(usage=dict(prompt_tokens=1, completion_tokens=2, total_tokens=3)),
    ])
    seen = []
    result = model.complete(model.build_request([], []), seen.append)
    assert seen == ["Hello", " world"]
    assert result.message.content == "Hello world"
    assert result.message.reasoning_content == "think"
    assert result.message.tool_calls[0].arguments == '{"path":"a"}'
    assert result.usage["total_tokens"] == 3
    assert stream.closed
    assert model.build_request([], [dict(type="function")])["stream"] is True


def test_truncated_tool_calls_are_discarded():
    model, _ = model_for([chunk(dict(tool_calls=[dict(index=0, function=dict(arguments="{"))])), chunk({}, "length")])
    assert model.complete({}).message.tool_calls == []


def test_unfinished_stream_is_an_error_and_closes():
    model, stream = model_for([chunk(dict(content="partial"))])
    with pytest.raises(ValueError, match="finish reason"):
        model.complete({})
    assert stream.closed


def test_pipe_output_is_incremental_and_not_duplicated():
    buffer = StringIO()
    output = CliOutput(console=Console(file=buffer, force_terminal=False))
    output.report("assistant_start", "")
    output.report("assistant_delta", "**Hello**")
    assert buffer.getvalue() == "**Hello**"
    output.report("assistant_delta", " world")
    output.report("assistant_end", "")
    assert buffer.getvalue() == "**Hello** world\n"


def test_terminal_keeps_full_long_answer():
    buffer = StringIO()
    output = CliOutput(console=Console(file=buffer, force_terminal=True, width=60, height=5))
    output.report("assistant_start", "")
    output.report("assistant_delta", "\n\n".join(f"Line {i}" for i in range(20)))
    output.report("assistant_end", "")
    assert "Line 0" in buffer.getvalue()
    assert "Line 19" in buffer.getvalue()
    assert output._live is None


@pytest.mark.parametrize("interrupted", [False, True])
def test_agent_stream_lifecycle_and_session(tmp_path, interrupted):
    from xsh.agent import Agent
    from xsh.messages import Message, ModelResponse
    from xsh.session import Session
    from xsh.tools.base import ToolRegistry

    class Model:
        def build_request(self, messages, tools):
            return {}

        def complete(self, request, on_text=None):
            on_text("hello")
            if interrupted:
                raise KeyboardInterrupt
            return ModelResponse(Message(role="assistant", content="hello"), "stop")

    session = Session.create(tmp_path / "session.jsonl", tmp_path, "test")
    events = []
    result = Agent(Model(), session, ToolRegistry([]), report=lambda kind, text: events.append((kind, text))).run("hi")
    assert result.status == ("cancelled" if interrupted else "completed")
    assert events[-1] == ("assistant_end", "")
    assert events.count(("assistant_delta", "hello")) == 1
    restored = Session.load(session.path)
    assert restored.messages[-1].role == ("user" if interrupted else "assistant")
