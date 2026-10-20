"""terminal.py - 负责终端的输入和输出"""

from time import perf_counter

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from xsh.agent import TurnResult
from xsh.constants import (
    TERMINAL_INTRO,
    TERMINAL_PROMPT,
    TERMINAL_REFRESH_PER_SECOND,
    TERMINAL_REQUIRED_ERROR,
)
from xsh.messages import Message


class Terminal:
    """终端输入输出对象，负责在终端中接受用户输入，并呈现 Agent 运行过程和结果，基于 rich 库实现"""

    def __init__(self, verbose: bool = False):
        self.console = Console()
        self.errors = Console(stderr=True)
        self.verbose = verbose
        self.context_window: int | None = None
        self._live: Live | None = None  # Live 对象，用于在终端中动态刷新模型输出
        self._text = ""  # 缓存拼接后的模型输出文本
        self._reasoning = False
        self._tool_live: Live | None = None  # 独立维护工具状态行，避免与模型输出的 Live 混用
        self._tool_panels: list[Panel] = []  # 同一 Step 的工具按行排列
        self._tool_results: list[Panel] = []  # 详细结果在工具组结束后打印
        self._tool_name = ""  # 当前工具名称，供后续状态更新复用
        self._tool_started_at: float | None = None
        self._turn_started_at: float | None = None
        self._turn_elapsed: float | None = None

        # 只支持终端输出；重定向或管道无法原地刷新界面，直接报错。
        if not (self.console.is_terminal and self.errors.is_terminal):
            raise OSError(TERMINAL_REQUIRED_ERROR)

    def _tool_status(self, status: str, result_chars: int | None = None) -> None:
        """原地刷新工具状态面板"""
        style = {"Pending": "yellow", "Running": "cyan", "Completed": "green", "Interrupted": "yellow"}[status]
        text = Text(f"Status: {status}", style=f"bold {style}")
        if result_chars is not None:
            text.append(f"\nLength: {result_chars} chars", style="dim")
        finished = status in {"Completed", "Interrupted"}
        if finished and self._tool_started_at is not None:
            text.append(f"\nTime: {perf_counter() - self._tool_started_at:.3f}s", style="dim")
        width = min(28, self.errors.width)
        panel = Panel(text, title=Text(f"Tool {self._tool_name}"), title_align="left", border_style=style, width=width)
        self._tool_panels[-1] = panel
        panels = Columns(self._tool_panels, width=width, equal=True, column_first=False)
        if self._tool_live is None:
            # 状态仅在事件到来时变化，无需后台定时刷新。
            self._tool_live = Live(panels, console=self.errors, auto_refresh=False)
            self._tool_live.start(refresh=True)
        else:
            self._tool_live.update(panels, refresh=True)

    def _stop_tool(self) -> None:
        """停止刷新并保留最终状态面板，重复调用也可安全退出。"""
        if self._tool_live is not None:
            self._tool_live.stop()
            self._tool_live = None
        if self._tool_results:
            self.errors.print(Group(*self._tool_results))
        self._tool_panels.clear()
        self._tool_results.clear()

    def _render_text(self):
        """将模型的 思维+输出 渲染为 灰色文本思维块 + Markdown输出块"""
        if self._reasoning:
            if not self.verbose:
                text = Text(self._text.replace("\r\n", " ").replace("\n", " ").replace("\r", " "), style="dim")
                # Panel 左右边框和默认内边距各占两个字符。
                lines = text.wrap(self.console, max(1, self.console.width - 4))
                return Panel(lines[-1] if lines else Text(""), title="Thinking", title_align="left", border_style="dim")
            return Panel(Text(self._text, style="dim"), title="Thinking", title_align="left", border_style="dim")
        return Panel(Markdown(self._text), title="Assistant", title_align="left", border_style="cyan")

    def report(self, kind: str, text: str) -> None:
        """报告事件，以打印到终端"""
        if kind == "turn_start":  # Turn 开始
            self._turn_started_at = perf_counter()
            self._turn_elapsed = None

        elif kind == "assistant_start":  # 模型开始输出
            self._text = ""
            self._reasoning = False

        elif kind in {"assistant_delta", "assistant_reasoning_delta"}:  # 模型输出增量
            reasoning = (kind == "assistant_reasoning_delta")

            if reasoning != self._reasoning:  # 思维状态发生变化，刷新终端输出
                self.report("assistant_end", "")
                self._reasoning = reasoning

            self._text += text  # 拼接模型输出文本

            if self._live is None:  # 使用 Live 动态刷新终端输出
                self._live = Live(console=self.console, refresh_per_second=TERMINAL_REFRESH_PER_SECOND, transient=True)
                self._live.start()
            self._live.update(self._render_text())

        elif kind == "assistant_end":  # 模型输出结束
            if self._live is not None:
                self._live.stop()
                self._live = None
                # Live 设置了 transient=True，停止后会清空终端输出，所以这里需要重新打印模型的完整输出
                # 简洁模式的思维仅供实时预览，结束时会消失，不会再打印一次
                if not self._reasoning or self.verbose:
                    self.console.print(self._render_text())
            self._text = ""

        elif kind == "tool_result":  # 工具调用结果
            # 保留完成面板，后续工具继续加入同一 Step 的横向布局。
            self._tool_status("Completed", result_chars=len(text))
            self._tool_started_at = None
            if self.verbose:
                self._tool_results.append(Panel(Text(text), title=f"Tool result: {self._tool_name}", title_align="left", border_style="dim"))

        elif kind == "step":  # 模型 Step 进度
            self._stop_tool()
            # Turn 起始使用粗分隔线，后续 Step 使用细分隔线，便于滚动查找。
            first_step = text.endswith(", Step 1")
            self.errors.print()
            self.errors.rule(
                Text(text, style="bold cyan" if first_step else "bold blue"),
                characters="━" if first_step else "─",
                style="cyan" if first_step else "blue",
                align="left",
            )

        elif kind == "tool":  # 模型调用工具
            # 将工具名称中的连续空白（包括换行）压缩为单个空格。
            self._tool_name = " ".join(text.split())
            self._tool_started_at = None
            self._tool_panels.append(Panel(""))
            self._tool_status("Pending")

        elif kind == "tool_start":  # 工具即将执行，原地更新为运行状态
            self._tool_started_at = perf_counter()
            self._tool_status("Running")

        elif kind == "tool_end":  # Turn 结束时兜底清理，包括工具执行中断或异常的情况
            if self._turn_started_at is not None:
                self._turn_elapsed = perf_counter() - self._turn_started_at
                self._turn_started_at = None
            if self._tool_started_at is not None:
                self._tool_status("Interrupted")
            self._stop_tool()
            self._tool_started_at = None

    def session(self, path: object) -> None:
        """打印会话路径"""
        self.errors.print(Text(f"Session: {path}", style="dim"))

    def outcome(self, result: TurnResult) -> None:
        """打印 Turn 结果"""
        style = {"completed": "green", "error": "red"}.get(result.status, "yellow")
        status = result.status.replace("_", " ").capitalize()
        summary = Text(f"Status: {status}", style=f"bold {style}")
        summary.append(f"\nSteps: {result.steps}", style="dim")
        if self._turn_elapsed is not None:
            summary.append(f"\nTime: {self._turn_elapsed:.3f}s", style="dim")
            self._turn_elapsed = None
        if result.usage:
            values = ", ".join(
                f"{label} {result.usage[key]}" if key in result.usage else f"{label} unavailable"
                for label, key in (("in", "prompt_tokens"), ("out", "completion_tokens"), ("sum", "total_tokens"))
            )
            summary.append(f"\nUsage: {values}" + (" (partial)" if result.usage_partial else ""), style="dim")
        else:
            summary.append("\nUsage: unavailable", style="dim")
        if result.context_tokens is None:
            summary.append("\nContext: unavailable", style="dim")
        elif self.context_window is None:
            summary.append(f"\nContext: {result.context_tokens} tokens", style="dim")
        else:
            summary.append(
                f"\nContext: {result.context_tokens} / {self.context_window} tokens ({result.context_tokens / self.context_window:.1%})",
                style="dim",
            )
        if result.error:
            summary.append("\n\n")
            summary.append(result.error, style="red")
        self.errors.print()
        self.errors.print(Panel(summary, title="Turn result", title_align="left", border_style=style, expand=False))

    def error(self, text: str) -> None:
        """打印真正的错误信息"""
        self.errors.print(Text(text, style="red"))

    def intro(self) -> None:
        """打印终端介绍信息"""
        self.errors.print(Panel(TERMINAL_INTRO, title="xsh", title_align="left", border_style="cyan"))

    def prompt(self) -> str:
        """打印终端提示符，并**接受**用户输入"""
        return self.console.input(TERMINAL_PROMPT).strip()

    def newline(self) -> None:
        """打印一个空行"""
        self.console.print()

    def history(self, messages: list[Message]) -> None:
        """打印会话历史"""
        for message in messages:
            if message.role == "system":
                continue
            self.console.rule(Text(message.role, style="cyan"))
            if message.reasoning_content:
                self.console.print(Panel(Text(message.reasoning_content, style="dim"), title="Thinking", title_align="left", border_style="dim"))
            if message.content:
                if message.role == "assistant":
                    self.console.print(Panel(Markdown(message.content), title="Assistant", title_align="left", border_style="cyan"))
                else:
                    self.console.print(Text(message.content))
            for call in message.tool_calls:
                self.console.print(Text(f"  {call.name}({call.arguments})", style="dim"))

