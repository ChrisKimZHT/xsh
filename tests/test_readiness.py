"""Tests for the startup readiness signal used by external supervisors."""

import json
from pathlib import Path

from xsh.readiness import READY_FORMAT_VERSION, build_record, new_boot_id, write_ready_file


def _record(tmp_path: Path, *, boot_id: str = "boot") -> dict:
    return build_record(
        boot_id=boot_id,
        resumed=True,
        workspace=tmp_path,
        session=tmp_path / "session.jsonl",
        model="test-model",
        non_stop=True,
    )


def test_build_record_contains_correlation_fields(tmp_path: Path) -> None:
    boot_id = new_boot_id()
    record = _record(tmp_path, boot_id=boot_id)
    assert record["version"] == READY_FORMAT_VERSION
    assert record["boot_id"] == boot_id
    assert isinstance(record["pid"], int) and record["pid"] > 0
    assert isinstance(record["ppid"], int) and record["ppid"] > 0
    assert record["resumed"] is True
    assert record["non_stop"] is True
    assert record["session"] == str(tmp_path / "session.jsonl")
    assert isinstance(record["epoch"], float) and record["epoch"] > 0


def test_boot_ids_are_unique() -> None:
    assert new_boot_id() != new_boot_id()


def test_write_ready_file_is_parseable_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ready.json"
    record = _record(tmp_path, boot_id="first")
    write_ready_file(path, record)
    assert json.loads(path.read_text(encoding="utf-8"))["boot_id"] == "first"

    # A second write must replace the file and leave no temporary artifacts behind.
    write_ready_file(path, _record(tmp_path, boot_id="second"))
    assert json.loads(path.read_text(encoding="utf-8"))["boot_id"] == "second"
    leftovers = [p.name for p in path.parent.iterdir() if p.name != path.name]
    assert leftovers == []
