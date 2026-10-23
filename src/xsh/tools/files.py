"""Small UTF-8 tools with workspace checks and read-before-write observations."""

import fnmatch
import hashlib
import os
import re
import tempfile
from pathlib import Path

from pydantic import Field

from xsh.config import STATE_DIRECTORY
from xsh.prompt import PromptSection
from xsh.tools.base import Tool, ToolArgs, bounded

_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_READ_LIMIT = 2000
_SCAN_LIMIT = 100_000
_RESULT_LIMIT = 1000
_SKIP_DIRS = frozenset({".git", STATE_DIRECTORY, ".venv", ".conda", "node_modules", "__pycache__"})


class ReadArgs(ToolArgs):
    file_path: str = Field(min_length=1, description="Path relative to the workspace or absolute.")
    offset: int = Field(default=1, ge=1, description="1-based first line.")
    limit: int = Field(default=500, ge=1, le=_MAX_READ_LIMIT)


class WriteArgs(ToolArgs):
    file_path: str = Field(min_length=1)
    content: str = Field(description="Complete UTF-8 file content.")


class EditArgs(ToolArgs):
    file_path: str = Field(min_length=1)
    old_string: str = Field(
        min_length=1, description="Exact literal text, without read line numbers."
    )
    new_string: str
    replace_all: bool = False


class EditOperation(ToolArgs):
    old_string: str = Field(min_length=1, description="Exact literal text to replace.")
    new_string: str
    replace_all: bool = False


class MultiEditArgs(ToolArgs):
    file_path: str = Field(min_length=1)
    edits: list[EditOperation] = Field(min_length=1, max_length=50, description="Edits applied in order to one file.")


class GlobArgs(ToolArgs):
    pattern: str = Field(default="*", min_length=1, description="Relative glob, e.g. **/*.py.")


class GrepArgs(ToolArgs):
    pattern: str = Field(
        min_length=1, description="Text to find. Literal by default; set regex=true to use a regular expression."
    )
    glob: str = Field(default="*", min_length=1)
    regex: bool = Field(default=False, description="Treat the pattern as a Python regular expression.")
    ignore_case: bool = Field(default=False, description="Case-insensitive matching.")
    context: int = Field(default=0, ge=0, le=3, description="Lines of context to show before and after each match.")


_FILE_GUIDANCE = (
    'File paths are relative to the workspace unless absolute. File tools only operate inside that workspace, '
    'and .xsh is reserved for harness session records. A file-tool access restriction is policy, not a command '
    'bug; do not use shell commands to bypass it.'
)


