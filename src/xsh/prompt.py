"""Ordered prompt contributions, assembled from the active tool registry."""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from xsh.config import STATE_DIRECTORY

if TYPE_CHECKING:
    from xsh.tools.base import ToolRegistry

_MAX_INSTRUCTIONS_BYTES = 128_000
_MAX_NESTED_INSTRUCTIONS = 20
_SKIP_DIRECTORIES = frozenset({".git", STATE_DIRECTORY, ".supervisor", ".venv", ".conda", "node_modules", "__pycache__"})


@dataclass(frozen=True)
class PromptSection:
    """One resolved contribution; names are unique and order controls placement."""

    name: str
    order: int
    text: str


def render_prompt(sections: Iterable[PromptSection]) -> str:
    """Deduplicate shared contributions and join sections in deterministic order.

    Identical shared sections may come from multiple tools. Conflicting definitions
    fail rather than silently choosing one based on tool registration order.
    Text is literal: project instructions and paths are never template-expanded.
    """
    registered: dict[str, PromptSection] = {}
    for section in sections:
        if section.name in registered and registered[section.name] != section:
            raise ValueError(f"Conflicting prompt section: {section.name}")
        registered[section.name] = section
    return "\n\n".join(
        section.text.strip()
        for section in sorted(registered.values(), key=lambda section: (section.order, section.name))
        if section.text.strip()
    )


def build_prompt(workspace: Path, *, model: str, tools: "ToolRegistry", non_stop_mode: bool = False, memory: str = "") -> str:
    """Assemble identity, general guidance, active tools and workspace instructions."""
    workspace = workspace.resolve()
    sections = [
        PromptSection("harness:identity", -1000, "You are an AI agent powered by xsh."),
        PromptSection("deployment:persona", 0, f"You are a coding assistant powered by the {model} model."),
        PromptSection("harness:guidance", 100, files("xsh").joinpath("prompts/system.md").read_text(encoding="utf-8")),
        *tools.prompt_sections(),
        PromptSection("context:memory", 900, ("Workspace memory (durable notes from past sessions; keep it accurate):\n\n" + memory) if memory.strip() else ""),
        PromptSection("context:workspace", 1000, f"Workspace: {workspace}"),
    ]
    instructions = workspace / "AGENTS.md"
    if instructions.is_file():
        if not instructions.resolve().is_relative_to(workspace):
            raise ValueError("Root AGENTS.md resolves outside the workspace")
        with instructions.open("rb") as file:
            data = file.read(_MAX_INSTRUCTIONS_BYTES + 1)
        if len(data) > _MAX_INSTRUCTIONS_BYTES:
            raise ValueError(f"Root AGENTS.md exceeds {_MAX_INSTRUCTIONS_BYTES} bytes; shorten it before starting")
        sections.append(PromptSection("context:project", 1100, "Project instructions (AGENTS.md):\n\n" + data.decode("utf-8")))
    sections.extend(_nested_instruction_sections(workspace))
    if non_stop_mode:
        sections.append(PromptSection("harness:non-stop", 1200, files("xsh").joinpath("prompts/non-stop.md").read_text(encoding="utf-8")))
    return render_prompt(sections)


def _nested_instruction_sections(workspace: Path) -> list[PromptSection]:
    """收集子目录中的 AGENTS.md（不含根目录），带相对路径标注并限制数量与大小。"""
    sections: list[PromptSection] = []
    count = 0
    for path in sorted(workspace.rglob("AGENTS.md")):
        relative = path.relative_to(workspace)
        if relative.as_posix() == "AGENTS.md":
            continue
        if any(part in _SKIP_DIRECTORIES for part in relative.parts):
            continue
        if not path.is_file() or not path.resolve().is_relative_to(workspace):
            continue
        count += 1
        if count > _MAX_NESTED_INSTRUCTIONS:
            break
        with path.open("rb") as file:
            data = file.read(_MAX_INSTRUCTIONS_BYTES + 1)
        if len(data) > _MAX_INSTRUCTIONS_BYTES:
            raise ValueError(f"{relative} exceeds {_MAX_INSTRUCTIONS_BYTES} bytes; shorten it before starting")
        sections.append(PromptSection(
            f"context:project:{relative.as_posix()}",
            1100 + count,
            f"Project instructions ({relative.as_posix()}):\n\n" + data.decode("utf-8"),
        ))
    return sections
