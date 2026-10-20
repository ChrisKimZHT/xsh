"""prompt.py - 提示词构建逻辑"""

from importlib.resources import files
from pathlib import Path

from xsh.constants import (
    PROMPT_INSTRUCTIONS_FILE,
    PROMPT_MAX_INSTRUCTIONS_BYTES,
    PROMPT_RESOURCE_PATH,
    PROMPT_SHELL_INSTRUCTIONS,
)


def build_prompt(workspace: Path, *, model: str, allow_shell: bool = False) -> str:
    # 内置系统提示词
    prompt = files("xsh").joinpath(PROMPT_RESOURCE_PATH).read_text(encoding="utf-8")
    prompt = prompt.replace("{{model}}", model)  # 渲染系统提示词的模型名称
    # 指定工作目录
    prompt += f"\n\nWorkspace: {workspace.resolve()}\n"
    if allow_shell:
        # Shell 工具相关提示词
        prompt += PROMPT_SHELL_INSTRUCTIONS
    # 加载工作目录的 AGENTS.md
    instructions = workspace / PROMPT_INSTRUCTIONS_FILE
    if instructions.is_file():
        if not instructions.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Root AGENTS.md resolves outside the workspace")
        with instructions.open("rb") as file:
            data = file.read(PROMPT_MAX_INSTRUCTIONS_BYTES + 1)
        if len(data) > PROMPT_MAX_INSTRUCTIONS_BYTES:
            raise ValueError(f"Root AGENTS.md exceeds {PROMPT_MAX_INSTRUCTIONS_BYTES} bytes; shorten it before starting")
        prompt += "\nProject instructions (AGENTS.md):\n\n" + data.decode("utf-8")
    return prompt
