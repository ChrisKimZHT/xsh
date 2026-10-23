"""cli.py - 主函数，准备会话、工具、模型，创建 Agent 并运行，维护 Turn 循环"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from xsh.agent import Agent
from xsh.compaction import Compactor
from xsh.config import STATE_DIRECTORY, Settings
from xsh.model import OpenAIModel, discover_context_window
from xsh.prompt import build_prompt
from xsh.session import Session
from xsh.terminal import Terminal
from xsh.tools.base import ToolRegistry

_SESSION_DIRECTORY = Path(STATE_DIRECTORY) / "sessions"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="xsh - a deliberately small, single-agent harness")
    result.add_argument("prompt", nargs="?", help="Run one task; omit for interactive mode")
    result.add_argument("--workspace", type=Path, help="File-tool root; defaults to current directory")
    sessions = result.add_mutually_exclusive_group()
    sessions.add_argument("--session", type=Path, help="Create a new JSONL file at this path")
    sessions.add_argument("--resume", type=Path, nargs="?", const=True, help="Resume a JSONL session; omit the path for the most recently modified default session")
    result.add_argument("--allow-shell", action="store_true", help="Enable unsandboxed shell execution")
    result.add_argument("--verbose", action="store_true", help="Show the system prompt, reasoning, and tool results on stdout")

    # 覆盖 .env 配置的命令行参数
    result.add_argument("--base-url", help="OpenAI-compatible API base URL")
    result.add_argument("--model", help="Provider model identifier")
    result.add_argument("--api-key", help="Provider API key")
    result.add_argument("--max-steps", type=int)
    result.add_argument("--max-tokens", type=int, help="Maximum output tokens per model request")
    result.add_argument("--context-window", type=int, help="Model context window in tokens, will override by automatic discovery")
    result.add_argument("--auto-compact", action=argparse.BooleanOptionalAction, default=None, help="Automatically compact context before model requests")
    result.add_argument("--compact-threshold", type=float, help="Context pressure fraction (default: 0.8)")
    result.add_argument("--compact-retain-ratio", type=float, help="Recent context fraction to retain (default: 0.16)")
    result.add_argument("--compact-max-tokens", type=int, help="Maximum summary output tokens (default: 4096)")
    result.add_argument("--request-timeout", type=float, help="API request timeout in seconds")
    result.add_argument("--max-retries", type=int, help="Maximum API request retries")
    return result


def main(argv: list[str] | None = None) -> int:
    # ============================================
    # 阶段 1：解析参数、加载配置、初始化终端和工作目录
    # ============================================
    args = parser().parse_args(argv)
    # 优先读取当前目录，再由安装目录补充；已有环境变量保持不变。
    load_dotenv(Path.cwd() / ".env", override=False)
    install_directory = Path(__file__).resolve().parent
    if install_directory.parent.name == "src":
        install_directory = install_directory.parent.parent
    load_dotenv(install_directory / ".env", override=False)

    # 仅支持终端输出；重定向或管道无法渲染动态界面，直接报错退出。
    try:
        terminal = Terminal(verbose=args.verbose)
    except OSError as error:
        print(f"xsh: {error}", file=sys.stderr)
        return 2

    try:
        workspace = (args.workspace or Path.cwd()).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Workspace must be a directory")

        # 覆盖 .env 配置的命令行参数
        settings = Settings.from_env(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            context_window=args.context_window,
            auto_compact=args.auto_compact,
            compact_threshold=args.compact_threshold,
            compact_retain_ratio=args.compact_retain_ratio,
            compact_max_tokens=args.compact_max_tokens,
            request_timeout=args.request_timeout,
            max_retries=args.max_retries,
        )

        # ===========================
        # 阶段 2：准备会话（恢复/创建）
        # ===========================
        terminal.context_window = settings.context_window
        if args.resume is not None:
            resume_path = args.resume
            if resume_path is True:  # 如果没有提供路径，则 resume 最近的会话
                session_directory = workspace / _SESSION_DIRECTORY
                resume_path = None
                # 找最近修改的会话文件作为恢复路径
                latest_modified_time = -1
                for path in sorted(session_directory.glob("*.jsonl")):
                    if not path.is_file():
                        continue
                    modified_time = path.stat().st_mtime_ns
                    if modified_time >= latest_modified_time:
                        resume_path = path
                        latest_modified_time = modified_time
                if resume_path is None:
                    raise ValueError(f"No sessions found in {session_directory}")
            session = Session.load(resume_path)
            if args.workspace and workspace != session.workspace:
                raise ValueError("Resumed session belongs to a different workspace")
            workspace = session.workspace
        else:
            filename = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".jsonl"
            default_path = workspace / _SESSION_DIRECTORY / filename
            path = args.session or default_path
            session = Session.create(path, workspace, "")  # 此时系统提示词还没准备好，后续会更新

        # ==============================
        # 阶段 3：注册工具、准备系统提示词
        # ==============================
        tools = ToolRegistry.default(workspace, settings, record=session.record, allow_shell=args.allow_shell)
        system_prompt = build_prompt(workspace, model=settings.model, tools=tools)
        session.update_system_prompt(system_prompt)  # 更新 session 的系统提示词

        terminal.session(session.path)
        terminal.system_prompt(session.messages[0].content or "")

        # ==============================
        # 阶段 4：初始化模型客户端与 Agent
        # ==============================
        with OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,  # OpenAI 库自带请求重试
        ) as client:
            # 获取模型的上下文长度
            terminal.context_window = discover_context_window(client, settings.model, workspace / STATE_DIRECTORY) or settings.context_window

            # 自动压缩必须要有上下文窗口参数，否则无法计算上下文压力
            if settings.auto_compact and terminal.context_window is None:
                terminal.report("compaction", "Auto compaction needs --context-window or XSH_CONTEXT_WINDOW; /compact remains available.")

            # 准备 Agent
            model = OpenAIModel(client, settings.model, settings.max_tokens)
            agent = Agent(
                model=model,
                session=session,
                tools=tools,
                max_steps=settings.max_steps,
                report=terminal.report,
                compactor=Compactor(
                    model, context_window=terminal.context_window, auto=settings.auto_compact,
                    threshold=settings.compact_threshold, retain_ratio=settings.compact_retain_ratio,
                    max_tokens=settings.compact_max_tokens, report=terminal.report,
                ),
            )

            # ========================
            # 阶段 6：命令解析和正式运行
            # ========================
            def run(prompt: str) -> int | None:
                """统一处理命令和普通输入，返回 None 表示退出交互循环。"""
                match prompt.strip():
                    case "":
                        return 0
                    case "/quit" | "/exit" | "/q":
                        return None
                    case "/list" | "/history" | "/h":
                        terminal.history(session)
                        return 0
                    case "/compact" | "/z":
                        try:
                            if agent.compact() is None:
                                terminal.report("compaction", "No history available to compact.")
                            return 0
                        except KeyboardInterrupt:
                            terminal.error("Compaction interrupted; history preserved.")
                            return 130
                        except Exception as error:
                            terminal.error(f"Compaction failed: {type(error).__name__}: {error}")
                            return 1
                # 单轮运行
                outcome = agent.run(prompt)
                terminal.outcome(outcome)
                if outcome.status == "completed":
                    return 0
                elif outcome.status == "cancelled":
                    return 130
                else:
                    return 1

            # ========================
            # 阶段 5：进入单轮或多轮运行
            # ========================
            # 命令行单轮运行
            if args.prompt is not None:
                status = run(args.prompt)
                return 0 if status is None else status

            # 交互式多轮运行
            terminal.intro()
            while True:  # ※ Agent Turn 循环
                try:
                    prompt = terminal.prompt()  # 取得用户输入
                except (EOFError, KeyboardInterrupt):
                    terminal.newline()
                    return 0
                if run(prompt) is None:
                    return 0

    except ValidationError as error:  # 配置验证失败
        for detail in error.errors(include_input=False, include_url=False):
            terminal.error(f"Configuration: {'.'.join(map(str, detail['loc']))}: {detail['msg']}")
        return 2

    except (OSError, ValueError, KeyError) as error:
        terminal.error(f"xsh: {error}")
        return 2
