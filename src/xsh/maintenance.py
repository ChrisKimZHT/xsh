"""maintenance.py - 会话文件维护：安全地压缩超大的 JSONL 会话。

早期版本会把每一步的完整请求体写入会话文件，造成 O(n^2) 膨胀（现已修复，但旧文件
仍然很大）。本模块在**保留足以重建对话的事件**的前提下，丢弃冗余的诊断事件
（request/response/compaction_* 等），从而缩小文件、加快恢复。

安全措施：
- 只丢弃已知的冗余事件类型，未知类型一律保留；
- 先在临时文件中重建并加载校验（消息数、轮次数、消息内容一致）再替换；
- 替换前保留 `.bak` 备份；
- 本工具应在 xsh 停止时运行。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xsh.session import Session, _read_events

# 这些事件仅用于诊断，重建对话时不需要，可安全丢弃。
_DROP_TYPES = frozenset({
    "request",
    "response",
    "compaction_start",
    "compaction_response",
    "compaction_end",
    "web_search_request",
})


def _dump(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, allow_nan=False)


def compact_session_file(path: Path, *, backup: bool = True) -> dict[str, Any]:
    """原地压缩一个会话文件，返回统计信息。校验失败时不做任何替换。"""
    path = Path(path).resolve()
    before_bytes = path.stat().st_size
    events = _read_events(path)  # 同时修复可能存在的末尾残片
    kept = [event for event in events if event.get("type") not in _DROP_TYPES]
    if len(kept) == len(events):
        return {
            "changed": False,
            "path": str(path),
            "before_bytes": before_bytes,
            "after_bytes": before_bytes,
            "events_before": len(events),
            "events_after": len(kept),
        }

    temporary = path.with_name(path.name + ".compacted")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for event in kept:
            handle.write(_dump(event) + "\n")

    try:
        original = Session.load(path, repair=False)
        rebuilt = Session.load(temporary, repair=False)
        same = (
            len(original.messages) == len(rebuilt.messages)
            and original.turn_count == rebuilt.turn_count
            and [m.model_dump() for m in original.messages] == [m.model_dump() for m in rebuilt.messages]
        )
        if not same:
            raise ValueError("Compacted session does not reconstruct the same state; keeping original")

        if backup:
            backup_path = path.with_name(path.name + ".bak")
            if not backup_path.exists():
                backup_path.write_bytes(path.read_bytes())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

    after_bytes = path.stat().st_size
    return {
        "changed": True,
        "path": str(path),
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "events_before": len(events),
        "events_after": len(kept),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compact an xsh session JSONL file (keep a .bak backup).")
    parser.add_argument("session", type=Path, help="Path to a session .jsonl file")
    parser.add_argument("--no-backup", action="store_true", help="Do not keep a .bak copy of the original")
    args = parser.parse_args(argv)
    if not args.session.is_file():
        print(f"xsh: not a file: {args.session}", file=sys.stderr)
        return 2
    try:
        stats = compact_session_file(args.session, backup=not args.no_backup)
    except (OSError, ValueError) as error:
        print(f"xsh: {error}", file=sys.stderr)
        return 1
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
