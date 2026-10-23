"""Tests for system-prompt assembly."""

from pathlib import Path

import pytest

from xsh.prompt import build_prompt, render_prompt


class _Tools:
    def prompt_sections(self):
        return []


def test_build_prompt_includes_identity_and_workspace(tmp_path: Path) -> None:
    prompt = build_prompt(tmp_path, model="test-model", tools=_Tools())
    assert "You are an AI agent powered by xsh." in prompt
    assert "test-model" in prompt
    assert f"Workspace: {tmp_path.resolve()}" in prompt


def test_build_prompt_includes_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("PROJECT RULES HERE", encoding="utf-8")
    prompt = build_prompt(tmp_path, model="m", tools=_Tools())
    assert "Project instructions (AGENTS.md):" in prompt
    assert "PROJECT RULES HERE" in prompt


def test_non_stop_mode_adds_its_section(tmp_path: Path) -> None:
    base = build_prompt(tmp_path, model="m", tools=_Tools(), non_stop_mode=False)
    assert "Non-stop mode is active" not in base
    active = build_prompt(tmp_path, model="m", tools=_Tools(), non_stop_mode=True)
    assert "Non-stop mode is active" in active


def test_agents_md_escaping_workspace_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-agents.md"
    outside.write_text("secret", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    try:
        (workspace / "AGENTS.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not supported here")
    with pytest.raises(ValueError, match="outside the workspace"):
        build_prompt(workspace, model="m", tools=_Tools())


def test_render_prompt_is_deterministic() -> None:
    from xsh.prompt import PromptSection

    sections = [PromptSection("z", 1, "zz"), PromptSection("a", 0, "aa")]
    assert render_prompt(sections) == "aa\n\nzz"


def test_build_prompt_includes_nested_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rules", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("pkg rules", encoding="utf-8")

    prompt = build_prompt(tmp_path, model="m", tools=_Tools())
    assert "Project instructions (AGENTS.md):" in prompt
    assert "Project instructions (pkg/AGENTS.md):" in prompt
    assert "pkg rules" in prompt


def test_nested_agents_md_skips_reserved_directories(tmp_path: Path) -> None:
    hidden = tmp_path / ".xsh"
    hidden.mkdir()
    (hidden / "AGENTS.md").write_text("hidden rules", encoding="utf-8")
    prompt = build_prompt(tmp_path, model="m", tools=_Tools())
    assert "hidden rules" not in prompt


def test_build_prompt_includes_memory_and_skills(tmp_path: Path) -> None:
    prompt = build_prompt(tmp_path, model="m", tools=_Tools(), memory="REMEMBER THIS", skills="- skill-a: does a")
    assert "REMEMBER THIS" in prompt
    assert "- skill-a: does a" in prompt
