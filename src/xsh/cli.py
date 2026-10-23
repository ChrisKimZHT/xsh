"""cli.py - 主函数，准备会话、工具、模型，创建 Agent 并运行，维护 Turn 循环"""

import argparse
import atexit
import json
import shutil
import signal
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from xsh.agent import Agent
from xsh.compaction import Compactor
from xsh.config import STATE_DIRECTORY, Settings
from xsh.hooks import Hooks
from xsh.maintenance import compact_session_file
from xsh.mcp import load_servers, start_clients
from xsh.memory import MemoryStore
from xsh.model import OpenAIModel, discover_context_window
from xsh.non_stop import NonStopTask, run_non_stop
from xsh.prompt import build_prompt
from xsh.readiness import build_record, new_boot_id, write_ready_file
from xsh.session import Session, usage_totals
from xsh.skills import SkillLibrary
from xsh.terminal import Terminal
from xsh.tools.base import ToolRegistry
from xsh.tools.mcp import build_mcp_tools
from xsh.tools.task import TaskTools
from xsh.tools.todo import format_todos
from xsh.transcript import export_transcript

_SESSION_DIRECTORY = Path(STATE_DIRECTORY) / "sessions"


def _handle_sigterm(signum: int, frame: object) -> None:
    """把 SIGTERM 转为 KeyboardInterrupt，复用 Ctrl+C 的收尾路径。

    这样外部监督脚本在需要强制停止时（C-c 无效后发送 SIGTERM），xsh 仍会
    修复未完成的工具调用并记录 turn_end，而不是被直接终止。
    """
    raise KeyboardInterrupt


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """从命令行参数与环境变量构造 Settings（命令行优先）。"""
    return Settings.from_env(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
        max_turns=args.max_turns,
        max_run_tokens=args.max_run_tokens,
        max_tokens=args.max_tokens,
        context_window=args.context_window,
        auto_compact=args.auto_compact,
        compact_threshold=args.compact_threshold,
        compact_retain_ratio=args.compact_retain_ratio,
        compact_max_tokens=args.compact_max_tokens,
        request_timeout=args.request_timeout,
        max_retries=args.max_retries,
    )


def maybe_compact_session(path: Path, threshold_mb: float) -> dict | None:
    """当会话文件超过阈值时离线压缩（opt-in；阈值 <= 0 表示关闭）。"""
    if threshold_mb <= 0 or not Path(path).is_file():
        return None
    if Path(path).stat().st_size <= int(threshold_mb * 1024 * 1024):
        return None
    return compact_session_file(Path(path), backup=True)


def resolve_session(value: Path, directory: Path) -> Path:
    """把会话名或路径解析为实际文件；名字支持在会话目录内按前缀匹配。"""
    candidate = Path(value)
    if candidate.is_file():
        return candidate.resolve()
    matches = [path for path in directory.glob("*.jsonl") if path.name == candidate.name or path.name.startswith(candidate.name)]
    if not matches:
        raise ValueError(f"Session not found: {value}")
    return max(matches, key=lambda path: path.stat().st_mtime_ns)


def fork_session(source: Path, directory: Path) -> Path:
    """把已有会话复制为新文件，返回新路径（原会话保持不变）。"""
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError(f"Session not found: {source}")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".jsonl")
    shutil.copyfile(source, target)
    return target


def list_sessions(directory: Path) -> list[tuple[float, int, str]]:
    """列出会话目录中的 JSONL 文件，按修改时间倒序返回 (mtime_ns, size, name)。"""
    if not directory.is_dir():
        return []
    entries: list[tuple[float, int, str]] = []
    for path in directory.glob("*.jsonl"):
        if path.is_file():
            stat = path.stat()
            entries.append((stat.st_mtime_ns, stat.st_size, path.name))
    entries.sort(reverse=True)
    return entries


