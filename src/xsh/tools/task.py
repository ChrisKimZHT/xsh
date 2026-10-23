"""task.py - 委派工具：把自包含的子任务交给拥有独立上下文的子代理执行。

支持一次提交多个**相互独立**的子任务并发执行，也支持 `background` 后台执行并返回
句柄（用 `task_status` 轮询）。子代理使用全新的会话与（不含 task 的）工具集，
因此不会递归委派，也不会污染主会话的上下文。
"""

from collections.abc import Callable, Sequence

from pydantic import Field, model_validator

from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs

_TASK_GUIDANCE = (
    "Use the task tool to delegate self-contained subtasks to subagents that work in their own "
    "fresh context and return final reports. Write complete, self-contained prompts: the "
    "subagents cannot see this conversation. Pass several independent subtasks via `prompts` "
    "(up to 4) to run them concurrently. Set `background=true` to start a long subtask without "
    "blocking, then poll it with the task_status tool."
)

_STATUS_GUIDANCE = (
    "Use the task_status tool to check background subtasks started with task(background=true). "
    "Omit `id` to list all background tasks."
)


class TaskArgs(ToolArgs):
    prompt: str = Field(default="", description="A single subtask prompt (or use `prompts` for several).")
    prompts: list[str] = Field(default_factory=list, max_length=4, description="Several independent subtasks to run concurrently.")
    label: str = Field(default="", max_length=80, description="Short label for logs (optional).")
    background: bool = Field(default=False, description="Run in the background and return a handle instead of waiting.")

    @model_validator(mode="after")
    def check_targets(self) -> "TaskArgs":
        if not self.prompt.strip() and not [p for p in self.prompts if p.strip()]:
            raise ValueError("Provide a non-empty `prompt` or at least one entry in `prompts`")
        return self

    def targets(self) -> list[str]:
        return [p for p in self.prompts if p.strip()] or [self.prompt.strip()]


class TaskStatusArgs(ToolArgs):
    id: str = Field(default="", description="Background task id; omit to list all tasks.")


class TaskTools:
    def __init__(
        self,
        run: Callable[[Sequence[str]], str],
        start: Callable[[Sequence[str]], str] | None = None,
        status: Callable[[str], str] | None = None,
    ):
        self.run = run
        self.start = start
        self.status = status

    def delegate(self, args: TaskArgs) -> str:
        targets = args.targets()
        if args.background:
            if self.start is None:
                raise ValueError("Background delegation is not available here")
            return self.start(targets)
        return self.run(targets)

    def poll(self, args: TaskStatusArgs) -> str:
        if self.status is None:
            return "Background tasks are not available here."
        return self.status(args.id.strip())

    def definitions(self) -> list[Tool]:
        tools = [
            Tool(
                "task",
                "Delegate self-contained subtasks to subagents with fresh context; returns their reports.",
                TaskArgs,
                self.delegate,
                guidance=_TASK_GUIDANCE,
                prompt_sections=(PromptSection("tool:task", 300, _TASK_GUIDANCE),),
            ),
        ]
        if self.status is not None:
            tools.append(
                Tool(
                    "task_status",
                    "Check or list background subtasks started with task(background=true).",
                    TaskStatusArgs,
                    self.poll,
                    guidance=_STATUS_GUIDANCE,
                    prompt_sections=(PromptSection("tool:task_status", 300, _STATUS_GUIDANCE),),
                )
            )
        return tools
