"""prompt.py - 提示词构建逻辑"""

from importlib.resources import files
from pathlib import Path

_MAX_INSTRUCTIONS_BYTES = 128_000
_SHELL_INSTRUCTIONS = (
    "\nYour shell tool runs foreground commands with the workspace as its working directory. "
    "It is not sandboxed and has no persistent terminal or background job support. "
    "Use the shell dialect advertised in its tool description. Use it for tests and build commands.\n\n"
    "Check the [exit code: N] marker on every shell result; investigate failures and "
    "timeouts before moving on. After a timeout, inspect state before retrying commands "
    "with side effects.\n"
)


def build_prompt(workspace: Path, *, model: str, allow_shell: bool = False) -> str:
    # 内置系统提示词
    prompt = files("xsh").joinpath("prompts/system.md").read_text(encoding="utf-8")
    prompt = prompt.replace("{{model}}", model)  # 渲染系统提示词的模型名称
    # 指定工作目录
    prompt += f"\n\nWorkspace: {workspace.resolve()}\n"
    if allow_shell:
        # Shell 工具相关提示词
        prompt += _SHELL_INSTRUCTIONS
    # 加载工作目录的 AGENTS.md
    instructions = workspace / "AGENTS.md"
    if instructions.is_file():
        if not instructions.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Root AGENTS.md resolves outside the workspace")
        with instructions.open("rb") as file:
            data = file.read(_MAX_INSTRUCTIONS_BYTES + 1)
        if len(data) > _MAX_INSTRUCTIONS_BYTES:
            raise ValueError(f"Root AGENTS.md exceeds {_MAX_INSTRUCTIONS_BYTES} bytes; shorten it before starting")
        prompt += "\nProject instructions (AGENTS.md):\n\n" + data.decode("utf-8")
    return prompt
