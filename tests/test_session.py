"""Tests for resilient session loading."""

import json
from pathlib import Path

import pytest

from xsh.messages import Message, ToolCall
from xsh.session import Session


def _new_session(tmp_path: Path) -> Session:
    return Session.create(tmp_path / "session.jsonl", tmp_path, "system prompt")


def test_load_roundtrip(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="hello"))
    loaded = Session.load(session.path)
    assert loaded.turn_count == 1
    assert loaded.messages[1].content == "hello"


def test_load_tolerates_truncated_final_line(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="hello"))
    # 模拟进程写入最后一条记录时被中断，留下半行 JSON。
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write('{"time": "2026-10-23T00:00:00')

    loaded = Session.load(session.path)
    assert loaded.turn_count == 1
    assert loaded.messages[1].content == "hello"
    # 残片被物理截断：文件以换行结尾，且再次恢复仍然成功。
    assert session.path.read_bytes().endswith(b"\n")
    assert Session.load(session.path).turn_count == 1


def test_load_keeps_complete_record_missing_newline(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="hello"))
    # 模拟在写入 JSON 之后、写入换行符之前被中断。
    session.path.write_bytes(session.path.read_bytes().rstrip(b"\n"))

    loaded = Session.load(session.path)
    assert loaded.turn_count == 1
    assert session.path.read_bytes().endswith(b"\n")


def test_load_rejects_corrupt_middle_line(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="hello"))
    # 在中间插入损坏行，再追加一条合法记录，使其不是最后一行。
    with session.path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"time": "x", "type": "message", "data": Message(role="user", content="world").model_dump()}) + "\n")

    with pytest.raises(ValueError, match="Corrupt session event"):
        Session.load(session.path)


def test_load_rejects_missing_header(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text('{"time": "x", "type": "message", "data": {}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Missing session header"):
        Session.load(path)


def test_load_marks_started_tool_call_as_unknown(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    call = ToolCall(id="c1", name="shell", arguments="{}")
    session.append(Message(role="user", content="go"))
    session.append(Message(role="assistant", tool_calls=[call]))
    session.start_tool(call)  # 已派发但未收到结果

    loaded = Session.load(session.path)
    assert loaded.recovered_tool_calls == 1
    assert loaded.messages[-1].role == "tool"
    assert "TOOL_OUTCOME_UNKNOWN" in (loaded.messages[-1].content or "")


def test_load_marks_unstarted_tool_call_as_not_started(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    call = ToolCall(id="c2", name="read", arguments="{}")
    session.append(Message(role="user", content="go"))
    session.append(Message(role="assistant", tool_calls=[call]))

    loaded = Session.load(session.path)
    assert loaded.recovered_tool_calls == 1
    assert "TOOL_NOT_STARTED" in (loaded.messages[-1].content or "")


def test_repair_pending_returns_zero_when_nothing_pending(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="hi"))
    assert session.repair_pending() == 0


def test_load_replays_compaction_checkpoint(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    for index in range(3):
        session.append(Message(role="user", content=f"u{index}"))
        session.append(Message(role="assistant", content=f"a{index}"))
    turns_before = session.turn_count

    summary = Message(role="user", content="earlier conversation checkpoint")
    session.compact(2, summary)  # 用摘要替换 messages[1:2]

    loaded = Session.load(session.path)
    assert loaded.messages[1].content == "earlier conversation checkpoint"
    assert loaded.message_positions[1] is None  # 摘要不占用 Turn/Step 位置
    assert loaded.turn_count == turns_before  # 摘要不增加轮次
    assert loaded.messages[-1].content == "a2"


def test_load_without_repair_leaves_pending(tmp_path: Path) -> None:
    session = _new_session(tmp_path)
    session.append(Message(role="user", content="go"))
    session.append(Message(role="assistant", tool_calls=[ToolCall(id="c9", name="shell", arguments="{}")]))

    loaded = Session.load(session.path, repair=False)
    assert loaded.recovered_tool_calls == 0
    assert loaded.pending  # 未修复时仍处于挂起状态
