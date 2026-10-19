"""tools/base.py - 工具相关的基类以及工具注册表"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from xsh.constants import (
    BASE_OUTPUT_LIMIT,
    BASE_TRUNCATION_MARKER,
)
from xsh.messages import Message, ToolCall


class ToolArgs(BaseModel):
    """工具参数基类，所有工具参数类都应继承自此类"""
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass
class Tool:
    """工具定义，封装名称、描述、参数类型和执行函数"""
    name: str
    description: str
    parameters: type[ToolArgs]
    execute: Callable[[ToolArgs], str]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(),
            },
        }


def bounded(text: str, limit: int = BASE_OUTPUT_LIMIT) -> str:
    marker = BASE_TRUNCATION_MARKER
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


class ToolRegistry:
    """工具注册表，维护工具列表并提供执行接口"""

    def __init__(self, tools: list[Tool]):
        """初始化工具注册表，确保工具名称唯一"""
        self.tools = {tool.name: tool for tool in tools}  # make a name->tool map
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool names")

    def schemas(self) -> list[dict]:
        """返回所有工具的 JSON Schema 列表"""
        return [tool.schema() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> Message:
        """执行工具调用，并返回工具结果消息"""
        try:
            tool = self.tools.get(call.name)
            if tool is None:
                raise ValueError(f"Unknown tool: {call.name}")
            args = tool.parameters.model_validate_json(call.arguments)
            content = tool.execute(args)
        except Exception as error:
            content = f"Error: {type(error).__name__}: {error}"

        return Message(
            role="tool",
            tool_call_id=call.id,
            content=bounded(content),  # 限制输出长度，防止过长
        )
