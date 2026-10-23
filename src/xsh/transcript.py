"""transcript.py - 把会话消息渲染为可移植的 Markdown 转录。"""

from datetime import datetime
from pathlib import Path

from xsh.messages import Message
from xsh.session import Session


def render_transcript(messages: list[Message], extra_sections: list[tuple[str, str]] | None = None) -> str:
    """把消息序列渲染为 Markdown 文本；extra_sections 追加为末尾小节。"""
    lines = ["# xsh transcript", ""]
    for index, message in enumerate(messages, start=1):
        lines.append(f"## {index}. {message.role}")
        lines.append("")
        if message.reasoning_content:
            lines.append("> " + message.reasoning_content.replace("\n", "\n> "))
            lines.append("")
        if message.content:
            lines.append(message.content)
            lines.append("")
        for call in message.tool_calls:
            lines.append(f"- `{call.name}` `{call.arguments}`")
        if message.tool_calls:
            lines.append("")
    for title, body in extra_sections or []:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(body.rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_transcript(session: Session, workspace: Path, target: str | None = None, extra_sections: list[tuple[str, str]] | None = None) -> Path:
    """把会话导出为 Markdown 文件；target 省略时按时间戳命名。"""
    workspace = Path(workspace).resolve()
    if target:
        path = (workspace / target).resolve()
        if not path.is_relative_to(workspace):
            raise ValueError("Export path must stay inside the workspace")
    else:
        path = workspace / f"xsh-transcript-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_transcript(session.messages, extra_sections), encoding="utf-8")
    return path
