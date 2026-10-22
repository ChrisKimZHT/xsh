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
from xsh.config import Settings
from xsh.constants import (
    CLI_ENV_FILE,
    CLI_EXIT_COMMANDS,
    CLI_HISTORY_COMMANDS,
    CLI_INTERRUPT_EXIT_CODE,
    CLI_SESSION_DIRECTORY,
    CLI_SESSION_ID_LENGTH,
    CLI_SESSION_SUFFIX,
    CLI_SESSION_TIMESTAMP_FORMAT,
)
from xsh.model import OpenAIModel, discover_context_window
from xsh.prompt import build_prompt
from xsh.session import Session
from xsh.terminal import Terminal
from xsh.tools.base import ToolRegistry
from xsh.tools.files import FileTools
from xsh.tools.shell import shell_tool


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
    args = parser().parse_args(argv)
    load_dotenv(Path.cwd() / CLI_ENV_FILE, override=False)

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

        # 准备会话，恢复或创建
        terminal.context_window = settings.context_window
        if args.resume is not None:
            resume_path = args.resume
            if resume_path is True:  # 如果没有提供路径，则 resume 最近的会话
                session_directory = workspace / CLI_SESSION_DIRECTORY
                resume_path = None
                # 找最近修改的会话文件作为恢复路径
                latest_modified_time = -1
                for path in sorted(session_directory.glob(f"*{CLI_SESSION_SUFFIX}")):
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
            # 模型在重启后可能已更换，重新渲染系统提示词
            system_prompt = build_prompt(workspace, model=settings.model, allow_shell=args.allow_shell)
            session.update_system_prompt(system_prompt)
        else:
            default_path = workspace / Path(CLI_SESSION_DIRECTORY) / (datetime.now().strftime(CLI_SESSION_TIMESTAMP_FORMAT) + uuid4().hex[:CLI_SESSION_ID_LENGTH] + CLI_SESSION_SUFFIX)
            path = args.session or default_path
            system_prompt = build_prompt(workspace, model=settings.model, allow_shell=args.allow_shell)
            session = Session.create(path, workspace, system_prompt)
        terminal.session(session.path)
        terminal.system_prompt(session.messages[0].content or "")

        # 准备工具列表
        definitions = FileTools(workspace).definitions()
        if args.allow_shell:
            definitions.append(shell_tool(workspace))

        # 准备 OpenAI 客户端
        with OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,  # OpenAI 库自带请求重试
        ) as client:
            # 获取模型的上下文长度
            terminal.context_window = discover_context_window(client, settings.model) or settings.context_window

            # 自动压缩必须要有上下文窗口参数，否则无法计算上下文压力
            if settings.auto_compact and terminal.context_window is None:
                terminal.report("compaction", "Auto compaction needs --context-window or XSH_CONTEXT_WINDOW; /compact remains available.")

            # 准备 Agent
            model = OpenAIModel(client, settings.model, settings.max_tokens)
            agent = Agent(
                model=model,
                session=session,
                tools=ToolRegistry(definitions),
                max_steps=settings.max_steps,
                report=terminal.report,
                compactor=Compactor(
                    model, context_window=terminal.context_window, auto=settings.auto_compact,
                    threshold=settings.compact_threshold, retain_ratio=settings.compact_retain_ratio,
                    max_tokens=settings.compact_max_tokens, report=terminal.report,
                ),
            )

            def run(prompt: str) -> int:
                if prompt.strip() == "/compact":
                    try:
                        if agent.compact() is None:
                            terminal.report("compaction", "No history available to compact.")
                        return 0
                    except KeyboardInterrupt:
                        terminal.error("Compaction interrupted; history preserved.")
                        return CLI_INTERRUPT_EXIT_CODE
                    except Exception as error:
                        terminal.error(f"Compaction failed: {type(error).__name__}: {error}")
                        return 1
                # 单轮运行
                outcome = agent.run(prompt)
                terminal.outcome(outcome)
                if outcome.status == "completed":
                    return 0
                elif outcome.status == "cancelled":
                    return CLI_INTERRUPT_EXIT_CODE
                else:
                    return 1

            # 命令行指定 prompt 单轮运行
            if args.prompt is not None:
                return run(args.prompt)

            # 交互式多轮运行
            terminal.intro()
            while True:  # ※ Agent Turn 循环
                try:
                    prompt = terminal.prompt()  # 取得用户输入
                except (EOFError, KeyboardInterrupt):
                    terminal.newline()
                    return 0
                command = prompt.strip()
                if command in CLI_EXIT_COMMANDS:
                    return 0
                elif command in CLI_HISTORY_COMMANDS:
                    terminal.history(session)
                elif command:
                    run(prompt)  # 运行 Agent

    except ValidationError as error:  # 配置验证失败
        for detail in error.errors(include_input=False, include_url=False):
            terminal.error(f"Configuration: {'.'.join(map(str, detail['loc']))}: {detail['msg']}")
        return 2

    except (OSError, ValueError, KeyError) as error:
        terminal.error(f"xsh: {error}")
        return 2
