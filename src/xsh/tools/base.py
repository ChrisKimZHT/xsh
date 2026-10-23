"""tools/base.py - 工具相关的基类以及工具注册表"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from xsh.config import Settings
from xsh.messages import Message, ToolCall
from xsh.prompt import PromptSection

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
    guidance: str = ""
    prompt_sections: tuple[PromptSection, ...] = ()

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
    """把文本裁剪到不超过 limit 个字符，并在截断时附加提示。

    当 limit 小于提示语长度时，绝不能返回超过 limit 的内容。
    """
    marker = "\n[Output truncated; request a smaller range or narrower search.]"
    if len(text) <= limit:
        return text
    if limit <= len(marker):
        return marker[:limit]
    return text[: limit - len(marker)] + marker


class ToolRegistry:
    """工具注册表，维护工具列表并提供执行接口"""

    def __init__(self, tools: list[Tool]):
        """初始化工具注册表，确保工具名称唯一"""
        self.tools = {tool.name: tool for tool in tools}  # make a name->tool map
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool names")

    def add(self, definitions: list[Tool]) -> None:
        """追加工具（在构建系统提示词之前调用，确保其指导文案进入提示词）。"""
        for tool in definitions:
            if tool.name in self.tools:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self.tools[tool.name] = tool

    @classmethod
    def default(
        cls,
        workspace: Path,
        settings: Settings,
        *,
        record: Callable[[str, dict], None] | None = None,
        report: Callable[[str, str], None] | None = None,
        allow_shell: bool = False,
        current_todos: Callable[[], list[dict]] | None = None,
        memory_store: object | None = None,
        skills_library: object | None = None,
    ) -> "ToolRegistry":
        """准备默认工具列表"""
        from xsh.tools.files import FileTools
        from xsh.tools.memory import MemoryTools
        from xsh.tools.shell import ShellTools
        from xsh.tools.skills import SkillTools
        from xsh.tools.todo import TodoTools
        from xsh.tools.web import WebTools

        definitions = FileTools(workspace).definitions()
        definitions.extend(WebTools(settings, record=record).definitions())
        definitions.extend(TodoTools(record=record, report=report, current=current_todos).definitions())
        if memory_store is not None:
            definitions.extend(MemoryTools(memory_store, report=report).definitions())
        if skills_library is not None:
            definitions.extend(SkillTools(skills_library).definitions())
        if allow_shell:
            definitions.extend(ShellTools(workspace).definitions())
        return cls(definitions)

    def prompt_sections(self) -> list[PromptSection]:
        """Contribute guidance only for tools advertised by this registry."""
        sections = []
        for tool in self.tools.values():
            sections.extend(tool.prompt_sections)
            if tool.guidance:
                sections.append(PromptSection(f"tool:{tool.name}", 300, tool.guidance))
        return sections

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
