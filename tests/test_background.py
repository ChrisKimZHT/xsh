"""Tests for the background subtask table."""

import threading
import time
from collections.abc import Sequence

from xsh.background import BackgroundJobs


def _wait(jobs: BackgroundJobs, job_id: str) -> str:
    status = ""
    for _ in range(200):
        status = jobs.status(job_id)
        if "finished" in status:
            return status
        time.sleep(0.02)
    return status


def _job_id(handle: str) -> str:
    return handle.split()[2]


def test_start_and_complete() -> None:
    jobs = BackgroundJobs(lambda prompts: "result:" + ",".join(prompts))
    handle = jobs.start(["a", "b"])
    assert "started" in handle
    assert "result:a,b" in _wait(jobs, _job_id(handle))


def test_list_and_unknown_id() -> None:
    jobs = BackgroundJobs(lambda prompts: "x")
    assert jobs.status() == "No background tasks."
    assert "Unknown" in jobs.status("nope")


def test_error_is_captured() -> None:
    def boom(prompts: Sequence[str]) -> str:
        raise ValueError("boom")

    jobs = BackgroundJobs(boom)
    handle = jobs.start(["a"])
    assert "ValueError: boom" in _wait(jobs, _job_id(handle))


def test_running_status_includes_elapsed() -> None:
    gate = threading.Event()
    jobs = BackgroundJobs(lambda prompts: gate.wait(timeout=2) or "done")
    handle = jobs.start(["a"])
    try:
        status = jobs.status(_job_id(handle))
        assert "still running" in status and "s)" in status
        assert "running" in jobs.status()  # 列表中也显示运行中
    finally:
        gate.set()
    _wait(jobs, _job_id(handle))
