"""Tests for the long-term memory store and tool."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from xsh.config import Settings
from xsh.memory import MemoryStore
from xsh.prompt import build_prompt
from xsh.tools.base import ToolRegistry
from xsh.tools.memory import MemoryArgs, MemoryTools


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k")


def test_store_roundtrip_and_remove(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.md")
    store.add(["hello world", "- second note"])
    store.save()

    reloaded = MemoryStore(tmp_path / "memory.md")
    assert reloaded.entries == ["hello world", "second note"]

    reloaded.remove([1])
    reloaded.save()
    assert MemoryStore(tmp_path / "memory.md").entries == ["second note"]


def test_reload_picks_up_external_edits(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    store = MemoryStore(path)
    assert store.entries == []
    path.write_text("# xsh memory\n\n- externally added\n", encoding="utf-8")
    store.reload()
    assert store.entries == ["externally added"]


def test_tool_add_replace_remove(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.md")
    tools = MemoryTools(store)

    out = tools.update(MemoryArgs(add=["a", "b"]))
    assert "- a" in out and "- b" in out
    tools.update(MemoryArgs(replace=["c"]))
    assert store.entries == ["c"]
    tools.update(MemoryArgs(remove=[1]))
    assert store.entries == []

    with pytest.raises(ValueError, match="out of range"):
        tools.update(MemoryArgs(remove=[5]))
    with pytest.raises(ValidationError):
        MemoryArgs()  # 必须指定 add / replace / remove 之一


def test_prompt_includes_memory(tmp_path: Path) -> None:
    prompt = build_prompt(tmp_path, model="m", tools=ToolRegistry.default(tmp_path, _settings()), memory="- user prefers tabs")
    assert "Workspace memory" in prompt
    assert "user prefers tabs" in prompt


def test_registry_registers_memory_tool(tmp_path: Path) -> None:
    registry = ToolRegistry.default(tmp_path, _settings(), memory_store=MemoryStore(tmp_path / "m.md"))
    assert "memory" in registry.tools
