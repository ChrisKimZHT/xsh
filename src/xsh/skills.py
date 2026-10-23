"""skills.py - 可按需加载的技能库（渐进式披露）。

技能是描述"如何做某类事"的 Markdown 指令包，放在 `.xsh/skills/*.md`。
系统提示词只列出技能名与首行摘要；模型在需要时用 `skill` 工具载入全文，
避免一次性把所有细节塞进上下文。
"""

from pathlib import Path

_MAX_SKILL_BYTES = 64_000


class SkillLibrary:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def reload(self) -> None:
        """技能每次调用都从磁盘读取，此处仅为与记忆/权限保持一致的接口。"""
        return None

    def _files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(path for path in self.directory.glob("*.md") if path.is_file())

    def names(self) -> list[str]:
        return [path.stem for path in self._files()]

    def describe(self) -> list[tuple[str, str]]:
        described = []
        for path in self._files():
            text = path.read_text(encoding="utf-8", errors="replace")
            first = next((line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()), "")
            described.append((path.stem, first[:120]))
        return described

    def render_index(self) -> str:
        described = self.describe()
        if not described:
            return ""
        return "\n".join(f"- {name}: {summary}" for name, summary in described)

    def read(self, name: str) -> str:
        path = (self.directory / f"{name}.md").resolve()
        if not path.is_file() or not path.is_relative_to(self.directory.resolve()):
            known = ", ".join(self.names()) or "(none)"
            raise ValueError(f"Unknown skill: {name}. Available: {known}")
        data = path.read_text(encoding="utf-8", errors="replace")
        if len(data) > _MAX_SKILL_BYTES:
            data = data[:_MAX_SKILL_BYTES] + "\n[truncated]"
        return data
