"""Tests for the optional tool permission policy."""

import json
from pathlib import Path

import pytest

from xsh.permissions import Permissions
from xsh.tools.files import FileTools, WriteArgs
from xsh.tools.shell import ShellArgs, ShellTools


def test_load_defaults_to_allow_all(tmp_path: Path) -> None:
    permissions = Permissions.load(tmp_path / "missing.json")
    assert permissions.path_allowed(tmp_path / "anything.txt")
    assert permissions.command_allowed("rm -rf /")


def test_load_parses_patterns(tmp_path: Path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text(json.dumps({"deny_paths": ["**/.env"], "deny_commands": ["rm -rf *"]}), encoding="utf-8")
    permissions = Permissions.load(path)
    assert not permissions.path_allowed(Path("/work/secret/.env"))
    assert permissions.path_allowed(Path("/work/src/app.py"))
    assert not permissions.command_allowed("rm -rf build")
    assert permissions.command_allowed("ls -la")


def test_file_tool_denies_matching_write(tmp_path: Path) -> None:
    permissions = Permissions(deny_paths=["*.secret"])
    tools = FileTools(tmp_path, permissions=permissions)
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.write(WriteArgs(file_path="key.secret", content="x"))
    # 非匹配路径不受影响
    tools.write(WriteArgs(file_path="ok.txt", content="x"))


def test_shell_tool_denies_matching_command(tmp_path: Path) -> None:
    permissions = Permissions(deny_commands=["rm -rf *"])
    tools = ShellTools(tmp_path, permissions=permissions)
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.execute(ShellArgs(command="rm -rf /"))
    assert "ok" in tools.execute(ShellArgs(command="echo ok"))
