"""One adapter: OpenAI Python SDK, Chat Completions, streaming."""

from collections.abc import Callable
from typing import Any, Protocol

from openai import OpenAI

from xsh.messages import Message, ModelResponse, ToolCall


class Model(Protocol):
    def build_request(self, messages: list[Message], tools: list[dict]) -> dict: 
        pass

    def complete(self, request: dict, on_text: Callable[[str], None] | None = None) -> ModelResponse: ...


class OpenAIModel:
    def __init__(self, client: OpenAI, model: str, max_tokens: int = 65536):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def build_request(self, messages: list[Message], tools: list[dict]) -> dict:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_wire() for message in messages],
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = tools
        return request

    def complete(self, request: dict, on_text: Callable[[str], None] | None = None) -> ModelResponse:
        # The SDK owns bounded request retries. Never wrap the whole agent turn in retry.
        content: list[str] = []
        refusals: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason = None
        usage = {}
        with self.client.chat.completions.create(**request) as stream:
            for chunk in stream:
                if chunk.usage:
                    usage = chunk.usage.model_dump()
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                for value, parts in ((delta.content, content), (delta.refusal, refusals)):
                    if value:
                        parts.append(value)
                        if on_text:
                            on_text(value)
                if value := getattr(delta, "reasoning_content", None):
                    reasoning.append(value)
                for part in delta.tool_calls or []:
                    if part.type not in {None, "function"}:
                        raise ValueError("Only function tool calls are supported")
                    call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                    if part.id:
                        call["id"] += part.id
                    if part.function:
                        call["name"] += part.function.name or ""
                        call["arguments"] += part.function.arguments or ""
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        if finish_reason is None:
            raise ValueError("Provider stream ended without a finish reason")
        # Incomplete/truncated tool calls must never be executed.
        tool_calls = [ToolCall(**calls[index]) for index in sorted(calls)] if finish_reason in {"stop", "tool_calls"} else []
        if finish_reason == "tool_calls" and not tool_calls:
            raise ValueError("Provider finished with tool_calls but returned no calls")
        return ModelResponse(
            message=Message(
                role="assistant",
                content="".join(content) or "".join(refusals) or None,
                reasoning_content="".join(reasoning) if reasoning else None,
                tool_calls=tool_calls,
            ),
            finish_reason=finish_reason,
            usage=usage,
        )
