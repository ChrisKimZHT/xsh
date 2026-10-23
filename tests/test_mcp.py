"""Tests for the minimal MCP stdio client."""

import json
import sys
from pathlib import Path

from xsh.mcp import McpClient, load_servers, start_clients
from xsh.messages import ToolCall
from xsh.tools.base import ToolRegistry
from xsh.tools.mcp import build_mcp_tools

_FAKE_SERVER = '''
import json, sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}})
    elif method == "tools/list":
        tool = {"name": "echo", "description": "echo back",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [tool]}})
    elif method == "tools/call":
        arguments = message["params"].get("arguments", {})
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "echo:" + str(arguments.get("text", ""))}]}})
    elif "id" in message:
        send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
'''


def _write_server(tmp_path: Path) -> Path:
    server = tmp_path / "server.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    return server


def test_load_servers_tolerates_missing_and_invalid(tmp_path: Path) -> None:
    assert load_servers(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_servers(bad) == {}


def test_client_lists_and_calls_tools(tmp_path: Path) -> None:
    server = _write_server(tmp_path)
    client = McpClient("fake", sys.executable, [str(server)], tmp_path)
    client.start()
    try:
        client.initialize()
        tools = client.list_tools()
        assert tools and tools[0]["name"] == "echo"
        assert client.call_tool("echo", {"text": "hi"}) == "echo:hi"
    finally:
        client.close()


def test_mcp_tools_integrate_with_registry(tmp_path: Path) -> None:
    server = _write_server(tmp_path)
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": {"fake": {"command": sys.executable, "args": [str(server)]}}}), encoding="utf-8")

    clients = start_clients(load_servers(config), tmp_path)
    assert len(clients) == 1
    try:
        definitions = build_mcp_tools(clients)
        names = {tool.name for tool in definitions}
        assert "mcp__fake__echo" in names

        registry = ToolRegistry(definitions)
        call = ToolCall(id="1", name="mcp__fake__echo", arguments=json.dumps({"text": "world"}))
        assert registry.execute(call).content == "echo:world"
    finally:
        for client in clients:
            client.close()
