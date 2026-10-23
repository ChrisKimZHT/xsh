"""Tests for the todo (task list) tool."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xsh.config import Settings
from xsh.messages import ToolCall
from xsh.session import Session
from xsh.tools.base import ToolRegistry
from xsh.tools.todo import TodoArgs, TodoTools


def _settings() -> Settings:
    return Settings(base_url="https://api.example/v1", model="m", api_key="k")


def test_todo_update_records_formats_and_persists(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "s.jsonl", tmp_path, "system prompt")
    reports: list[tuple[str, str]] = []
    tools = TodoTools(record=session.record, report=lambda kind, text: reports.append((kind, text)))

    out = tools.update(TodoArgs(todos=[
        {"content": "first", "status": "completed"},
        {"content": "second", "status": "in_progress"},
    ]))
    assert "[x] first" in out and "[~] second" in out
    assert reports and reports[0][0] == "todos"

    loaded = Session.load(session.path)
    assert [t["content"] for t in loaded.todos] == ["first", "second"]
    assert loaded.todos[1]["status"] == "in_progress"


def test_todo_args_validation() -> None:
    with pytest.raises(ValidationError):
        TodoArgs(todos=[])
    with pytest.raises(ValidationError):
        TodoArgs(todos=[{"content": "x", "status": "bogus"}])


def test_todo_is_registered_and_executes(tmp_path: Path) -> None:
    session = Session.create(tmp_path / "r.jsonl", tmp_path, "system prompt")
    registry = ToolRegistry.default(tmp_path, _settings(), record=session.record)
    assert "todo" in registry.tools

    call = ToolCall(id="1", name="todo", arguments=json.dumps({"todos": [{"content": "x", "status": "pending"}]}))
    result = registry.execute(call)
    assert result.content.startswith("Todo list updated")
