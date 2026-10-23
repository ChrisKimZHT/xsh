"""doctor.py - 环境自检：工作区、配置与可选依赖的可诊断报告。

只做只读检查，便于在启动/排障时快速确认环境。返回 (name, status, detail) 三元组列表，
status ∈ {ok, warn, fail}。
"""

import json
import os
from pathlib import Path

from xsh.config import STATE_DIRECTORY, Settings

Check = tuple[str, str, str]

OK, WARN, FAIL = "ok", "warn", "fail"


def _json_check(path: Path) -> Check:
    if not path.is_file():
        return (path.name, OK, "not present (optional)")
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return (path.name, FAIL, f"invalid: {type(error).__name__}: {error}")
    return (path.name, OK, "parsed")


def run_checks(workspace: Path, settings: Settings, allow_shell: bool = False) -> list[Check]:
    """返回一组只读检查结果。"""
    workspace = Path(workspace)
    state = workspace / STATE_DIRECTORY
    checks: list[Check] = []
    checks.append(("workspace", OK if workspace.is_dir() else FAIL, str(workspace)))
    checks.append(("workspace writable", OK if os.access(workspace, os.W_OK) else WARN, "needed for edits" if os.access(workspace, os.W_OK) else "read-only"))
    checks.append(("state dir", OK if state.is_dir() else WARN, str(state) if state.is_dir() else "created on demand"))
    checks.append(("model", OK if settings.model and settings.base_url else FAIL, f"{settings.model} @ {settings.base_url}"))
    has_key = bool(settings.api_key and settings.api_key.get_secret_value())
    checks.append(("api key", OK if has_key else WARN, "set" if has_key else "missing; set XSH_API_KEY"))
    checks.append(("context window", OK if settings.context_window else WARN, f"{settings.context_window:,}" if settings.context_window else "unknown; set XSH_CONTEXT_WINDOW"))
    checks.append(("shell", OK if allow_shell else WARN, "enabled" if allow_shell else "disabled (pass --allow-shell)"))
    for name in ("hooks.json", "mcp.json", "permissions.json"):
        checks.append(_json_check(state / name))
    skills = state / "skills"
    checks.append(("skills", OK if skills.is_dir() else WARN, f"{len(list(skills.glob('*.md')))} skill(s)" if skills.is_dir() else "not present (optional)"))
    memory = state / "memory.md"
    checks.append(("memory", OK if memory.is_file() else WARN, f"{(memory.stat().st_size if memory.is_file() else 0):,} bytes" if memory.is_file() else "not present (optional)"))
    return checks


def render(checks: list[Check]) -> str:
    """把检查结果渲染为多行文本。"""
    lines = [f"[{status}] {name}: {detail}" for name, status, detail in checks]
    failures = sum(1 for _, status, _ in checks if status == FAIL)
    lines.append("")
    lines.append(f"{failures} failure(s), {sum(1 for _, s, _ in checks if s == WARN)} warning(s)")
    return "\n".join(lines)
