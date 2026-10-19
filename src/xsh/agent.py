"""The whole agent loop: request, observe, act, repeat."""

from collections.abc import Callable
from dataclasses import dataclass

from xsh.messages import Message
from xsh.model import Model
from xsh.session import Session
from xsh.tools.base import ToolRegistry


@dataclass(frozen=True)
class TurnResult:
    status: str
    steps: int
    text: str = ""
    error: str = ""


class Agent:
    def __init__(
        self,
        model: Model,
        session: Session,
        tools: ToolRegistry,
        max_steps: int = 100,
        report: Callable[[str, str], None] | None = None,
    ):
        if max_steps < 1:
            raise ValueError("Agent limits must be positive")
        self.model = model
        self.session = session
        self.tools = tools
        self.max_steps = max_steps
        self.report = report or (lambda kind, text: None)

    def run(self, prompt: str) -> TurnResult:
        if not prompt.strip():
            raise ValueError("Prompt must not be empty")

        step = 0
        try:
            self.session.repair_pending()  # failed tool calls will receive an error message result
            self.session.append(Message(role="user", content=prompt))

            # agent step loop
            for step in range(1, self.max_steps + 1):
                # prepare model request
                request = self.model.build_request(self.session.messages, self.tools.schemas())
                self.session.record("request", {"step": step, "body": request})
                self.report("step", str(step))

                # request model completion
                response = self.model.complete(request)
                self.session.record(
                    "response",
                    {
                        "step": step,
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                    },
                )
                message = response.message

                # only a complete response may authorize tool execution.
                if response.finish_reason not in {"stop", "tool_calls"}:
                    message = message.model_copy(update={"tool_calls": []})

                self.session.append(message)

                # report assistant and tool results to the user
                if message.content:
                    self.report("assistant", message.content)

                # if the model did not stop or request tool calls, the turn is complete.
                if response.finish_reason not in {"stop", "tool_calls"}:
                    return self._finish(
                        TurnResult(
                            "max_tokens" if response.finish_reason == "length" else "stopped",
                            step,
                            message.content or "",
                            response.finish_reason,
                        )
                    )

                # model requested tool calls but did not provide any; the turn is complete.
                if not message.tool_calls:
                    return self._finish(TurnResult("completed", step, message.content or ""))

                # execute tool calls and record results
                for call in message.tool_calls:
                    self.report("tool", call.name)
                    self.session.start_tool(call)
                    result = self.tools.execute(call)
                    self.session.append(result)
                    self.report("tool_result", result.content or "")

            # step limit exceeded; the turn is complete but the model may not have finished.
            return self._finish(
                TurnResult(
                    "step_limit",
                    step,
                    error="Maximum model steps reached; completed tool results are saved.",
                )
            )

        except KeyboardInterrupt:
            self.session.repair_pending()
            return self._finish(TurnResult("cancelled", step, error="Interrupted by user."))

        except Exception as error:
            self.session.repair_pending()
            return self._finish(TurnResult("error", step, error=f"{type(error).__name__}: {error}"))

    def _finish(self, result: TurnResult) -> TurnResult:
        self.session.record(
            "turn_end",
            {
                "status": result.status,
                "steps": result.steps,
                "error": result.error,
            },
        )
        return result
