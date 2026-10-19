"""prompt.py - 提示词构建逻辑"""

from importlib.resources import files
from pathlib import Path


def build_prompt(workspace: Path, *, allow_shell: bool = False) -> str:
    # 内置系统提示词
    prompt = files("xsh").joinpath("prompts/system.md").read_text(encoding="utf-8")
    # 指定工作目录
    prompt += f"\n\nWorkspace: {workspace.resolve()}\n"
    if allow_shell:
        # Shell 工具相关提示词
        prompt += (
            "\nThe shell tool runs foreground commands in the workspace. It has no persistent "
            "terminal or background job support. Use it for tests and build commands. "
            "Inspect non-zero exit codes and timeouts before moving on.\n"
        )
    # 加载工作目录的 AGENTS.md
    instructions = workspace / "AGENTS.md"
    if instructions.is_file():
        if not instructions.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Root AGENTS.md resolves outside the workspace")
        with instructions.open("rb") as file:
            data = file.read(128001)
        if len(data) > 128000:
            raise ValueError("Root AGENTS.md exceeds 128000 bytes; shorten it before starting")
        prompt += "\nProject instructions (AGENTS.md):\n\n" + data.decode("utf-8")
    return prompt
