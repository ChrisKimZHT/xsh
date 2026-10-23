"""task.py - 委派工具：把自包含的子任务交给拥有独立上下文的子代理执行。

子代理使用全新的会话与（不含 task 的）工具集，因此不会递归委派，也不会污染
主会话的上下文；完成后把最终报告作为工具结果返回给主代理。
"""

from collections.abc import Callable

from pydantic import Field

from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_TASK_GUIDANCE = (
    "Use the task tool to delegate a self-contained subtask to a subagent that works in its own "
    "fresh context and returns a final report. Write a complete, self-contained prompt: the "
    "subagent cannot see this conversation. Use it for exploratory or parallelizable work when "
    "the intermediate steps are not needed in this context."
)


class TaskArgs(ToolArgs):
    prompt: str = Field(min_length=1, description="A complete, self-contained prompt for the subagent.")
    label: str = Field(default="", max_length=80, description="Short label for logs (optional).")


class TaskTools:
    def __init__(self, run: Callable[[str], str]):
        self.run = run

    def delegate(self, args: TaskArgs) -> str:
        return self.run(args.prompt)

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "task",
                "Delegate a self-contained subtask to a subagent with its own fresh context; returns its report.",
                TaskArgs,
                self.delegate,
                guidance=_TASK_GUIDANCE,
                prompt_sections=(PromptSection("tool:task", 300, _TASK_GUIDANCE),),
            ),
        ]
