"""permissions.py - 可选的工具权限策略（路径/命令拒绝清单）。

在工作区状态目录放置 `.xsh/permissions.json` 即可启用，例如：

    {"deny_paths": ["**/.env", "secrets/**"], "deny_commands": ["rm -rf *", "git push*"]}

- 未配置文件时一切照旧（允许）。
- `deny_paths` 拒绝对其匹配路径的**读取与写入**（read/write/edit/multiedit）。
- `deny_commands` 拒绝匹配的 shell 命令。
"""

import fnmatch
import json
from pathlib import Path


class Permissions:
    def __init__(self, deny_paths: list[str] | None = None, deny_commands: list[str] | None = None):
        self.deny_paths = [pattern for pattern in (deny_paths or []) if pattern]
        self.deny_commands = [pattern for pattern in (deny_commands or []) if pattern]

    @classmethod
    def load(cls, path: Path) -> "Permissions":
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        def as_list(key: str) -> list[str]:
            value = raw.get(key)
            return [str(item) for item in value] if isinstance(value, list) else []

        return cls(as_list("deny_paths"), as_list("deny_commands"))

    def path_allowed(self, path: Path) -> bool:
        text = str(path)
        name = Path(text).name
        return not any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(name, pattern) for pattern in self.deny_paths)

    def command_allowed(self, command: str) -> bool:
        return not any(fnmatch.fnmatch(command, pattern) for pattern in self.deny_commands)

    def require_path(self, path: Path) -> None:
        if not self.path_allowed(path):
            raise ValueError(f"Access to {path} is denied by the permission policy")

    def require_command(self, command: str) -> None:
        if not self.command_allowed(command):
            raise ValueError("Command denied by the permission policy")
