"""agent.py - Agent 对象，维护 Agent 的 Step 循环"""

from collections.abc import Callable
from dataclasses import dataclass

from xsh.constants import (
    AGENT_DEFAULT_MAX_STEPS,
)
from xsh.messages import Message
from xsh.model import Model
from xsh.session import Session
from xsh.tools.base import ToolRegistry


@dataclass(frozen=True)
class TurnResult:
    """单轮运行结果，储存这轮运行的所有信息"""
    status: str
    steps: int
    text: str = ""
    error: str = ""


class Agent:
    """Agent 对象，维护 Agent 的 Step 循环"""

    def __init__(
        self,
        model: Model,
        session: Session,
        tools: ToolRegistry,
        max_steps: int = AGENT_DEFAULT_MAX_STEPS,
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
            self.report("turn_start", "")
            self.session.repair_pending()  # 失败的工具调用会直接收到错误报告字符串作为结果
            self.session.append(Message(role="user", content=prompt))  # 添加用户输入到会话中
            # 每条用户消息对应一个 Turn，从会话历史计数以支持恢复后继续编号。
            turn = sum(message.role == "user" for message in self.session.messages)

            # ※ Agent Step 循环
            for step in range(1, self.max_steps + 1):
                # 准备模型请求参数，取出会话消息和工具列表
                request = self.model.build_request(self.session.messages, self.tools.schemas())
                self.session.record("request", {"step": step, "body": request})
                self.report("step", f"Turn {turn}, Step {step}")

                # 请求模型得到响应
                self.report("assistant_start", "")
                try:
                    response = self.model.complete(
                        request,
                        on_text=lambda text: self.report("assistant_delta", text),
                        on_reasoning=lambda text: self.report("assistant_reasoning_delta", text),
                    )
                finally:
                    self.report("assistant_end", "")
                self.session.record(
                    "response",
                    {
                        "step": step,
                        "finish_reason": response.finish_reason,
                        "usage": response.usage,
                    },
                )
                message = response.message

                # 检查结束原因，若异常结束则丢弃不可靠的工具调用
                if response.finish_reason not in {"stop", "tool_calls"}:
                    message = message.model_copy(update={"tool_calls": []})

                # 储存模型响应到会话中
                self.session.append(message)

                # 检查结束原因，若异常结束则该 Turn 直接结束
                if response.finish_reason not in {"stop", "tool_calls"}:
                    return self._finish(
                        TurnResult(
                            status="max_tokens" if response.finish_reason == "length" else "stopped",
                            steps=step,
                            message=message.content or "",
                            finish_reason=response.finish_reason,
                        )
                    )

                # 如果没有工具调用，则该 Turn 结束
                if not message.tool_calls:
                    return self._finish(TurnResult("completed", step, message.content or ""))

                # 如果有工具调用，则依次执行工具调用
                for call in message.tool_calls:
                    self.report("tool", call.name)  # 通知终端已收到当前工具调用
                    self.session.start_tool(call)
                    self.report("tool_start", call.name)  # 开始记录落盘后、实际执行前更新运行状态
                    result = self.tools.execute(call)
                    self.session.append(result)
                    self.report("tool_result", result.content or "")

            # 循环跑完了，说明 Step 超限，该 Turn 可能未完成，但必须结束
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
        # 无论正常结束还是中断、异常，都停止工具状态刷新，避免影响后续终端输出。
        self.report("tool_end", "")
        self.session.record(
            "turn_end",
            {
                "status": result.status,
                "steps": result.steps,
                "error": result.error,
            },
        )
        return result
