"""Composition root: configuration, session, tools, model, then the agent."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from xsh.agent import Agent
from xsh.config import Settings
from xsh.model import OpenAIModel
from xsh.prompt import build_prompt
from xsh.session import Session
from xsh.tools.base import ToolRegistry
from xsh.tools.files import FileTools
from xsh.tools.shell import shell_tool


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="xsh - a small coding agent for learning")
    result.add_argument("prompt", nargs="?", help="Run one task; omit for interactive mode")
    result.add_argument("--workspace", type=Path, help="File-tool root; defaults to current directory")
    sessions = result.add_mutually_exclusive_group()
    sessions.add_argument("--session", type=Path, help="Create a new JSONL file at this path")
    sessions.add_argument("--resume", type=Path, help="Resume an existing JSONL session")
    result.add_argument("--allow-shell", action="store_true", help="Enable unsandboxed shell execution")
    result.add_argument("--verbose", action="store_true", help="Print tool results to stderr")
    result.add_argument("--show-prompt", action="store_true", help="Print a fresh system prompt and exit")

    # can override .env values
    result.add_argument("--base-url", help="OpenAI-compatible API base URL")
    result.add_argument("--model", help="Provider model identifier")
    result.add_argument("--api-key", help="Provider API key")
    result.add_argument("--max-steps", type=int)
    result.add_argument("--max-tokens", type=int, help="Maximum output tokens per model request")
    result.add_argument("--request-timeout", type=float, help="API request timeout in seconds")
    result.add_argument("--max-retries", type=int, help="Maximum API request retries")
    return result


def main(argv: list[str] | None = None) -> int:
    # load configuration
    args = parser().parse_args(argv)
    load_dotenv(Path.cwd() / ".env", override=False)

    try:
        workspace = (args.workspace or Path.cwd()).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Workspace must be a directory")

        if args.show_prompt:
            print(build_prompt(workspace, allow_shell=args.allow_shell))
            return 0

        # override .env values with command-line arguments
        settings = Settings.from_env(
            base_url=args.base_url,
            model=args.model,
            api_key=args.api_key,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            request_timeout=args.request_timeout,
            max_retries=args.max_retries,
        )

        # prepare session (resume or create)
        if args.resume:
            session = Session.load(args.resume)
            if args.workspace and workspace != session.workspace:
                raise ValueError("Resumed session belongs to a different workspace")
            workspace = session.workspace
        else:
            default_path = workspace / ".xsh" / "sessions" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".jsonl")
            path = args.session or default_path
            session = Session.create(path, workspace, build_prompt(workspace, allow_shell=args.allow_shell),)
        print(f"Session: {session.path}", file=sys.stderr)

        # prepare tool list
        definitions = FileTools(workspace).definitions()
        if args.allow_shell:
            definitions.append(shell_tool(workspace))

        # print function
        def report(kind: str, text: str) -> None:
            if kind == "assistant":
                print(text, flush=True)
            elif kind == "tool_result":
                if args.verbose:
                    print(text, file=sys.stderr)
            else:
                print(f"[{kind}: {text}]", file=sys.stderr, flush=True)

        # prepare model and agent
        with OpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        ) as client:
            agent = Agent(
                model=OpenAIModel(client, settings.model, settings.max_tokens),
                session=session,
                tools=ToolRegistry(definitions),
                max_steps=settings.max_steps,
                report=report,
            )

            def run(prompt: str) -> int:
                outcome = agent.run(prompt)
                print(f"[{outcome.status}; steps={outcome.steps}]", file=sys.stderr)
                if outcome.error:
                    print(outcome.error, file=sys.stderr)
                return (
                    0
                    if outcome.status == "completed"
                    else 130
                    if outcome.status == "cancelled"
                    else 1
                )

            # run a single prompt
            if args.prompt is not None:
                return run(args.prompt)

            # interactive mode
            print(
                "Enter a task; /history shows messages, /exit quits. Ctrl+C interrupts a turn.",
                file=sys.stderr,
            )

            # agent round loop
            while True:
                try:
                    prompt = input("\nxsh> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0
                if prompt in {"/exit", "/quit"}:
                    return 0
                if prompt == "/history":
                    for message in session.messages:
                        if message.role != "system":
                            print(f"[{message.role}] {message.content or ''}")
                            for call in message.tool_calls:
                                print(f"  {call.name}({call.arguments})")
                elif prompt:
                    run(prompt)

    except ValidationError as error:
        for detail in error.errors(include_input=False, include_url=False):
            print(f"Configuration: {'.'.join(map(str, detail['loc']))}: {detail['msg']}", file=sys.stderr)
        return 2

    except (OSError, ValueError, KeyError) as error:
        print(f"xsh: {error}", file=sys.stderr)
        return 2
