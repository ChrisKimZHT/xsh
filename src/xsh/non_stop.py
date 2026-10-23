"""Non-stop task parsing and automatic Turn scheduling."""

from collections.abc import Callable
from dataclasses import dataclass

from xsh.agent import Agent, TurnResult


@dataclass(frozen=True)
class NonStopTask:
    prompt: str
    continuation: str = ""

    # 正确拼写为 continue-prompt；同时兼容早期版本使用的 continue-promot。
    _TAG_NAMES = ("continue-prompt", "continue-promot")

    @classmethod
    def parse(cls, text: str) -> "NonStopTask":
        task = None
        for name in cls._TAG_NAMES:
            opening, closing = f"<{name}>", f"</{name}>"
            if opening not in text and closing not in text:
                continue
            if text.count(opening) != 1 or text.count(closing) != 1:
                raise ValueError(f"Expected one matching {opening}...{closing} block")
            prompt, _, rest = text.partition(opening)
            continuation, separator, trailing = rest.partition(closing)
            if not separator or trailing.strip():
                raise ValueError(f"The {opening} block must follow the task and end the prompt")
            task = cls(prompt.strip(), continuation.strip())
            break
        if task is None:
            task = cls(text.strip())
        if not task.prompt:
            raise ValueError("Non-stop mode requires a non-empty task")
        return task

    @classmethod
    def from_stored(cls, prompt: str, continuation: str) -> "NonStopTask":
        """从会话记录恢复任务；旧的记录可能把续跑块留在 prompt 中，这里重新拆分。"""
        if continuation or not any(f"<{name}>" in prompt for name in cls._TAG_NAMES):
            return cls(prompt, continuation)
        return cls.parse(prompt)

    @property
    def next_prompt(self) -> str:
        return "\n\n".join(part for part in (self.prompt, self.continuation) if part)


def run_non_stop(agent: Agent, task: NonStopTask, outcome: Callable[[TurnResult], None], *, resumed: bool = False) -> int:
    """Continue model-ended Turns until interruption or a runtime error."""
    prompt = task.next_prompt if resumed else task.prompt
    try:
        while True:
            result = agent.run(prompt)
            outcome(result)
            if result.status == "cancelled":
                return 130
            if result.status not in {"completed", "max_tokens", "stopped", "step_limit"}:
                return 1
            prompt = task.next_prompt
    except KeyboardInterrupt:
        return 130
