"""Tests for the environment self-check (doctor)."""

from pathlib import Path

from xsh.config import Settings
from xsh.doctor import FAIL, OK, WARN, render, run_checks


def _settings(**overrides) -> Settings:
    values = {"base_url": "https://api.example/v1", "model": "m", "api_key": "k"}
    values.update(overrides)
    return Settings(**values)


def test_run_checks_reports_core_environment(tmp_path: Path) -> None:
    checks = run_checks(tmp_path, _settings(), allow_shell=False)
    by_name = {name: (status, detail) for name, status, detail in checks}
    assert by_name["workspace"][0] == OK
    assert by_name["model"][0] == OK
    assert by_name["shell"][0] == WARN
    assert by_name["permissions.json"][0] == OK  # 缺省视为可选


def test_run_checks_flags_invalid_config_json(tmp_path: Path) -> None:
    state = tmp_path / ".xsh"
    state.mkdir()
    (state / "permissions.json").write_text("{not json", encoding="utf-8")
    checks = run_checks(tmp_path, _settings(), allow_shell=True)
    by_name = {name: status for name, status, _ in checks}
    assert by_name["permissions.json"] == FAIL
    assert by_name["shell"] == OK


def test_render_summarizes_counts(tmp_path: Path) -> None:
    text = render(run_checks(tmp_path, _settings()))
    assert "[ok] workspace" in text
    assert "failure(s)" in text
