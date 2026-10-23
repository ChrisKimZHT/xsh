"""Tests for subagent delegation (task tool)."""

import json
from pathlib import Path

import pytest

from xsh.config import Settings
from xsh.messages import ToolCall
from xsh.session import Session
from xsh.tools.base import Tool, ToolRegistry
from xsh.tools.task import TaskArgs, TaskTools


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k")


def test_delegate_forwards_prompt_and_returns_report() -> None:
    seen: list[str] = []
    tools = TaskTools(lambda prompt: seen.append(prompt) or f"report for {prompt}")
    out = tools.delegate(TaskArgs(prompt="do research"))
    assert seen == ["do research"]
    assert out == "report for do research"


def test_default_registry_has_no_task_tool(tmp_path: Path) -> None:
    # 子代理复用 default()，因此不会包含 task，避免递归委派。
    registry = ToolRegistry.default(tmp_path, _settings())
    assert "task" not in registry.tools


def test_registry_add_and_duplicate_guard(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    registry = ToolRegistry.default(tmp_path, _settings(), record=session.record)
    registry.add(TaskTools(lambda prompt: "ok").definitions())
    assert "task" in registry.tools
    with pytest.raises(ValueError, match="Duplicate tool name"):
        registry.add([Tool("read", "d", None, lambda args: "")])


def test_task_executes_through_registry(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    registry = ToolRegistry.default(tmp_path, _settings(), record=session.record)
    registry.add(TaskTools(lambda prompt: f"subagent says: {prompt}").definitions())

    call = ToolCall(id="1", name="task", arguments=json.dumps({"prompt": "hello", "label": "x"}))
    result = registry.execute(call)
    assert result.content == "subagent says: hello"
