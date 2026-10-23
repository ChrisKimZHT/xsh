"""Tests for file tools: workspace confinement, read-before-write, edit semantics."""

from pathlib import Path

import pytest

from xsh.tools.files import EditArgs, FileTools, GlobArgs, GrepArgs, ReadArgs, WriteArgs


@pytest.fixture
def tools(tmp_path: Path) -> FileTools:
    return FileTools(tmp_path)


def test_resolve_confines_to_workspace(tmp_path: Path, tools: FileTools) -> None:
    with pytest.raises(ValueError, match="outside the workspace"):
        tools.resolve("../escape.txt")
    with pytest.raises(ValueError, match="reserved"):
        tools.resolve(".xsh/session.jsonl")


def test_write_then_read_roundtrip(tools: FileTools) -> None:
    assert tools.write(WriteArgs(file_path="a.txt", content="one\ntwo\n")) == "Wrote a.txt"
    out = tools.read(ReadArgs(file_path="a.txt"))
    assert "1: one" in out and "2: two" in out
    assert "Total lines: 2" in out


def test_write_detects_external_change(tools: FileTools, tmp_path: Path) -> None:
    tools.write(WriteArgs(file_path="a.txt", content="one"))
    # 工具自身写入算作一次观测；绕过工具的外部修改应被拒绝。
    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="unread or changed"):
        tools.write(WriteArgs(file_path="a.txt", content="two"))
    tools.read(ReadArgs(file_path="a.txt"))
    assert tools.write(WriteArgs(file_path="a.txt", content="two")).startswith("Wrote")


def test_edit_requires_observation_and_unique_match(tools: FileTools, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\nx\n", encoding="utf-8")  # 未经工具创建
    with pytest.raises(ValueError, match="unread or changed"):
        tools.edit(EditArgs(file_path="a.txt", old_string="x", new_string="y"))

    tools.read(ReadArgs(file_path="a.txt"))
    with pytest.raises(ValueError, match="Found 2 matches"):
        tools.edit(EditArgs(file_path="a.txt", old_string="x", new_string="y"))
    assert tools.edit(EditArgs(file_path="a.txt", old_string="x", new_string="y", replace_all=True)) == "Edited a.txt (2 match(es))"


def test_edit_same_string_and_missing_string(tools: FileTools) -> None:
    tools.write(WriteArgs(file_path="a.txt", content="hello"))
    tools.read(ReadArgs(file_path="a.txt"))
    with pytest.raises(ValueError, match="must differ"):
        tools.edit(EditArgs(file_path="a.txt", old_string="hello", new_string="hello"))
    with pytest.raises(ValueError, match="not found"):
        tools.edit(EditArgs(file_path="a.txt", old_string="nope", new_string="x"))


def test_read_rejects_binary(tools: FileTools, tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"a\0b")
    with pytest.raises(ValueError, match="Binary"):
        tools.read(ReadArgs(file_path="bin.dat"))


def test_glob_and_grep(tools: FileTools) -> None:
    tools.write(WriteArgs(file_path="pkg/a.py", content="needle\n"))
    tools.write(WriteArgs(file_path="pkg/b.txt", content="needle here\n"))
    assert "pkg/a.py" in tools.glob(GlobArgs(pattern="**/*.py"))
    found = tools.grep(GrepArgs(pattern="needle", glob="**/*.py"))
    assert "pkg/a.py:1: needle" in found
    assert "b.txt" not in found
    assert tools.glob(GlobArgs(pattern="*.nomatch")) == "No files matched."


def test_glob_rejects_absolute_and_parent(tools: FileTools) -> None:
    with pytest.raises(ValueError):
        tools.glob(GlobArgs(pattern="/etc/*"))
    with pytest.raises(ValueError):
        tools.glob(GlobArgs(pattern="../*"))


def test_grep_regex_ignore_case_and_context(tools: FileTools) -> None:
    tools.write(WriteArgs(file_path="x.txt", content="alpha\nBETA\ngamma\n"))

    regex = tools.grep(GrepArgs(pattern=r"\b(beta|gamma)\b", glob="*.txt", regex=True, ignore_case=True, context=1))
    assert "x.txt:2: BETA" in regex
    assert "x.txt-1- alpha" in regex  # 上下文行用 '-' 分隔
    assert "x.txt:3: gamma" in regex

    with pytest.raises(ValueError, match="Invalid regular expression"):
        tools.grep(GrepArgs(pattern="(", glob="*.txt", regex=True))
