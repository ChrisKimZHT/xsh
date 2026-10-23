"""Tests for the optional tool permission policy."""

import json
from pathlib import Path

import pytest

from xsh.config import Settings
from xsh.messages import ToolCall
from xsh.permissions import Permissions
from xsh.tools.base import ToolRegistry
from xsh.tools.files import FileTools, GlobArgs, GrepArgs, ReadArgs, WriteArgs
from xsh.tools.shell import ShellArgs, ShellTools


def test_load_defaults_to_allow_all(tmp_path: Path) -> None:
    permissions = Permissions.load(tmp_path / "missing.json")
    assert permissions.path_allowed(tmp_path / "anything.txt")
    assert permissions.command_allowed("rm -rf /")
    assert permissions.summary() == "0 path pattern(s), 0 command pattern(s), 0 url pattern(s)"


def test_load_parses_patterns(tmp_path: Path) -> None:
    path = tmp_path / "permissions.json"
    path.write_text(json.dumps({"deny_paths": ["**/.env"], "deny_commands": ["rm -rf *"]}), encoding="utf-8")
    permissions = Permissions.load(path)
    assert not permissions.path_allowed(Path("/work/secret/.env"))
    assert permissions.path_allowed(Path("/work/src/app.py"))
    assert not permissions.command_allowed("rm -rf build")
    assert permissions.command_allowed("ls -la")


def test_file_tool_denies_matching_write_and_read(tmp_path: Path) -> None:
    permissions = Permissions(deny_paths=["*.secret"])
    tools = FileTools(tmp_path, permissions=permissions)
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.write(WriteArgs(file_path="key.secret", content="x"))
    (tmp_path / "key.secret").write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.read(ReadArgs(file_path="key.secret"))
    # 非匹配路径不受影响
    tools.write(WriteArgs(file_path="ok.txt", content="x"))


def test_glob_and_grep_skip_denied_paths(tmp_path: Path) -> None:
    (tmp_path / "key.secret").write_text("token=abc", encoding="utf-8")
    (tmp_path / "app.py").write_text("token=abc", encoding="utf-8")
    tools = FileTools(tmp_path, permissions=Permissions(deny_paths=["*.secret"]))

    assert "key.secret" not in tools.glob(GlobArgs(pattern="*"))
    assert "app.py" in tools.glob(GlobArgs(pattern="*"))
    grep_out = tools.grep(GrepArgs(pattern="token"))
    assert "key.secret" not in grep_out
    assert "app.py" in grep_out


def test_shell_tool_denies_matching_command(tmp_path: Path) -> None:
    permissions = Permissions(deny_commands=["rm -rf *"])
    tools = ShellTools(tmp_path, permissions=permissions)
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.execute(ShellArgs(command="rm -rf /"))
    assert "ok" in tools.execute(ShellArgs(command="echo ok"))


def test_registry_wires_permissions(tmp_path: Path) -> None:
    settings = Settings(base_url="https://api.example/v1", model="m", api_key="k")
    registry = ToolRegistry.default(tmp_path, settings, permissions=Permissions(deny_paths=["*.secret"]))
    call = ToolCall(id="1", name="write", arguments=json.dumps({"file_path": "a.secret", "content": "x"}))
    assert "denied by the permission policy" in registry.execute(call).content


def test_url_permission_filters_search_and_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    from xsh.tools import web as web_module
    from xsh.tools.web import FetchArgs, SearchArgs, WebTools

    settings = Settings(base_url="https://api.example/v1", model="m", api_key="k")
    permissions = Permissions(deny_urls=["http://blocked.test/*"])
    monkeypatch.setattr(
        WebTools, "_search",
        lambda self, body: [{"url": "http://blocked.test/a", "title": "B"}, {"url": "http://ok.test/a", "title": "O"}],
    )
    tools = WebTools(settings, permissions=permissions)
    out = tools.search(SearchArgs(queries=["q"]))
    assert "blocked.test" not in out and "ok.test" in out

    monkeypatch.setattr(web_module, "_fetch_page", lambda value: (value, 200, "text", "body", False))
    with pytest.raises(ValueError, match="denied by the permission policy"):
        tools.fetch(FetchArgs(url="http://blocked.test/a"))
    assert "body" in tools.fetch(FetchArgs(url="http://ok.test/a"))
