"""tools/base.py - 工具相关的基类以及工具注册表"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from xsh.config import Settings
from xsh.messages import Message, ToolCall

_OUTPUT_LIMIT = 64_000


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
    output_limit: int = _OUTPUT_LIMIT

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters.model_json_schema(),
            },
        }


def bounded(text: str, limit: int = _OUTPUT_LIMIT) -> str:
    marker = "\n[Output truncated; request a smaller range or narrower search.]"
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


class ToolRegistry:
    """工具注册表，维护工具列表并提供执行接口"""

    def __init__(self, tools: list[Tool]):
        """初始化工具注册表，确保工具名称唯一"""
        self.tools = {tool.name: tool for tool in tools}  # make a name->tool map
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool names")

    @classmethod
    def default(
        cls,
        workspace: Path,
        settings: Settings,
        *,
        record: Callable[[str, dict], None] | None = None,
        allow_shell: bool = False,
    ) -> "ToolRegistry":
        """准备默认工具列表"""
        from xsh.tools.files import FileTools
        from xsh.tools.shell import ShellTools
        from xsh.tools.web import WebTools

        definitions = FileTools(workspace).definitions()
        definitions.extend(WebTools(settings, record=record).definitions())
        if allow_shell:
            definitions.extend(ShellTools(workspace).definitions())
        return cls(definitions)

    def schemas(self) -> list[dict]:
        """返回所有工具的 JSON Schema 列表"""
        return [tool.schema() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> Message:
        """执行工具调用，并返回工具结果消息"""
        output_limit = _OUTPUT_LIMIT
        try:
            tool = self.tools.get(call.name)
            if tool is None:
                raise ValueError(f"Unknown tool: {call.name}")
            output_limit = tool.output_limit
            args = tool.parameters.model_validate_json(call.arguments)
            content = tool.execute(args)
        except Exception as error:
            content = f"Error: {type(error).__name__}: {error}"

        return Message(
            role="tool",
            tool_call_id=call.id,
            content=bounded(content, output_limit),  # 限制完整工具输出长度，防止过长
        )
