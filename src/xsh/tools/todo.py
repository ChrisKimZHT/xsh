"""todo.py - 结构化任务清单工具。

长任务（尤其是非停机模式下的持续任务）需要一个可跨恢复续作的计划清单。
模型每次调用该工具提交**完整的**清单，工具把清单写入会话文件，因此进程重启后
仍能恢复；同时在终端渲染清单，便于用户观察进度。
"""

from collections.abc import Callable
from typing import Literal

from pydantic import Field

from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_STATUS_MARK = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}

_TODO_GUIDANCE = (
    "Use the todo tool to plan multi-step work and keep the list current: submit the "
    "complete list each time (it replaces the previous one), mark exactly one item "
    "in_progress while working on it, and mark items completed as soon as they are done. "
    "The list persists in the session, so it survives restarts."
)


class TodoItem(ToolArgs):
    """清单中的一项。"""

    content: str = Field(min_length=1, description="What this task item is.")
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoArgs(ToolArgs):
    """todo 工具参数：完整替换当前清单。"""

    todos: list[TodoItem] = Field(min_length=1, max_length=200, description="The complete, updated todo list.")


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
    ):
        self.record = record
        self.report = report

    def update(self, args: TodoArgs) -> str:
        todos = [item.model_dump() for item in args.todos]
        if self.record:
            self.record("todos", {"todos": todos})
        text = format_todos(todos)
        if self.report:
            self.report("todos", text)
        return "Todo list updated:\n" + text

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "todo",
                "Create or update the session's task list (submit the complete list; it replaces the previous one).",
                TodoArgs,
                self.update,
                guidance=_TODO_GUIDANCE,
                prompt_sections=(PromptSection("tool:todo", 300, _TODO_GUIDANCE),),
            ),
        ]
