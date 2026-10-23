"""Tests for prompt section ordering/deduplication and tool registry execution."""

import pytest

from xsh.messages import ToolCall
from xsh.prompt import PromptSection, render_prompt
from xsh.tools.base import Tool, ToolArgs, ToolRegistry, bounded


def test_render_prompt_orders_and_dedupes() -> None:
    sections = [
        PromptSection("b", 20, "second"),
        PromptSection("a", 10, "first "),
        PromptSection("a", 10, "first "),  # 完全相同的重复项合并
        PromptSection("empty", 30, "   "),
    ]
    assert render_prompt(sections) == "first\n\nsecond"


def test_render_prompt_rejects_conflicting_sections() -> None:
    with pytest.raises(ValueError, match="Conflicting prompt section"):
        render_prompt([PromptSection("x", 1, "one"), PromptSection("x", 1, "two")])


class _EchoArgs(ToolArgs):
    value: str


def _registry() -> ToolRegistry:
    return ToolRegistry([
        Tool("echo", "echo", _EchoArgs, lambda args: f"echo:{args.value}"),
        Tool("big", "big", _EchoArgs, lambda args: "x" * 100, output_limit=20),
    ])


def test_registry_rejects_duplicate_names() -> None:
    tool = Tool("dup", "d", _EchoArgs, lambda args: "")
    with pytest.raises(ValueError, match="Duplicate tool names"):
        ToolRegistry([tool, tool])


def test_registry_executes_and_bounds_output() -> None:
    registry = _registry()
    ok = registry.execute(ToolCall(id="1", name="echo", arguments='{"value":"hi"}'))
    assert ok.role == "tool" and ok.content == "echo:hi"

    big = registry.execute(ToolCall(id="2", name="big", arguments='{"value":"hi"}'))
    assert len(big.content) <= 20  # 被裁剪到不超过工具的输出上限


def test_bounded_never_exceeds_tiny_limit() -> None:
    assert len(bounded("y" * 200, 10)) <= 10
    assert len(bounded("y" * 200, 1)) <= 1


def test_registry_reports_unknown_tool_and_bad_arguments() -> None:
    registry = _registry()
    unknown = registry.execute(ToolCall(id="1", name="nope", arguments="{}"))
    assert unknown.content.startswith("Error:") and "Unknown tool" in unknown.content

    bad = registry.execute(ToolCall(id="2", name="echo", arguments="not json"))
    assert bad.content.startswith("Error:")


def test_bounded_passes_short_text_through() -> None:
    assert bounded("hello", 100) == "hello"
    assert "[Output truncated" in bounded("y" * 200, 50)
