"""One adapter: OpenAI Python SDK, Chat Completions, non-streaming."""

from typing import Any, Protocol

from openai import OpenAI

from xsh.messages import Message, ModelResponse, ToolCall


class Model(Protocol):
    def build_request(self, messages: list[Message], tools: list[dict]) -> dict: ...

    def complete(self, request: dict) -> ModelResponse: ...


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
            "stream": False,
        }
        if tools:
            request["tools"] = tools
        return request

    def complete(self, request: dict) -> ModelResponse:
        # The SDK owns bounded request retries. Never wrap the whole agent turn in retry.
        response = self.client.chat.completions.create(**request)
        if not response.choices:
            raise ValueError("Provider returned no choices")
        choice = response.choices[0]
        raw = choice.message.model_dump()
        calls = []
        # A truncated/refused response may contain incomplete calls: never execute them.
        if choice.finish_reason in {"stop", "tool_calls"}:
            for call in raw.get("tool_calls") or []:
                if call.get("type") != "function":
                    raise ValueError("Only function tool calls are supported")
                calls.append(
                    ToolCall(
                        id=call["id"],
                        name=call["function"]["name"],
                        arguments=call["function"]["arguments"],
                    )
                )
        if choice.finish_reason == "tool_calls" and not calls:
            raise ValueError("Provider finished with tool_calls but returned no calls")
        message = Message(
            role="assistant",
            content=raw.get("content") or raw.get("refusal"),
            reasoning_content=raw.get("reasoning_content"),
            tool_calls=calls,
        )
        return ModelResponse(
            message=message,
            finish_reason=choice.finish_reason,
            usage=response.usage.model_dump() if response.usage else {},
        )
