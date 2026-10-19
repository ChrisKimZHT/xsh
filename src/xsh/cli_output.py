"""Terminal presentation, kept separate from CLI orchestration and agent logic."""

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from xsh.agent import TurnResult
from xsh.messages import Message


class CliOutput:
    def __init__(self, verbose: bool = False, console: Console | None = None, error_console: Console | None = None):
        self.console = console or Console()
        self.errors = error_console or Console(stderr=True)
        self.verbose = verbose
        self._live: Live | None = None
        self._text = ""

    def report(self, kind: str, text: str) -> None:
        if kind == "assistant_start":
            self._text = ""
        elif kind == "assistant_delta":
            self._text += text
            if self.console.is_terminal:
                if self._live is None:
                    self._live = Live(console=self.console, refresh_per_second=10, transient=True)
                    self._live.start()
                self._live.update(Markdown(self._text))
            else:
                # Pipes receive unmodified Markdown incrementally, without ANSI escapes.
                self.console.file.write(text)
                self.console.file.flush()
        elif kind == "assistant_end":
            if self._live is not None:
                live, self._live = self._live, None
                live.stop()
                # Print the full answer outside Live so long responses remain in scrollback.
                self.console.print(Markdown(self._text))
            elif self._text:
                self.console.print()
            self._text = ""
        elif kind == "tool_result":
            if self.verbose:
                self.errors.print(Panel(Text(text), title="Tool result", border_style="dim"))
        elif kind == "step":
            self.errors.print(Text(f"Step {text}", style="dim"))
        elif kind == "tool":
            self.errors.print(Text(f"Tool · {text}", style="cyan"))

    def session(self, path: object) -> None:
        self.errors.print(Text(f"Session: {path}", style="dim"))

    def outcome(self, result: TurnResult) -> None:
        style = "green" if result.status == "completed" else "yellow"
        self.errors.print(Text(f"{result.status} · steps={result.steps}", style=style))
        if result.error:
            self.error(result.error)

    def error(self, text: str) -> None:
        self.errors.print(Text(text, style="red"))

    def intro(self) -> None:
        self.errors.print(Panel("Enter a task; /history shows messages, /exit quits. Ctrl+C interrupts a turn.", title="xsh", border_style="cyan"))

    def prompt(self) -> str:
        return self.console.input("\n[bold cyan]xsh> [/]").strip()

    def newline(self) -> None:
        self.console.print()

    def history(self, messages: list[Message]) -> None:
        for message in messages:
            if message.role == "system":
                continue
            self.console.rule(Text(message.role, style="cyan"))
            if message.content:
                if self.console.is_terminal and message.role == "assistant":
                    self.console.print(Markdown(message.content))
                else:
                    self.console.print(Text(message.content))
            for call in message.tool_calls:
                self.console.print(Text(f"  {call.name}({call.arguments})", style="dim"))

    def system_prompt(self, text: str) -> None:
        self.console.print(Text(text))
