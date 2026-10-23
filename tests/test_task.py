"""Tests for subagent delegation (task tool)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xsh.config import Settings
from xsh.messages import ToolCall
from xsh.session import Session
from xsh.tools.base import Tool, ToolRegistry
from xsh.tools.task import TaskArgs, TaskStatusArgs, TaskTools


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k")


def test_delegate_forwards_single_and_multiple_prompts() -> None:
    seen: list[list[str]] = []

    def run(prompts) -> str:
        seen.append(list(prompts))
        return f"reports for {list(prompts)}"

    tools = TaskTools(run)
    assert tools.delegate(TaskArgs(prompt="one")) == "reports for ['one']"
    assert tools.delegate(TaskArgs(prompts=["a", "b"])) == "reports for ['a', 'b']"
    assert seen == [["one"], ["a", "b"]]


def test_targets_prefers_prompts_and_requires_something() -> None:
    assert TaskArgs(prompts=["a", "", "b"]).targets() == ["a", "b"]
    assert TaskArgs(prompt="  solo  ").targets() == ["solo"]
    with pytest.raises(ValidationError):
        TaskArgs()


def test_default_registry_has_no_task_tool(tmp_path: Path) -> None:
    # 子代理复用 default()，因此不会包含 task，避免递归委派。
    registry = ToolRegistry.default(tmp_path, _settings())
    assert "task" not in registry.tools


def test_registry_add_and_duplicate_guard(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    registry = ToolRegistry.default(tmp_path, _settings(), record=session.record)
    registry.add(TaskTools(lambda prompts: "ok").definitions())
    assert "task" in registry.tools
    with pytest.raises(ValueError, match="Duplicate tool name"):
        registry.add([Tool("read", "d", None, lambda args: "")])


def test_task_executes_through_registry(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system")
    registry = ToolRegistry.default(tmp_path, _settings(), record=session.record)
    registry.add(TaskTools(lambda prompts: f"subagent says: {', '.join(prompts)}").definitions())

    call = ToolCall(id="1", name="task", arguments=json.dumps({"prompts": ["x", "y"], "label": "l"}))
    result = registry.execute(call)
    assert result.content == "subagent says: x, y"


def test_background_delegation_and_status_tool() -> None:
    started: list[list[str]] = []
    tools = TaskTools(
        lambda prompts: "foreground",
        start=lambda prompts: started.append(list(prompts)) or "handle-1",
        status=lambda job_id: f"status:{job_id or 'all'}",
    )
    assert tools.delegate(TaskArgs(prompt="x", background=True)) == "handle-1"
    assert started == [["x"]]
    assert tools.delegate(TaskArgs(prompt="x")) == "foreground"
    assert tools.poll(TaskStatusArgs()) == "status:all"
    assert tools.poll(TaskStatusArgs(id="abc")) == "status:abc"

    names = {tool.name for tool in tools.definitions()}
    assert names == {"task", "task_status"}
    # 未提供 status 时只注册 task。
    assert {tool.name for tool in TaskTools(lambda prompts: "ok").definitions()} == {"task"}


def test_background_requires_start() -> None:
    with pytest.raises(ValueError, match="not available"):
        TaskTools(lambda prompts: "ok").delegate(TaskArgs(prompt="x", background=True))
