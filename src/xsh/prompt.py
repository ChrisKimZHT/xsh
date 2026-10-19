"""A fixed prompt plus the workspace's root AGENTS.md, captured once per session."""

from importlib.resources import files
from pathlib import Path


def build_prompt(workspace: Path, *, allow_shell: bool = False) -> str:
    prompt = files("xsh").joinpath("prompts/system.md").read_text(encoding="utf-8")
    prompt += f"\n\nWorkspace: {workspace.resolve()}\n"
    if allow_shell:
        prompt += (
            "\nThe shell tool runs foreground commands in the workspace. It has no persistent "
            "terminal or background job support. Use it for tests and build commands. "
            "Inspect non-zero exit codes and timeouts before moving on.\n"
        )
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
