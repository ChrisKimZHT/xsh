"""hooks.py - 可选的工具事件钩子（pre/post tool use）。

在工作区状态目录放置 `.xsh/hooks.json` 即可启用，例如：

    {"pre_tool": "echo checking", "post_tool": "./scripts/format.sh"}

- 仅在启用且有配置文件时生效，且需要与 shell 工具相同的授权（只有允许 shell 时
  才会真正执行命令）。
- `pre_tool` 返回非零退出码时**拦截该次工具调用**，把钩子输出作为工具错误返回。
- `post_tool` 仅作观察，不影响结果。
- 钩子通过环境变量拿到上下文：XSH_TOOL_NAME / XSH_TOOL_ARGUMENTS / XSH_WORKSPACE。
"""

import json
import os
import subprocess
from pathlib import Path

_PHASES = ("pre_tool", "post_tool")
_MAX_OUTPUT = 4000
_TIMEOUT_SECONDS = 60


class Hooks:
    def __init__(self, commands: dict[str, str], workspace: Path, timeout: int = _TIMEOUT_SECONDS):
        self.commands = {phase: command for phase, command in commands.items() if command.strip()}
        self.workspace = Path(workspace)
        self.timeout = timeout

    @classmethod
    def load(cls, path: Path, *, enabled: bool) -> "Hooks | None":
        """读取钩子配置；未启用、文件缺失或无效时返回 None（不阻断主流程）。"""
        path = Path(path)
        if not enabled or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        commands = {phase: str(raw.get(phase, "")) for phase in _PHASES}
        hooks = cls(commands, path.parent.parent)
        return hooks if hooks.commands else None

    def run(self, phase: str, *, name: str, arguments: str) -> tuple[int, str]:
        """执行某阶段的钩子，返回 (退出码, 输出)。超时/异常不抛出，转为非零/零码。"""
        command = self.commands.get(phase, "")
        if not command:
            return 0, ""
        environment = {**os.environ, "XSH_TOOL_NAME": name, "XSH_TOOL_ARGUMENTS": arguments, "XSH_WORKSPACE": str(self.workspace)}
        try:
            completed = subprocess.run(
                command, shell=True, cwd=self.workspace, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=self.timeout, text=True,
            )
        except subprocess.TimeoutExpired:
            return 124, f"hook timed out after {self.timeout}s"
        except OSError as error:
            return 1, f"hook failed to start: {error}"
        output = (completed.stdout or "").strip()
        return completed.returncode, output[:_MAX_OUTPUT]
