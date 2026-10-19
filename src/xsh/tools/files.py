"""Small UTF-8 tools with workspace checks and read-before-write observations."""

import fnmatch
import hashlib
import os
import tempfile
from pathlib import Path

from pydantic import Field

from xsh.constants import (
    FILES_DEFAULT_GLOB,
    FILES_DEFAULT_READ_LIMIT,
    FILES_MAX_FILE_BYTES,
    FILES_MAX_READ_LIMIT,
    FILES_RESERVED_DIRECTORY,
    FILES_RESULT_LIMIT,
    FILES_SCAN_LIMIT,
    FILES_SKIP_DIRS,
)
from xsh.tools.base import Tool, ToolArgs, bounded


class ReadArgs(ToolArgs):
    file_path: str = Field(min_length=1, description="Path relative to the workspace or absolute.")
    offset: int = Field(default=1, ge=1, description="1-based first line.")
    limit: int = Field(default=FILES_DEFAULT_READ_LIMIT, ge=1, le=FILES_MAX_READ_LIMIT)


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


class GlobArgs(ToolArgs):
    pattern: str = Field(default=FILES_DEFAULT_GLOB, min_length=1, description="Relative glob, e.g. **/*.py.")


class GrepArgs(ToolArgs):
    pattern: str = Field(
        min_length=1, description="Literal text to find; NOT a regular expression."
    )
    glob: str = Field(default=FILES_DEFAULT_GLOB, min_length=1)


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
        if any(part.casefold() == FILES_RESERVED_DIRECTORY for part in relative.parts):
            raise ValueError(".xsh is reserved for harness session records")
        # Disallow Windows alternate data streams (drive colon is outside relative.parts).
        if os.name == "nt" and any(":" in part for part in relative.parts):
            raise ValueError("Alternate data streams are not supported")
        return path

    def _read_bytes(self, path: Path) -> bytes:
        if not path.is_file():
            raise ValueError("Expected an existing regular file")
        with path.open("rb") as file:
            data = file.read(FILES_MAX_FILE_BYTES + 1)
        if len(data) > FILES_MAX_FILE_BYTES:
            raise ValueError(f"File exceeds the {FILES_MAX_FILE_BYTES}-byte limit")
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
        if len(data) > FILES_MAX_FILE_BYTES:
            raise ValueError(f"Output exceeds {FILES_MAX_FILE_BYTES} bytes")
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

    def _paths(self, pattern: str):
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("Use a workspace-relative glob without '..'")
        visited = 0
        for directory, dirs, files in os.walk(self.workspace, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in FILES_SKIP_DIRS
                and not (Path(directory) / d).is_symlink()
                and not (Path(directory) / d).is_junction()
            )
            for name in sorted(files):
                visited += 1
                if visited > FILES_SCAN_LIMIT:
                    raise ValueError(
                        f"Scan limit reached ({FILES_SCAN_LIMIT} files); use a smaller workspace"
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
            if len(matches) == FILES_RESULT_LIMIT:
                return bounded(
                    "\n".join(matches) + "\n[Result limit reached; narrow the pattern.]"
                )
        return bounded("\n".join(matches) or "No files matched.")

    def grep(self, args: GrepArgs) -> str:
        matches = []
        skipped = 0
        for path, name in self._paths(args.glob):
            try:
                lines = self._read_bytes(path).decode("utf-8").splitlines()
            except (OSError, UnicodeError, ValueError):
                skipped += 1
                continue
            for number, line in enumerate(lines, 1):
                if args.pattern in line:
                    matches.append(f"{name}:{number}: {line}")
                    if len(matches) == FILES_RESULT_LIMIT:
                        return bounded(
                            "\n".join(matches) + "\n[Match limit reached; narrow the search.]"
                        )
        footer = f"\n[Skipped {skipped} unreadable, binary, or oversized files.]" if skipped else ""
        return bounded(("\n".join(matches) or "No matches.") + footer)

    def definitions(self) -> list[Tool]:
        return [
            Tool(
                "read",
                "Read a UTF-8 file with line numbers. Use offset and limit to page.",
                ReadArgs,
                self.read,
            ),
            Tool(
                "write",
                "Create or fully replace a UTF-8 file. Read existing files first.",
                WriteArgs,
                self.write,
            ),
            Tool(
                "edit",
                "Replace literal text in a previously read file; unique match by default.",
                EditArgs,
                self.edit,
            ),
            Tool(
                "glob",
                f"Find workspace file paths by glob. Returns at most {FILES_RESULT_LIMIT} paths.",
                GlobArgs,
                self.glob,
            ),
            Tool(
                "grep",
                f"Search UTF-8 files for literal text. Returns at most {FILES_RESULT_LIMIT} matching lines.",
                GrepArgs,
                self.grep,
            ),
        ]
