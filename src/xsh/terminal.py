"""terminal.py - 负责终端的输入和输出"""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from xsh.agent import TurnResult
from xsh.constants import (
    TERMINAL_INTRO,
    TERMINAL_PROMPT,
    TERMINAL_REFRESH_PER_SECOND,
)
from xsh.messages import Message


class Terminal:
    """终端输入输出对象，负责在终端中接受用户输入，并呈现 Agent 运行过程和结果，基于 rich 库实现"""

    def __init__(self, verbose: bool = False, console: Console | None = None, error_console: Console | None = None):
        self.console = console or Console()
        self.errors = error_console or Console(stderr=True)
        self.verbose = verbose
        self._live: Live | None = None  # Live 对象，用于在终端中动态刷新模型输出
        self._text = ""  # 缓存拼接后的模型输出文本
        self._reasoning = False

    def _render_text(self):
        """将模型的 思维+输出 渲染为 灰色文本思维块 + Markdown输出块"""
        if self._reasoning:
            if not self.verbose:
                text = Text(self._text.replace("\r\n", " ").replace("\n", " ").replace("\r", " "), style="dim")
                # Panel 左右边框和默认内边距各占两个字符。
                lines = text.wrap(self.console, max(1, self.console.width - 4))
                return Panel(lines[-1] if lines else Text(""), title="Thinking", border_style="dim")
            return Panel(Text(self._text, style="dim"), title="Thinking", border_style="dim")
        return Markdown(self._text)

    def report(self, kind: str, text: str) -> None:
        """报告事件，以打印到终端"""
        if kind == "assistant_start":  # 模型开始输出
            self._text = ""
            self._reasoning = False

        elif kind in {"assistant_delta", "assistant_reasoning_delta"}:  # 模型输出增量
            reasoning = (kind == "assistant_reasoning_delta")

            if reasoning != self._reasoning:  # 思维状态发生变化，刷新终端输出
                self.report("assistant_end", "")
                self._reasoning = reasoning
                if reasoning and not self.console.is_terminal:  # 如果是管道输出，则在思维开始时打印提示，防止混到一起
                    self.console.file.write("Thinking:\n")

            self._text += text  # 拼接模型输出文本

            if self.console.is_terminal:
                # 如果是终端输出，则使用 Live 动态刷新终端输出
                if self._live is None:
                    self._live = Live(console=self.console, refresh_per_second=TERMINAL_REFRESH_PER_SECOND, transient=True)
                    self._live.start()
                self._live.update(self._render_text())
            else:
                # 如果是管道输出，则直接打印模型当前的文本块
                self.console.file.write(text)
                self.console.file.flush()

        elif kind == "assistant_end":  # 模型输出结束
            if self._live is not None:
                self._live.stop()
                self._live = None
                # Live 设置了 transient=True，停止后会清空终端输出，所以这里需要重新打印模型的完整输出
                # 简洁模式的思维仅供实时预览，结束时会消失，不会再打印一次
                if not self._reasoning or self.verbose:
                    self.console.print(self._render_text())
            elif self._text:
                self.console.print()
            self._text = ""

        elif kind == "tool_result":  # 工具调用结果
            if self.verbose:
                self.errors.print(Panel(Text(text), title="Tool result", border_style="dim"))

        elif kind == "step":  # 模型 Step 进度
            self.errors.print(Text(text, style="dim"))

        elif kind == "tool":  # 模型调用工具
            self.errors.print(Text(f"Tool · {text}", style="cyan"))

    def session(self, path: object) -> None:
        """打印会话路径"""
        self.errors.print(Text(f"Session: {path}", style="dim"))

    def outcome(self, result: TurnResult) -> None:
        """打印 Turn 结果"""
        style = "green" if result.status == "completed" else "yellow"
        self.errors.print(Text(f"{result.status} · steps={result.steps}", style=style))
        if result.error:
            self.error(result.error)

    def error(self, text: str) -> None:
        """打印真正的错误信息"""
        self.errors.print(Text(text, style="red"))

    def intro(self) -> None:
        """打印终端介绍信息"""
        self.errors.print(Panel(TERMINAL_INTRO, title="xsh", border_style="cyan"))

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
                self.console.print(Panel(Text(message.reasoning_content, style="dim"), title="Thinking", border_style="dim"))
            if message.content:
                if self.console.is_terminal and message.role == "assistant":
                    self.console.print(Markdown(message.content))
                else:
                    self.console.print(Text(message.content))
            for call in message.tool_calls:
                self.console.print(Text(f"  {call.name}({call.arguments})", style="dim"))

    def system_prompt(self, text: str) -> None:
        """打印系统提示"""
        self.console.print(Text(text))
