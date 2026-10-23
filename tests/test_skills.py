"""Tests for the skills library and tool."""

from pathlib import Path

import pytest

from xsh.config import Settings
from xsh.prompt import build_prompt
from xsh.skills import SkillLibrary
from xsh.tools.base import ToolRegistry
from xsh.tools.skills import SkillArgs, SkillTools


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k")


def _library(tmp_path: Path) -> SkillLibrary:
    directory = tmp_path / "skills"
    directory.mkdir()
    (directory / "release.md").write_text("# Release checklist\n\nRun the tests first.\n", encoding="utf-8")
    (directory / "style.md").write_text("# Style guide\n\nPrefer small functions.\n", encoding="utf-8")
    return SkillLibrary(directory)


def test_library_lists_and_reads(tmp_path: Path) -> None:
    library = _library(tmp_path)
    assert library.names() == ["release", "style"]
    assert "- release: Release checklist" in library.render_index()
    assert "Run the tests first." in library.read("release")


def test_tool_lists_and_loads(tmp_path: Path) -> None:
    tools = SkillTools(_library(tmp_path))
    listing = tools.run(SkillArgs())
    assert "release" in listing and "style" in listing
    loaded = tools.run(SkillArgs(name="release"))
    assert loaded.startswith("Skill: release")
    assert "Run the tests first." in loaded
    with pytest.raises(ValueError, match="Unknown skill"):
        tools.run(SkillArgs(name="../secret"))
    with pytest.raises(ValueError, match="Available: release"):
        tools.run(SkillArgs(name="missing"))


def test_prompt_lists_skills(tmp_path: Path) -> None:
    library = _library(tmp_path)
    prompt = build_prompt(tmp_path, model="m", tools=ToolRegistry.default(tmp_path, _settings()), skills=library.render_index())
    assert "Available skills" in prompt
    assert "release" in prompt


def test_registry_registers_skill_tool(tmp_path: Path) -> None:
    registry = ToolRegistry.default(tmp_path, _settings(), skills_library=_library(tmp_path))
    assert "skill" in registry.tools
