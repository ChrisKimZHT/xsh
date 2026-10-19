"""A tool is a schema and a function. Errors become observations for the model."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from xsh.messages import Message, ToolCall


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass
class Tool:
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


def bounded(text: str, limit: int = 64000) -> str:
    marker = "\n[Output truncated; request a smaller range or narrower search.]"
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self.tools = {tool.name: tool for tool in tools}  # make a name->tool map
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate tool names")

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> Message:
        try:
            tool = self.tools.get(call.name)
            if tool is None:
                raise ValueError(f"Unknown tool: {call.name}")
            args = tool.parameters.model_validate_json(call.arguments)
            content = tool.execute(args)
        except Exception as error:
            # KeyboardInterrupt deliberately escapes so the loop can stop and repair history.
            content = f"Error: {type(error).__name__}: {error}"

        return Message(
            role="tool",
            tool_call_id=call.id,
            content=bounded(content),
        )
