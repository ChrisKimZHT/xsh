"""permissions.py - 可选的工具权限策略（路径/命令拒绝清单）。

在工作区状态目录放置 `.xsh/permissions.json` 即可启用，例如：

    {"deny_paths": ["**/.env", "secrets/**"], "deny_commands": ["rm -rf *", "git push*"], "deny_urls": ["http://*evil*", "https://tracker.example/*"]}

- 未配置文件时一切照旧（允许）。
- `deny_paths` 拒绝对其匹配路径的**读取与写入**（read/write/edit/multiedit/glob/grep）。
- `deny_commands` 拒绝匹配的 shell 命令。
- `deny_urls` 拒绝匹配的抓取 URL，并从搜索结果中过滤掉匹配来源。
"""

import fnmatch
import json
from pathlib import Path


class Permissions:
    def __init__(self, deny_paths: list[str] | None = None, deny_commands: list[str] | None = None, deny_urls: list[str] | None = None, workspace: Path | None = None):
        self.deny_paths = [pattern for pattern in (deny_paths or []) if pattern]
        self.deny_commands = [pattern for pattern in (deny_commands or []) if pattern]
        self.deny_urls = [pattern for pattern in (deny_urls or []) if pattern]
        self.workspace = Path(workspace).resolve() if workspace is not None else None

    @classmethod
    def load(cls, path: Path, workspace: Path | None = None) -> "Permissions":
        path = Path(path)
        if not path.is_file():
            return cls(workspace=workspace)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(workspace=workspace)
        if not isinstance(raw, dict):
            return cls(workspace=workspace)

        def as_list(key: str) -> list[str]:
            value = raw.get(key)
            return [str(item) for item in value] if isinstance(value, list) else []

        return cls(as_list("deny_paths"), as_list("deny_commands"), as_list("deny_urls"), workspace=workspace)

    def path_allowed(self, path: Path) -> bool:
        path = Path(path)
        text = str(path)
        candidates = [text, path.name]
        if self.workspace is not None:
            try:
                candidates.append(path.resolve().relative_to(self.workspace).as_posix())
            except ValueError:
                pass
        return not any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates for pattern in self.deny_paths)

    def command_allowed(self, command: str) -> bool:
        return not any(fnmatch.fnmatch(command, pattern) for pattern in self.deny_commands)

    def url_allowed(self, url: str) -> bool:
        return not any(fnmatch.fnmatch(url, pattern) for pattern in self.deny_urls)

    def summary(self) -> str:
        return f"{len(self.deny_paths)} path pattern(s), {len(self.deny_commands)} command pattern(s), {len(self.deny_urls)} url pattern(s)"

    def require_path(self, path: Path) -> None:
        if not self.path_allowed(path):
            raise ValueError(f"Access to {path} is denied by the permission policy")

    def require_command(self, command: str) -> None:
        if not self.command_allowed(command):
            raise ValueError("Command denied by the permission policy")

    def require_url(self, url: str) -> None:
        if not self.url_allowed(url):
            raise ValueError(f"Access to {url} is denied by the permission policy")
