"""Ordered prompt contributions, assembled from the active tool registry."""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xsh.tools.base import ToolRegistry

_MAX_INSTRUCTIONS_BYTES = 128_000


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


def build_prompt(workspace: Path, *, model: str, tools: "ToolRegistry") -> str:
    """Assemble identity, general guidance, active tools and workspace instructions."""
    workspace = workspace.resolve()
    sections = [
        PromptSection("harness:identity", -1000, "You are an AI agent powered by xsh."),
        PromptSection("deployment:persona", 0, f"You are a coding assistant powered by the {model} model."),
        PromptSection("harness:guidance", 100, files("xsh").joinpath("prompts/system.md").read_text(encoding="utf-8")),
        *tools.prompt_sections(),
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
    return render_prompt(sections)
