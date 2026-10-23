"""memory.py - 长期记忆工具：维护工作区级持久笔记。"""

from collections.abc import Callable

from pydantic import Field, model_validator

from xsh.memory import MemoryStore
from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_MEMORY_GUIDANCE = (
    "Use the memory tool to persist durable facts that should survive across sessions and "
    "restarts: user preferences, project conventions, important decisions, and recurring "
    "context. Keep entries short and factual; never store secrets or credentials. Add new "
    "notes with `add`, replace the whole set with `replace`, or delete entries by 1-based "
    "index with `remove`. The workspace memory file is injected into the system prompt."
)


class MemoryArgs(ToolArgs):
    add: list[str] = Field(default_factory=list, max_length=50, description="New notes to append.")
    replace: list[str] | None = Field(default=None, max_length=200, description="Replacement set of notes (empty clears).")
    remove: list[int] = Field(default_factory=list, max_length=200, description="1-based indices to delete.")

    @model_validator(mode="after")
    def check_targets(self) -> "MemoryArgs":
        if self.replace is None and not self.add and not self.remove:
            raise ValueError("Provide `add`, `replace`, or `remove`")
        return self


class MemoryTools:
    def __init__(self, store: MemoryStore, report: Callable[[str, str], None] | None = None):
        self.store = store
        self.report = report

    def update(self, args: MemoryArgs) -> str:
        if args.replace is not None:
            self.store.replace(args.replace)
        if args.add:
            self.store.add(args.add)
        if args.remove:
            self.store.remove(args.remove)
        self.store.save()
        text = self.store.render() or "(no memory entries)"
        if self.report:
            self.report("memory", text)
        return "Memory updated:\n" + text

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "memory",
                "Persist durable notes for this workspace across sessions (add/replace/remove).",
                MemoryArgs,
                self.update,
                guidance=_MEMORY_GUIDANCE,
                prompt_sections=(PromptSection("tool:memory", 300, _MEMORY_GUIDANCE),),
            ),
        ]
