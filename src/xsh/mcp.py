"""mcp.py - 极简 MCP（Model Context Protocol）stdio 客户端。

从工作区状态目录的 `.xsh/mcp.json` 读取服务器定义：

    {"servers": {"name": {"command": "npx", "args": ["-y", "some-mcp-server"]}}}

以**行分隔的 JSON-RPC 2.0** 与服务器通信，握手后列出并调用其工具。
任何失败都优雅降级：跳过该服务器，不影响主流程。
"""

import json
import subprocess
from pathlib import Path

_PROTOCOL_VERSION = "2024-11-05"


class McpError(RuntimeError):
    """MCP 通信或协议错误。"""


class McpClient:
    def __init__(self, name: str, command: str, args: list[str], cwd: Path, timeout: int = 30):
        self.name = name
        self.command = command
        self.args = list(args)
        self.cwd = Path(cwd)
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self._id = 0

    def start(self) -> None:
        self.process = subprocess.Popen(
            [self.command, *self.args], cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1,
        )

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None:
            raise McpError("server is not running")
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _read_response(self, request_id: int) -> dict:
        if self.process is None or self.process.stdout is None:
            raise McpError("server is not running")
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise McpError("server closed the connection")
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise McpError(str(message["error"]))
            result = message.get("result", {})
            return result if isinstance(result, dict) else {}

    def request(self, method: str, params: dict) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        return self._read_response(self._id)

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def initialize(self) -> None:
        self.request("initialize", {"protocolVersion": _PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "xsh", "version": "0.1"}})
        self.notify("notifications/initialized", {})

    def list_tools(self) -> list[dict]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        return [tool for tool in tools if isinstance(tool, dict)] if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict) -> str:
        return _flatten(self.request("tools/call", {"name": name, "arguments": arguments}))

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.terminate()
        except OSError:
            pass
        self.process = None


def _flatten(result: dict) -> str:
    parts = []
    for item in result.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        elif isinstance(item, dict):
            parts.append(json.dumps(item, ensure_ascii=False))
    text = "\n".join(parts)
    if result.get("isError"):
        text = "Error: " + text
    return text or json.dumps(result, ensure_ascii=False)


def load_servers(path: Path) -> dict[str, dict]:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    servers = raw.get("servers") if isinstance(raw, dict) else None
    return servers if isinstance(servers, dict) else {}


def start_clients(servers: dict[str, dict], cwd: Path) -> list[McpClient]:
    """启动并完成握手的服务器；单个失败只跳过该服务器。"""
    clients: list[McpClient] = []
    for name, spec in servers.items():
        if not isinstance(spec, dict) or not spec.get("command"):
            continue
        client = McpClient(str(name), str(spec["command"]), list(spec.get("args", [])), cwd)
        try:
            client.start()
            client.initialize()
        except (OSError, McpError, ValueError):
            client.close()
            continue
        clients.append(client)
    return clients
