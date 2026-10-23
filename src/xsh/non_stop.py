"""Non-stop task parsing and automatic Turn scheduling."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from xsh.agent import Agent, TurnResult

# 暂时性故障的重试策略：指数退避，上限固定，避免无限重试。
_INITIAL_BACKOFF_SECONDS = 15.0
_MAX_BACKOFF_SECONDS = 300.0
_MAX_TRANSIENT_RETRIES = 10


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


def run_non_stop(
    agent: Agent,
    task: NonStopTask,
    outcome: Callable[[TurnResult], None],
    *,
    resumed: bool = False,
    report: Callable[[str, str], None] | None = None,
) -> int:
    """Continue model-ended Turns until interruption or a non-retryable runtime error.

    暂时性故障（限流 429、超时、连接中断、5xx）不会结束进程，而是退避后重试，
    以保证长时间无人值守运行时进程存活；只有永久性错误或重试耗尽才退出。
    """
    notify = report or (lambda kind, text: None)
    prompt = task.next_prompt if resumed else task.prompt
    backoff = _INITIAL_BACKOFF_SECONDS
    retries = 0
    try:
        while True:
            result = agent.run(prompt)
            outcome(result)
            if result.status == "cancelled":
                return 130
            if result.status == "error" and result.retryable:
                retries += 1
                if retries > _MAX_TRANSIENT_RETRIES:
                    notify("retry", f"Transient error persisted after {_MAX_TRANSIENT_RETRIES} retries; exiting so a supervisor can restart.")
                    return 1
                kind = result.error.split(":", 1)[0] or "error"
                notify("retry", f"Transient error ({kind}); retry {retries}/{_MAX_TRANSIENT_RETRIES} in {backoff:.0f}s.")
                time.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                prompt = task.next_prompt
                continue
            if result.status not in {"completed", "max_tokens", "stopped", "step_limit"}:
                return 1
            retries = 0
            backoff = _INITIAL_BACKOFF_SECONDS
            prompt = task.next_prompt
    except KeyboardInterrupt:
        return 130
