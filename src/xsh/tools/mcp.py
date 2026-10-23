"""tools/mcp.py - 把 MCP 服务器暴露的工具接入本地工具注册表。"""

from pydantic import ConfigDict

from xsh.mcp import McpClient
from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_MCP_GUIDANCE = (
    "Tools named `mcp__<server>__<tool>` come from external MCP servers configured in "
    "`.xsh/mcp.json`. Call them like any other tool; arguments follow the server's schema."
)


class McpToolArgs(ToolArgs):
    """MCP 工具的宽松参数模型：字段由服务器 schema 决定。"""

    model_config = ConfigDict(extra="allow", strict=False)


def _definition(client: McpClient, tool_name: str, description: str, remote_name: str, schema: dict) -> Tool:
    def execute(args: McpToolArgs) -> str:
        arguments = dict(args.model_dump())
        try:
            return client.call_tool(remote_name, arguments)
        except Exception as error:  # noqa: BLE001
            return f"Error: MCP call failed: {type(error).__name__}: {error}"

    return Tool(
        tool_name,
        description,
        McpToolArgs,
        execute,
        guidance=_MCP_GUIDANCE,
        prompt_sections=(PromptSection("tool:mcp", 300, _MCP_GUIDANCE),),
        schema_override=schema,
    )


def build_mcp_tools(clients: list[McpClient]) -> list[Tool]:
    definitions: list[Tool] = []
    for client in clients:
        try:
            tools = client.list_tools()
        except Exception:  # noqa: BLE001
            continue
        for spec in tools:
            name = spec.get("name")
            if not name:
                continue
            schema = spec.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            description = str(spec.get("description") or f"{name} (via MCP server {client.name})")
            definitions.append(_definition(client, f"mcp__{client.name}__{name}", description, str(name), schema))
    return definitions
