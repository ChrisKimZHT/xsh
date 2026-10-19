"""messages.py - 消息相关的类定义"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolCall(BaseModel):
    """工具调用对象，表示模型**请求**中包含的工具调用信息"""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str  # 保持原始 JSON，以便无效参数可以成为工具错误。


class Message(BaseModel):
    """模型消息对象，表示模型**请求和响应**中的消息信息"""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def check_shape(self) -> "Message":
        """完成五个字段互斥和约束检查，确保消息对象的有效性"""
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
        """将消息对象转换为发送请求时的字典格式，符合 OpenAI 库的要求"""
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
        if self.reasoning_content is not None:
            data["reasoning_content"] = self.reasoning_content
        return data


@dataclass(frozen=True)
class ModelResponse:
    """模型响应对象，表示模型**响应**的完整结果信息"""
    message: Message
    finish_reason: str
    usage: dict[str, Any] = field(default_factory=dict)