class FileTools:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be a directory")
        self.observed: dict[Path, str] = {}

    def resolve(self, name: str) -> Path:
        if not name.strip():
            raise ValueError("Path must not be blank")
        path = (self.workspace / name).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError("Path is outside the workspace")
        relative = path.relative_to(self.workspace)
        if any(part.casefold() == STATE_DIRECTORY for part in relative.parts):
            raise ValueError(f"{STATE_DIRECTORY} is reserved for harness session records")
        # Disallow Windows alternate data streams (drive colon is outside relative.parts).
        if os.name == "nt" and any(":" in part for part in relative.parts):
            raise ValueError("Alternate data streams are not supported")
        return path

    def _read_bytes(self, path: Path) -> bytes:
        if not path.is_file():
            raise ValueError("Expected an existing regular file")
        with path.open("rb") as file:
            data = file.read(_MAX_FILE_BYTES + 1)
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError(f"File exceeds the {_MAX_FILE_BYTES}-byte limit")
        if b"\0" in data:
            raise ValueError("Binary files are not supported")
        return data

    def read(self, args: ReadArgs) -> str:
        path = self.resolve(args.file_path)
        data = self._read_bytes(path)
        text = data.decode("utf-8")
        lines = text.splitlines()
        self.observed[path] = hashlib.sha256(data).hexdigest()
        selected = lines[args.offset - 1 : args.offset - 1 + args.limit]
        body = "\n".join(f"{number}: {line}" for number, line in enumerate(selected, args.offset))
        end = args.offset - 1 + len(selected)
        line_endings = "CRLF" if "\r\n" in text else "LF"
        footer = f"\n[Line endings: {line_endings}. Total lines: {len(lines)}."
        footer += f" Continue with offset={end + 1}.]" if end < len(lines) else "]"
        return bounded(f"{path.relative_to(self.workspace)}\n{body}{footer}")

    def _existing(self, path: Path) -> str:
        data = self._read_bytes(path)
        if self.observed.get(path) != hashlib.sha256(data).hexdigest():
            raise ValueError(
                "File is unread or changed since observation. Read it again before editing."
            )
        return data.decode("utf-8")

    def _save(self, path: Path, text: str) -> None:
        data = text.encode("utf-8")
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError(f"Output exceeds {_MAX_FILE_BYTES} bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically so an interrupted write does not leave a half-written target.
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        try:
            if path.exists():
                temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        self.observed[path] = hashlib.sha256(data).hexdigest()

    def write(self, args: WriteArgs) -> str:
        path = self.resolve(args.file_path)
        if path.exists():
            self._existing(path)
        self._save(path, args.content)
        return f"Wrote {path.relative_to(self.workspace)}"

    def edit(self, args: EditArgs) -> str:
        path = self.resolve(args.file_path)
        before = self._existing(path)
        if args.old_string == args.new_string:
            raise ValueError("old_string and new_string must differ")
        count = before.count(args.old_string)
        if count == 0:
            raise ValueError("old_string was not found; read the file and copy the exact text")
        if count != 1 and not args.replace_all:
            raise ValueError(f"Found {count} matches; provide more context or set replace_all=true")
        after = before.replace(args.old_string, args.new_string, -1 if args.replace_all else 1)
        self._save(path, after)
        replaced = count if args.replace_all else 1
        return f"Edited {path.relative_to(self.workspace)} ({replaced} match(es))"

    def multiedit(self, args: MultiEditArgs) -> str:
        """按顺序对同一文件应用多处编辑，只在全部成功时写入一次（原子）。"""
        path = self.resolve(args.file_path)
        text = self._existing(path)
        total = 0
        for operation in args.edits:
            if operation.old_string == operation.new_string:
                raise ValueError("old_string and new_string must differ")
            count = text.count(operation.old_string)
            if count == 0:
                raise ValueError(f"old_string was not found: {operation.old_string!r}")
            if count != 1 and not operation.replace_all:
                raise ValueError(f"Found {count} matches for {operation.old_string!r}; provide more context or set replace_all=true")
            text = text.replace(operation.old_string, operation.new_string, -1 if operation.replace_all else 1)
            total += count if operation.replace_all else 1
        self._save(path, text)
        return f"Edited {path.relative_to(self.workspace)} ({total} change(s) across {len(args.edits)} edit(s))"

    def _paths(self, pattern: str):
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("Use a workspace-relative glob without '..'")
        visited = 0
        for directory, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in _SKIP_DIRS
                and not (Path(directory) / d).is_symlink()
                and not (Path(directory) / d).is_junction()
            )
            for name in sorted(files):
                visited += 1
                if visited > _SCAN_LIMIT:
                    raise ValueError(
                        f"Scan limit reached ({_SCAN_LIMIT} files); use a smaller workspace"
                    )
                path = Path(directory) / name
                relative = path.relative_to(self.workspace)
                # A leading **/ also matches zero directories (files at the workspace root).
                patterns = (pattern, pattern.removeprefix("**/"))
                if any(
                    fnmatch.fnmatch(relative.as_posix(), p) or relative.match(p) for p in patterns
                ):
                    try:
                        resolved = self.resolve(str(relative))
                    except ValueError:
                        continue
                    if resolved.is_file():
                        yield resolved, relative.as_posix()

    def glob(self, args: GlobArgs) -> str:
        matches = []
        for _, name in self._paths(args.pattern):
            matches.append(name)
            if len(matches) == _RESULT_LIMIT:
                return bounded(
                    "\n".join(matches) + "\n[Result limit reached; narrow the pattern.]"
                )
        return bounded("\n".join(matches) or "No files matched.")

    def grep(self, args: GrepArgs) -> str:
        if args.regex:
            try:
                compiled = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
            except re.error as error:
                raise ValueError(f"Invalid regular expression: {error}") from None

            def hit(line: str) -> bool:
                return compiled.search(line) is not None
        else:
            needle = args.pattern.lower() if args.ignore_case else args.pattern

            def hit(line: str) -> bool:
                return needle in (line.lower() if args.ignore_case else line)

        matches: list[str] = []
        skipped = 0
        for path, name in self._paths(args.glob):
            try:
                lines = self._read_bytes(path).decode("utf-8").splitlines()
            except (OSError, UnicodeError, ValueError):
                skipped += 1
                continue
            hits = [number for number, line in enumerate(lines, 1) if hit(line)]
            if not hits:
                continue
            if args.context <= 0:
                rows = [(number, number in hits) for number in hits]
            else:
                wanted: set[int] = set()
                for number in hits:
                    wanted.update(range(max(1, number - args.context), min(len(lines), number + args.context) + 1))
                hit_set = set(hits)
                rows = [(number, number in hit_set) for number in sorted(wanted)]
            for number, is_match in rows:
                separator = ":" if is_match else "-"
                matches.append(f"{name}{separator}{number}{separator} {lines[number - 1]}")
                if len(matches) == _RESULT_LIMIT:
                    return bounded("\n".join(matches) + "\n[Match limit reached; narrow the search.]")
        footer = f"\n[Skipped {skipped} unreadable, binary, or oversized files.]" if skipped else ""
        return bounded(("\n".join(matches) or "No matches.") + footer)

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "read",
                "Read a UTF-8 file with line numbers. Use offset and limit to page.",
                ReadArgs,
                self.read,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance=(
                    'Use the read tool — not shell commands like cat — to inspect text files. Use offset and limit to continue '
                    'reading large files. Line numbers in read output are display metadata, not part of the file.'
                ),
            ),
            Tool(
                "write",
                "Create or fully replace a UTF-8 file. Read existing files first.",
                WriteArgs,
                self.write,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance='Read an existing file before overwriting it with write (the file tools require it) and prefer edit for targeted changes.',
            ),
            Tool(
                "edit",
                "Replace literal text in a previously read file; unique match by default.",
                EditArgs,
                self.edit,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance=(
                    'Read a file before editing it (the file tools require it), unless you just created or edited it in this '
                    'session. If a file changed since your last observation, read it again. Literal edits must match exactly, '
                    'including whitespace and line endings; provide enough surrounding text to identify a unique occurrence.'
                ),
            ),
            Tool(
                "multiedit",
                "Apply several literal edits to one previously read file in a single atomic write.",
                MultiEditArgs,
                self.multiedit,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance=(
                    'Use multiedit to make several changes to the same file in one call: edits are applied in order and the '
                    'file is written once, only if every edit matches. Read the file first; each old_string must match.'
                ),
            ),
            Tool(
                "glob",
                f"Find workspace file paths by glob. Returns at most {_RESULT_LIMIT} paths.",
                GlobArgs,
                self.glob,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance='Use the glob tool — not shell find — to discover files by path pattern.',
            ),
            Tool(
                "grep",
                f"Search UTF-8 files for text (literal by default; regex optional). Returns at most {_RESULT_LIMIT} matching lines.",
                GrepArgs,
                self.grep,
                prompt_sections=(PromptSection("files:policy", 200, _FILE_GUIDANCE),),
                guidance=(
                    'Use the grep tool — not shell grep or rg — to search file contents. The pattern is literal unless you set '
                    'regex=true; set ignore_case for case-insensitive matches and context>0 to show surrounding lines. '
                    'Use read on a matched file when you need more context.'
                ),
            ),
        ]
