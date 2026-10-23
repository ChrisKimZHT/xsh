"""Non-stop task parsing and automatic Turn scheduling."""

from collections.abc import Callable
from dataclasses import dataclass

from xsh.agent import Agent, TurnResult


@dataclass(frozen=True)
class NonStopTask:
    prompt: str
    continuation: str = ""

    @classmethod
    def parse(cls, text: str) -> "NonStopTask":
        opening, closing = "<continue-promot>", "</continue-promot>"
        if opening not in text and closing not in text:
            task = cls(text.strip())
        else:
            if text.count(opening) != 1 or text.count(closing) != 1:
                raise ValueError("Expected one matching <continue-promot>...</continue-promot> block")
            prompt, _, rest = text.partition(opening)
            continuation, separator, trailing = rest.partition(closing)
            if not separator or trailing.strip():
                raise ValueError("The <continue-promot> block must follow the task and end the prompt")
            task = cls(prompt.strip(), continuation.strip())
        if not task.prompt:
            raise ValueError("Non-stop mode requires a non-empty task")
        return task

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
