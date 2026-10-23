"""background.py - 后台子任务表：立即返回句柄，由 task_status 轮询。

把"启动/查询"逻辑从 cli 中抽出来，便于独立测试；每个任务在单独线程中运行，
结果与状态受锁保护。任务表仅存在于进程内（重启即清空）。
"""

import threading
import time
from collections.abc import Callable, Sequence
from uuid import uuid4


class BackgroundJobs:
    def __init__(self, runner: Callable[[Sequence[str]], str]):
        self.runner = runner
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, prompts: Sequence[str]) -> str:
        job_id = uuid4().hex[:8]
        with self._lock:
            self._jobs[job_id] = {"status": "running", "result": "", "started": time.monotonic(), "finished": None}

        def worker() -> None:
            try:
                text = self.runner(prompts)
            except Exception as error:  # noqa: BLE001
                text = f"error: {type(error).__name__}: {error}"
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.update(status="done", result=text, finished=time.monotonic())

        threading.Thread(target=worker, daemon=True).start()
        return f'Background task {job_id} started. Poll with task_status(id="{job_id}").'

    def status(self, job_id: str = "") -> str:
        with self._lock:
            snapshot = {key: dict(value) for key, value in self._jobs.items()}
        if not job_id:
            if not snapshot:
                return "No background tasks."
            lines = []
            for key, job in snapshot.items():
                if job["status"] == "running":
                    lines.append(f"- {key}: running ({time.monotonic() - job['started']:.0f}s)")
                else:
                    lines.append(f"- {key}: done")
            return "Background tasks:\n" + "\n".join(lines)
        job = snapshot.get(job_id)
        if job is None:
            return f"Unknown background task: {job_id}"
        if job["status"] == "running":
            return f"Background task {job_id} is still running ({time.monotonic() - job['started']:.0f}s)."
        return f"Background task {job_id} finished:\n{job['result']}"
