"""memory.py - 跨会话长期记忆：工作区级持久笔记，并注入系统提示词。

记忆保存为 `.xsh/memory.md`（位于 gitignored 的状态目录，不污染用户提交），
条目为 Markdown 列表项。工具可追加 / 整体替换 / 删除条目；系统提示词在每次
构建时读取当前内容，使记忆在会话与进程重启之间持续生效。
"""

from pathlib import Path

_HEADER = "# xsh memory"
_MAX_ENTRIES = 200
_MAX_ENTRY_CHARS = 2000


def _clean(text: str) -> str:
    """规整单条记忆：去空白、去掉列表前缀、限制长度。"""
    value = " ".join(text.split())
    if value.startswith("- "):
        value = value[2:].strip()
    return value[:_MAX_ENTRY_CHARS]


class MemoryStore:
    """读写工作区级记忆文件。"""

    def __init__(self, path: Path, entries: list[str] | None = None):
        self.path = Path(path)
        self.entries: list[str] = list(entries) if entries is not None else self._load()

    def _load(self) -> list[str]:
        if not self.path.is_file():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                value = _clean(stripped)
                if value:
                    entries.append(value)
        return entries[-_MAX_ENTRIES:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.entries:
            body = _HEADER + "\n\n" + "\n".join(f"- {entry}" for entry in self.entries) + "\n"
        else:
            body = _HEADER + "\n"
        self.path.write_text(body, encoding="utf-8")

    def add(self, texts: list[str]) -> None:
        self.entries.extend(entry for entry in (_clean(text) for text in texts) if entry)
        self.entries = self.entries[-_MAX_ENTRIES:]

    def replace(self, texts: list[str]) -> None:
        self.entries = [entry for entry in (_clean(text) for text in texts) if entry][-_MAX_ENTRIES:]

    def remove(self, indices: list[int]) -> None:
        for index in sorted(set(indices), reverse=True):
            if not 1 <= index <= len(self.entries):
                raise ValueError(f"index {index} is out of range (memory has {len(self.entries)} entrie(s))")
            self.entries.pop(index - 1)

    def render(self) -> str:
        return "\n".join(f"- {entry}" for entry in self.entries)
