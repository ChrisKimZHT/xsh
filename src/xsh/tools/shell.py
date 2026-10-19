"""Optional foreground shell. This is process execution, not an OS sandbox."""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from pydantic import Field

from xsh.constants import (
    SHELL_DEFAULT_TIMEOUT_SECONDS,
    SHELL_MAX_OUTPUT_BYTES,
    SHELL_MAX_TIMEOUT_SECONDS,
    SHELL_TIMEOUT_MARKER,
    SHELL_TRUNCATION_MARKER,
)
from xsh.tools.base import Tool, ToolArgs, bounded


class ShellArgs(ToolArgs):
    command: str = Field(
        min_length=1, description="A foreground command in the advertised dialect."
    )
    timeout_seconds: int = Field(default=SHELL_DEFAULT_TIMEOUT_SECONDS, ge=1, le=SHELL_MAX_TIMEOUT_SECONDS)


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


def shell_tool(workspace: Path) -> Tool:
    windows = os.name == "nt"
    executable = (
        (shutil.which("pwsh") or shutil.which("powershell")) if windows else shutil.which("bash")
    )
    if executable is None:
        raise ValueError("PowerShell (Windows) or bash (Unix) is required for --allow-shell")
    dialect = "PowerShell" if windows else "bash"

    def execute(args: ShellArgs) -> str:
        command = args.command
        if windows:
            command = (
                "$ErrorActionPreference = 'Stop'; "
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
                "$OutputEncoding = [Console]::OutputEncoding; " + command
            )
            argv = [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            argv = [executable, "-c", command]
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            if windows
            else {"start_new_session": True}
        )
        # File-backed output avoids unbounded Python memory for noisy commands.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
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
            raw = output.read(SHELL_MAX_OUTPUT_BYTES + 1)
        text = raw[: SHELL_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(raw) > SHELL_MAX_OUTPUT_BYTES:
            text += SHELL_TRUNCATION_MARKER
        status = f"[exit code: {process.returncode}]"
        if timed_out:
            status += SHELL_TIMEOUT_MARKER
        return status + "\n" + bounded(text)

    return Tool(
        "shell",
        f"Run a foreground {dialect} command in the workspace with a timeout. "
        "No persistent shell or background jobs. This tool is not sandboxed.",
        ShellArgs,
        execute,
    )
