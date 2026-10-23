"""task.py - 委派工具：把自包含的子任务交给拥有独立上下文的子代理执行。

支持一次提交多个**相互独立**的子任务并发执行，子代理使用全新的会话与
（不含 task 的）工具集，因此不会递归委派，也不会污染主会话的上下文。
"""

from collections.abc import Callable, Sequence

from pydantic import Field, model_validator

from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_TASK_GUIDANCE = (
    "Use the task tool to delegate self-contained subtasks to subagents that work in their own "
    "fresh context and return final reports. Write complete, self-contained prompts: the "
    "subagents cannot see this conversation. Pass several independent subtasks via `prompts` "
    "(up to 4) to run them concurrently; continue useful work while they run."
)


class TaskArgs(ToolArgs):
    prompt: str = Field(default="", description="A single subtask prompt (or use `prompts` for several).")
    prompts: list[str] = Field(default_factory=list, max_length=4, description="Several independent subtasks to run concurrently.")
    label: str = Field(default="", max_length=80, description="Short label for logs (optional).")

    @model_validator(mode="after")
    def check_targets(self) -> "TaskArgs":
        if not self.prompt.strip() and not [p for p in self.prompts if p.strip()]:
            raise ValueError("Provide a non-empty `prompt` or at least one entry in `prompts`")
        return self

    def targets(self) -> list[str]:
        return [p for p in self.prompts if p.strip()] or [self.prompt.strip()]


class TaskTools:
    def __init__(self, run: Callable[[Sequence[str]], str]):
        self.run = run

    def delegate(self, args: TaskArgs) -> str:
        return self.run(args.targets())

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "task",
                "Delegate self-contained subtasks to subagents with fresh context; returns their reports.",
                TaskArgs,
                self.delegate,
                guidance=_TASK_GUIDANCE,
                prompt_sections=(PromptSection("tool:task", 300, _TASK_GUIDANCE),),
            ),
        ]
