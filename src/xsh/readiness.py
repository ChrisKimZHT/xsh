"""readiness.py - 启动就绪信号。

外部监督脚本需要判断“新启动的进程是否真正就绪”，而不是仅仅“命令已发出”或
“进程存在”。本模块在主流程完成配置解析、会话恢复、工具注册和模型客户端初始化后，
把本次启动的关键信息原子写入一个状态文件，供监督脚本关联到具体的一次启动。

设计要点：
- 记录唯一 boot_id 与进程 PID，使监督脚本能把文件关联到本次启动；
- 采用“临时文件 + os.replace”的原子替换，避免读到半截内容；
- 记录 epoch 时间戳，便于监督脚本按“晚于启动时刻”过滤旧文件；
- 写入失败只影响监督流程，不应中断主任务，因此调用方需要容错。
"""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

READY_FORMAT_VERSION = 1


def new_boot_id() -> str:
    """为一次启动生成唯一标识。"""
    return uuid4().hex


def build_record(
    *,
    boot_id: str,
    resumed: bool,
    workspace: Path,
    session: Path,
    model: str,
    non_stop: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造就绪记录内容，便于测试与复用。"""
    record: dict[str, Any] = {
        "version": READY_FORMAT_VERSION,
        "boot_id": boot_id,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "epoch": time.time(),
        "started_at": datetime.now(UTC).isoformat(),
        "resumed": bool(resumed),
        "non_stop": bool(non_stop),
        "workspace": str(workspace),
        "session": str(session),
        "model": model,
    }
    if extra:
        record.update(extra)
    return record


def write_ready_file(path: Path, record: dict[str, Any]) -> None:
    """原子写入就绪文件；调用方负责捕获 OSError。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{record.get('boot_id', uuid4().hex)}.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
