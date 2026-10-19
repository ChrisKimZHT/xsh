"""The model-visible vocabulary. No provider SDK objects enter the agent loop."""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str  # Keep raw JSON so invalid arguments can become a tool error.


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    reasoning_content: str | None = None

    @model_validator(mode="after")
    def check_shape(self) -> "Message":
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages can contain tool calls")
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate tool call ids in one assistant message")
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("Only tool messages must have a non-empty tool_call_id")
        if self.role != "assistant" and self.content is None:
            raise ValueError("Non-assistant messages require text content")
        if self.role != "assistant" and self.reasoning_content is not None:
            raise ValueError("Only assistant messages can contain reasoning_content")
        return self

    def to_wire(self) -> dict[str, Any]:
        """Return a dict suitable for sending to the model provider, with tool calls flattened."""
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        # Some compatible providers require this on tool-use continuation requests.
        if self.reasoning_content is not None:
            data["reasoning_content"] = self.reasoning_content
        return data


@dataclass(frozen=True)
class ModelResponse:
    message: Message
    finish_reason: str
    usage: dict[str, Any] = field(default_factory=dict)
