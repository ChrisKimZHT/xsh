"""todo.py - 结构化任务清单工具。

长任务（尤其是非停机模式下的持续任务）需要一个可跨恢复续作的计划清单。
模型可以提交**完整的**清单来替换，或用 `add`/`complete`/`remove` 增量维护。
工具把清单写入会话文件，因此进程重启后仍能恢复；同时在终端渲染清单，便于用户观察进度。
"""

from collections.abc import Callable
from typing import Literal

from pydantic import Field, model_validator

from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_STATUS_MARK = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}

_TODO_GUIDANCE = (
    "Use the todo tool to plan multi-step work and keep the list current. Either submit the "
    "complete list with `todos` (it replaces the previous one), or update incrementally with "
    "`add` (append pending items), `complete` (1-based indices), and `remove` (1-based indices). "
    "Mark exactly one item in_progress while working on it, and mark items completed as soon as "
    "they are done. The list persists in the session, so it survives restarts."
)


class TodoItem(ToolArgs):
    """清单中的一项。"""

    content: str = Field(min_length=1, description="What this task item is.")
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoArgs(ToolArgs):
    """todo 工具参数：可整体替换，也可增量增删/标记。"""

    todos: list[TodoItem] | None = Field(default=None, max_length=200, description="Replacement list; submit the complete list (empty clears it).")
    add: list[str] = Field(default_factory=list, max_length=50, description="Append new pending items.")
    complete: list[int] = Field(default_factory=list, max_length=200, description="1-based indices to mark completed.")
    remove: list[int] = Field(default_factory=list, max_length=200, description="1-based indices to remove.")

    @model_validator(mode="after")
    def check_targets(self) -> "TodoArgs":
        if self.todos is None and not self.add and not self.complete and not self.remove:
            raise ValueError("Provide `todos` to replace, or `add`/`complete`/`remove`")
        return self


def format_todos(todos: list[dict]) -> str:
    """把清单渲染为多行文本。"""
    lines = []
    for item in todos:
        status = item.get("status", "pending")
        mark = _STATUS_MARK.get(status, "[?]")
        lines.append(f"{mark} {item.get('content', '')}")
    done = sum(1 for item in todos if item.get("status") == "completed")
    return "\n".join(lines) + f"\n\n({done}/{len(todos)} completed)"


class TodoTools:
    def __init__(
        self,
        record: Callable[[str, dict], None] | None = None,
        report: Callable[[str, str], None] | None = None,
        current: Callable[[], list[dict]] | None = None,
    ):
        self.record = record
        self.report = report
        self.current = current or (lambda: [])

    @staticmethod
    def _index(index: int, items: list[dict]) -> None:
        if not 1 <= index <= len(items):
            raise ValueError(f"index {index} is out of range (list has {len(items)} item(s))")

    def update(self, args: TodoArgs) -> str:
        items = [dict(item) for item in self.current()]
        if args.todos is not None:
            items = [item.model_dump() for item in args.todos]
        if args.add:
            items.extend({"content": text, "status": "pending"} for text in args.add)
        for index in args.complete:
            self._index(index, items)
            items[index - 1]["status"] = "completed"
        for index in sorted(set(args.remove), reverse=True):
            self._index(index, items)
            items.pop(index - 1)
        if self.record:
            self.record("todos", {"todos": items})
        text = format_todos(items)
        if self.report:
            self.report("todos", text)
        return "Todo list updated:\n" + text

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "todo",
                "Create or update the session's task list (replace with `todos`, or use `add`/`complete`/`remove`).",
                TodoArgs,
                self.update,
                guidance=_TODO_GUIDANCE,
                prompt_sections=(PromptSection("tool:todo", 300, _TODO_GUIDANCE),),
            ),
        ]

