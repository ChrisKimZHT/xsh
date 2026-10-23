"""Optional foreground shell. This is process execution, not an OS sandbox."""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from pydantic import Field

from xsh.tools.base import Tool, ToolArgs, bounded

_MAX_TIMEOUT_SECONDS = 600
_MAX_OUTPUT_BYTES = 256_000


class ShellArgs(ToolArgs):
    command: str = Field(
        min_length=1, description="A foreground command in the advertised dialect."
    )
    timeout_seconds: int = Field(default=120, ge=1, le=_MAX_TIMEOUT_SECONDS)


def _stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


class ShellTools:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.windows = os.name == "nt"
        self.executable = (
            (shutil.which("pwsh") or shutil.which("powershell"))
            if self.windows else shutil.which("bash")
        )
        if self.executable is None:
            raise ValueError("PowerShell (Windows) or bash (Unix) is required for --allow-shell")
        self.dialect = "PowerShell" if self.windows else "bash"

    def execute(self, args: ShellArgs) -> str:
        command = args.command
        if self.windows:
            command = (
                "$ErrorActionPreference = 'Stop'; "
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
                "$OutputEncoding = [Console]::OutputEncoding; " + command
            )
            argv = [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            argv = [self.executable, "-c", command]
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            if self.windows
            else {"start_new_session": True}
        )
        # File-backed output avoids unbounded Python memory for noisy commands.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                argv,
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                **options,
            )
            timed_out = False
            try:
                process.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop(process)
            except BaseException:
                _stop(process)
                raise
            output.seek(0)
            raw = output.read(_MAX_OUTPUT_BYTES + 1)
        text = raw[: _MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(raw) > _MAX_OUTPUT_BYTES:
            text += "\n[Output truncated; rerun with a narrower command or redirect to a file.]"
        status = f"[exit code: {process.returncode}]"
        if timed_out:
            status += " [timed out; inspect state before retrying commands with side effects]"
        return status + "\n" + bounded(text)

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "shell",
                f"Run a foreground {self.dialect} command in the workspace with a timeout. "
                "No persistent shell or background jobs. This tool is not sandboxed.",
                ShellArgs,
                self.execute,
                guidance=(
                    "Your shell tool runs foreground commands with the workspace as its working directory. "
                    "It is not sandboxed and has no persistent terminal or background job support. "
                    "Use the shell dialect advertised in its tool description. Use it for tests and build commands.\n\n"
                    "Check the [exit code: N] marker on every shell result; investigate failures and "
                    "timeouts before moving on. After a timeout, inspect state before retrying commands "
                    "with side effects."
                ),
            ),
        ]