def run_print_mode(args: argparse.Namespace) -> int:
    """无终端运行：执行给定 prompt（单轮或非停机）并把结果文本打印到 stdout。"""
    try:
        workspace = (args.workspace or Path.cwd()).resolve(strict=True)
        settings = _settings_from_args(args)
    except (ValidationError, OSError, ValueError) as error:
        print(f"xsh: {error}", file=sys.stderr)
        return 2

    memory_store = MemoryStore(workspace / STATE_DIRECTORY / "memory.md")
    skills_library = SkillLibrary(workspace / STATE_DIRECTORY / "skills")
    session_directory = workspace / _SESSION_DIRECTORY

    if args.fork is not None:
        session = Session.load(fork_session(args.fork, session_directory))
    elif args.resume is not None:
        if args.resume is True:
            entries = list_sessions(session_directory)
            if not entries:
                print(f"xsh: no sessions found in {session_directory}", file=sys.stderr)
                return 2
            resume_path = session_directory / entries[0][2]
        else:
            resume_path = resolve_session(args.resume, session_directory)
        session = Session.load(resume_path)
    else:
        filename = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".jsonl"
        session = Session.create(args.session or session_directory / filename, workspace, "")
    workspace = session.workspace

    tools = ToolRegistry.default(
        workspace, settings, record=session.record, allow_shell=args.allow_shell,
        current_todos=lambda: session.todos, memory_store=memory_store, skills_library=skills_library,
    )
    # --print 模式不启动子代理（保持无副作用）；仍注册工具以对齐提示词。
    tools.add(TaskTools(lambda prompts: "(subagents are unavailable in --print mode)").definitions())
    session.update_system_prompt(build_prompt(
        workspace, model=settings.model, tools=tools, non_stop_mode=args.non_stop_mode,
        memory=memory_store.render(), skills=skills_library.render_index(),
    ))

    with OpenAI(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
    ) as client:
        model = OpenAIModel(client, settings.model, settings.max_tokens)
        hooks = Hooks.load(workspace / STATE_DIRECTORY / "hooks.json", enabled=args.allow_shell)
        agent = Agent(model=model, session=session, tools=tools, max_steps=settings.max_steps, hooks=hooks)
        if args.non_stop_mode:
            task = NonStopTask.parse(args.prompt)
            session.non_stop_task = {"prompt": task.prompt, "continuation": task.continuation, "initial_turn": session.turn_count}
            session.record("non_stop_task", session.non_stop_task)
            return run_non_stop(
                agent, task, lambda result: print(result.text or result.error or "", flush=True),
                report=lambda kind, text: None, max_turns=settings.max_turns, budget_tokens=settings.max_run_tokens,
                usage=lambda: usage_totals(session.path)["total_tokens"],
            )
        result = agent.run(args.prompt)
        print(result.text or result.error or "", flush=True)
        return 0 if result.status == "completed" else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xsh", description="xsh - a deliberately small, single-agent harness")
    result.add_argument("prompt", nargs="?", help="Run one task; omit for interactive mode")
    result.add_argument("--workspace", type=Path, help="File-tool root; defaults to current directory")
    sessions = result.add_mutually_exclusive_group()
    sessions.add_argument("--session", type=Path, help="Create a new JSONL file at this path")
    sessions.add_argument("--resume", type=Path, nargs="?", const=True, help="Resume a JSONL session by path or name prefix; omit to resume the most recently modified default session")
    sessions.add_argument("--fork", type=Path, help="Copy an existing session to a new file and open the copy (branch without touching the original)")
    result.add_argument("--allow-shell", action="store_true", help="Enable unsandboxed shell execution")
    result.add_argument("--verbose", action="store_true", help="Show the system prompt, reasoning, and tool results on stdout")
    result.add_argument("--non-stop-mode", action="store_true", help="Continuously improve one task and automatically start another Turn until interrupted")
    result.add_argument("--ready-file", type=Path, help="Write a startup readiness record (boot id, PID, session) for external supervisors")
    result.add_argument("--version", action="version", version=f"%(prog)s {version('xsh-agent')}")
    result.add_argument("--list-sessions", action="store_true", help="List saved sessions for the workspace and exit")
    result.add_argument("--dump-prompt", action="store_true", help="Print the assembled system prompt and exit")
    result.add_argument("--list-tools", action="store_true", help="List the available tools and exit")
    result.add_argument("--compact-session", nargs="?", const=True, type=Path, help="Offline-compact a session file (default: most recent) and exit")
    result.add_argument("--print", action="store_true", dest="print_mode", help="Run a prompt without the interactive UI and print the result")

    # 覆盖 .env 配置的命令行参数
    result.add_argument("--base-url", help="OpenAI-compatible API base URL")
    result.add_argument("--model", help="Provider model identifier")
    result.add_argument("--api-key", help="Provider API key")
    result.add_argument("--max-steps", type=int)
    result.add_argument("--max-turns", type=int, help="Maximum number of Turns in non-stop mode before stopping")
    result.add_argument("--max-run-tokens", type=int, help="Token budget for a non-stop run before stopping")
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
    load_dotenv(Path.cwd() / ".env", override=False)

    # 仅在主线程可用时注册；失败不影响主流程。
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except (ValueError, OSError):
        pass

    # 列出会话不需要终端或模型；在创建 Terminal 之前处理，便于脚本化调用。
    if args.list_sessions:
        try:
            workspace = (args.workspace or Path.cwd()).resolve(strict=True)
        except OSError as error:
            print(f"xsh: {error}", file=sys.stderr)
            return 2
        entries = list_sessions(workspace / _SESSION_DIRECTORY)
        if not entries:
            print(f"No sessions found in {workspace / _SESSION_DIRECTORY}")
            return 0
        print(f"Sessions in {workspace / _SESSION_DIRECTORY} (newest first):")
        for mtime_ns, size, name in entries:
            when = datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {when}  {size:>10}  {name}")
        return 0

    # 离线压缩会话（不需要终端/模型）：默认压缩最近会话。
    if args.compact_session is not None:
        try:
            workspace = (args.workspace or Path.cwd()).resolve(strict=True)
            if args.compact_session is True:
                entries = list_sessions(workspace / _SESSION_DIRECTORY)
                if not entries:
                    raise ValueError(f"No sessions found in {workspace / _SESSION_DIRECTORY}")
                target = workspace / _SESSION_DIRECTORY / entries[0][2]
            else:
                target = Path(args.compact_session)
            print(json.dumps(compact_session_file(target, backup=True), ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError) as error:
            print(f"xsh: {error}", file=sys.stderr)
            return 2

    # 打印系统提示词 / 工具清单同样不需要终端；便于脚本化检查。
    if args.dump_prompt or args.list_tools:
        try:
            workspace = (args.workspace or Path.cwd()).resolve(strict=True)
            settings = _settings_from_args(args)
            memory_store = MemoryStore(workspace / STATE_DIRECTORY / "memory.md")
            skills_library = SkillLibrary(workspace / STATE_DIRECTORY / "skills")
            tools = ToolRegistry.default(workspace, settings, allow_shell=args.allow_shell, memory_store=memory_store, skills_library=skills_library)
            # 与真实运行保持一致：补上 task/task_status（这里用占位回调，仅用于 schema/提示词）。
            tools.add(TaskTools(lambda prompts: "", start=lambda prompts: "", status=lambda job_id: "").definitions())
            if args.list_tools:
                for name, tool in sorted(tools.tools.items()):
                    print(f"{name}\t{tool.description}")
            else:
                print(build_prompt(workspace, model=settings.model, tools=tools, non_stop_mode=args.non_stop_mode, memory=memory_store.render(), skills=skills_library.render_index()))
            return 0
        except (ValidationError, OSError, ValueError) as error:
            print(f"xsh: {error}", file=sys.stderr)
            return 2

    # 无终端模式：--print 直接执行 prompt 并打印结果，便于脚本化调用。
    if args.print_mode:
        if args.prompt is None:
            print("xsh: --print requires a prompt", file=sys.stderr)
            return 2
        return run_print_mode(args)

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
        settings = _settings_from_args(args)

        # ===========================
        # 阶段 2：准备会话（恢复/创建）
        # ===========================
        terminal.context_window = settings.context_window
        if args.fork is not None:
            # 从已有会话分叉：复制为新文件后按恢复处理，原会话不受影响。
            forked = fork_session(args.fork, workspace / _SESSION_DIRECTORY)
            session = Session.load(forked)
            workspace = session.workspace
            terminal.report("recovery", f"Forked {args.fork} -> {forked.name}")
        elif args.resume is not None:
            resume_path = args.resume
            if resume_path is not True:  # 允许按文件名或前缀在会话目录中定位
                resume_path = resolve_session(resume_path, workspace / _SESSION_DIRECTORY)
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
            stats = maybe_compact_session(resume_path, settings.session_compact_mb)
            if stats and stats.get("changed"):
                terminal.report(
                    "compaction",
                    f"Compacted session {resume_path.name}: {stats['before_bytes']} -> {stats['after_bytes']} bytes",
                )
            session = Session.load(resume_path)
            if args.workspace and workspace != session.workspace:
                raise ValueError("Resumed session belongs to a different workspace")
            workspace = session.workspace
            if session.recovered_tool_calls:
                terminal.report(
                    "recovery",
                    f"Recovered {session.recovered_tool_calls} interrupted tool call(s); "
                    "their results are marked in the session. Inspect external state before retrying a mutation.",
                )
        else:
            filename = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".jsonl"
            default_path = workspace / _SESSION_DIRECTORY / filename
            path = args.session or default_path
            session = Session.create(path, workspace, "")  # 此时系统提示词还没准备好，后续会更新

        # ==============================
        # 阶段 3：注册基础工具
        # ==============================
        memory_store = MemoryStore(workspace / STATE_DIRECTORY / "memory.md")
        skills_library = SkillLibrary(workspace / STATE_DIRECTORY / "skills")
        tools = ToolRegistry.default(
            workspace, settings, record=session.record, report=terminal.report, allow_shell=args.allow_shell,
            current_todos=lambda: session.todos, memory_store=memory_store, skills_library=skills_library,
        )
        non_stop_mode = args.non_stop_mode or session.non_stop_task is not None

        # ==============================
        # 阶段 4：初始化模型客户端与 Agent
        # ==============================
        with OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,  # OpenAI 库自带重试
        ) as client:
            # 获取模型的上下文长度
            terminal.context_window = discover_context_window(client, settings.model, workspace / STATE_DIRECTORY) or settings.context_window

            # 自动压缩必须要有上下文窗口参数，否则无法计算上下文压力
            if settings.auto_compact and terminal.context_window is None:
                terminal.report("compaction", "Auto compaction needs --context-window or XSH_CONTEXT_WINDOW; /compact remains available.")

            model = OpenAIModel(client, settings.model, settings.max_tokens)

            # 委派工具：子代理使用独立会话与不含 task 的工具集（避免递归、隔离上下文）。
            # 多个子任务并发执行；子代理不向终端输出，避免与主界面竞争。
            def run_subtask(prompts: Sequence[str]) -> str:
                def one(subtask: str) -> str:
                    directory = workspace / STATE_DIRECTORY / "subtasks"
                    sub_session = Session.create(directory / f"{uuid4().hex}.jsonl", workspace, "")
                    sub_tools = ToolRegistry.default(
                        workspace, settings, record=sub_session.record, allow_shell=args.allow_shell,
                        current_todos=lambda: sub_session.todos, memory_store=memory_store, skills_library=skills_library,
                    )
                    sub_session.update_system_prompt(build_prompt(
                        workspace, model=settings.model, tools=sub_tools, non_stop_mode=False,
                        memory=memory_store.render(), skills=skills_library.render_index(),
                    ))
                    sub_agent = Agent(model=model, session=sub_session, tools=sub_tools, max_steps=settings.max_steps, report=lambda kind, text: None)
                    result = sub_agent.run(subtask)
                    return f"Subagent: {result.status} ({result.steps} step(s))\n{result.text or result.error or '(no output)'}"

                if len(prompts) == 1:
                    reports = [one(prompts[0])]
                else:
                    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
                        reports = list(executor.map(one, prompts))
                terminal.report("subtask", f"{len(reports)} subagent(s) finished")
                if len(reports) == 1:
                    return reports[0]
                return "\n\n".join(f"[{index + 1}] {report}" for index, report in enumerate(reports))

            # 后台子任务：立即返回句柄，由 task_status 轮询。
            background_jobs: dict[str, dict] = {}
            jobs_lock = threading.Lock()

            def start_background(prompts: Sequence[str]) -> str:
                job_id = uuid4().hex[:8]
                with jobs_lock:
                    background_jobs[job_id] = {"status": "running", "result": ""}

                def worker() -> None:
                    try:
                        text = run_subtask(prompts)
                    except Exception as error:  # noqa: BLE001
                        text = f"error: {type(error).__name__}: {error}"
                    with jobs_lock:
                        background_jobs[job_id].update(status="done", result=text)

                threading.Thread(target=worker, daemon=True).start()
                return f'Background task {job_id} started. Poll with task_status(id="{job_id}").'

            def task_status(job_id: str) -> str:
                with jobs_lock:
                    snapshot = {key: dict(value) for key, value in background_jobs.items()}
                if not job_id:
                    if not snapshot:
                        return "No background tasks."
                    return "Background tasks:\n" + "\n".join(f"- {key}: {value['status']}" for key, value in snapshot.items())
                job = snapshot.get(job_id)
                if job is None:
                    return f"Unknown background task: {job_id}"
                if job["status"] == "running":
                    return f"Background task {job_id} is still running."
                return f"Background task {job_id} finished:\n{job['result']}"

            tools.add(TaskTools(run_subtask, start=start_background, status=task_status).definitions())

            # 外部 MCP 服务器（可选）：连接后把其工具接入本地工具集。
            mcp_servers = load_servers(workspace / STATE_DIRECTORY / "mcp.json")
            mcp_clients = start_clients(mcp_servers, workspace)
            if mcp_servers:
                terminal.report("subtask", f"MCP: {len(mcp_clients)}/{len(mcp_servers)} server(s) connected")
            if mcp_clients:
                atexit.register(lambda: [client.close() for client in mcp_clients])
                mcp_definitions = build_mcp_tools(mcp_clients)
                if mcp_definitions:
                    tools.add(mcp_definitions)

            # 系统提示词在工具集完整后构建，确保所有工具指导文案都进入提示词。
            system_prompt = build_prompt(workspace, model=settings.model, tools=tools, non_stop_mode=non_stop_mode, memory=memory_store.render(), skills=skills_library.render_index())
            session.update_system_prompt(system_prompt)
            terminal.session(session.path)
            terminal.system_prompt(session.messages[0].content or "")
            if session.todos:  # 恢复后先展示持久化的任务清单，便于续作
                terminal.report("todos", format_todos(session.todos))

            agent = Agent(
                model=model,
                session=session,
                tools=tools,
                max_steps=settings.max_steps,
                report=terminal.report,
                hooks=Hooks.load(workspace / STATE_DIRECTORY / "hooks.json", enabled=args.allow_shell),
                compactor=Compactor(
                    model, context_window=terminal.context_window, auto=settings.auto_compact,
                    threshold=settings.compact_threshold, retain_ratio=settings.compact_retain_ratio,
                    max_tokens=settings.compact_max_tokens, report=terminal.report,
                ),
            )

            # ==============================
            # 阶段 5：写入启动就绪信号
            # ==============================
            # 到这里配置、会话、工具和模型客户端都已就绪，可以开始执行 Turn。
            # 监督脚本据此判断本次启动成功，因此写入失败需要报告但不能中断主流程。
            boot_id = new_boot_id()
            if args.ready_file is not None:
                try:
                    record = build_record(
                        boot_id=boot_id,
                        resumed=args.resume is not None,
                        workspace=workspace,
                        session=session.path,
                        model=settings.model,
                        non_stop=non_stop_mode,
                        extra={"turns": session.turn_count, "messages": len(session.messages)},
                    )
                    write_ready_file(Path(args.ready_file).resolve(), record)
                except OSError as error:
                    terminal.error(f"xsh: could not write readiness file: {error}")
                else:
                    terminal.report("readiness", f"[xsh] ready pid={record['pid']} boot={boot_id} session={session.path}")

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
                    case "/todos" | "/todo":
                        terminal.report("todos", format_todos(session.todos) if session.todos else "No todos on record.")
                        return 0
                    case "/memory" | "/mem":
                        terminal.report("memory", memory_store.render() or "(no memory entries)")
                        return 0
                    case "/reload":
                        memory_store.reload()
                        session.update_system_prompt(build_prompt(
                            workspace, model=settings.model, tools=tools, non_stop_mode=non_stop_mode,
                            memory=memory_store.render(), skills=skills_library.render_index(),
                        ))
                        terminal.report("config", f"Reloaded memory and skills (memory={len(memory_store.entries)}, skills={len(skills_library.names())}).")
                        return 0
                    case "/skills":
                        terminal.report("skills", skills_library.render_index() or "(no skills)")
                        return 0
                    case "/tasks":
                        terminal.report("tasks", task_status(""))
                        return 0
                    case "/config" | "/settings":
                        lines = [
                            f"model: {settings.model}",
                            f"base_url: {settings.base_url}",
                            f"workspace: {workspace}",
                            f"context_window: {terminal.context_window}",
                            f"auto_compact: {settings.auto_compact}",
                            f"max_steps: {settings.max_steps}  max_turns: {settings.max_turns}  max_run_tokens: {settings.max_run_tokens}",
                            f"memory: {len(memory_store.entries)} entrie(s)  skills: {len(skills_library.names())}",
                            f"mcp servers: {len(mcp_clients)}  hooks: {'on' if agent.hooks else 'off'}",
                        ]
                        terminal.report("config", "\n".join(lines))
                        return 0
                    case "/usage" | "/u":
                        terminal.usage(session)
                        return 0
                    case "/stats":
                        terminal.stats(session)
                        return 0
                    case "/help" | "/?":
                        terminal.intro()
                        return 0
                    case "/sessions":
                        terminal.sessions(list_sessions(workspace / _SESSION_DIRECTORY))
                        return 0
                    case _ if prompt.strip().startswith("/export"):
                        target = prompt.strip()[len("/export"):].strip() or None
                        try:
                            path = export_transcript(session, workspace, target)
                        except (OSError, ValueError) as error:
                            terminal.error(f"Export failed: {error}")
                            return 1
                        terminal.report("export", f"Wrote transcript to {path}")
                        return 0
                    case _ if prompt.strip().startswith("/find"):
                        needle = prompt.strip()[len("/find"):].strip()
                        if not needle:
                            terminal.report("find", "Usage: /find <text>")
                        else:
                            terminal.find(session, needle)
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
            # 阶段 7：进入单轮或多轮运行
            # ========================
            if non_stop_mode:
                if args.prompt is not None:
                    task = NonStopTask.parse(args.prompt)
                elif session.non_stop_task is not None:
                    task = NonStopTask.from_stored(session.non_stop_task["prompt"], session.non_stop_task["continuation"])
                    return run_non_stop(
                        agent, task, terminal.outcome,
                        resumed=session.turn_count > session.non_stop_task["initial_turn"],
                        report=terminal.report,
                        max_turns=settings.max_turns,
                        budget_tokens=settings.max_run_tokens,
                        usage=lambda: usage_totals(session.path)["total_tokens"],
                    )
                else:
                    terminal.intro()
                    try:
                        task = NonStopTask.parse(terminal.prompt())
                    except (EOFError, KeyboardInterrupt):
                        terminal.newline()
                        return 130
                session.non_stop_task = {"prompt": task.prompt, "continuation": task.continuation, "initial_turn": session.turn_count}
                session.record("non_stop_task", session.non_stop_task)
                return run_non_stop(
                    agent, task, terminal.outcome, report=terminal.report, max_turns=settings.max_turns,
                    budget_tokens=settings.max_run_tokens, usage=lambda: usage_totals(session.path)["total_tokens"],
                )

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

    except KeyboardInterrupt:  # 启动阶段收到 Ctrl+C 或 SIGTERM：干净退出，不打印栈
        terminal.newline()
        return 130
