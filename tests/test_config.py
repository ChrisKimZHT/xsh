"""Tests for configuration validation and environment loading."""

import pytest
from pydantic import ValidationError

from xsh.config import Settings


def _base() -> dict:
    return {"base_url": "https://example.com/v1", "model": "m", "api_key": "k"}


def test_valid_settings_roundtrip() -> None:
    settings = Settings(**_base())
    assert settings.base_url == "https://example.com/v1"
    assert settings.api_key.get_secret_value() == "k"
    assert settings.auto_compact is True


@pytest.mark.parametrize(
    "base_url",
    [
        "example.com/v1",  # 缺少 scheme
        "ftp://example.com/v1",  # 非 http(s)
        "https://user:pass@example.com/v1",  # 带凭据
        "https://example.com/v1?x=1",  # 带查询
        "https://example.com/chat/completions",  # 误填完整端点
    ],
)
def test_invalid_base_urls_rejected(base_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**_base(), "base_url": base_url})


def test_search_base_url_rejects_messages_suffix() -> None:
    with pytest.raises(ValidationError):
        Settings(**{**_base(), "search_base_url": "https://example.com/v1/messages"})


def test_compaction_ratio_must_be_below_threshold() -> None:
    with pytest.raises(ValidationError):
        Settings(**{**_base(), "compact_threshold": 0.5, "compact_retain_ratio": 0.6})


def test_from_env_reads_prefixed_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSH_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("XSH_MODEL", "env-model")
    monkeypatch.setenv("XSH_API_KEY", "env-key")
    monkeypatch.setenv("XSH_SEARCH_API_KEY", "")
    settings = Settings.from_env()
    assert settings.model == "env-model"
    assert settings.search_api_key is None  # 空字符串归一化为 None


def test_from_env_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSH_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("XSH_MODEL", "env-model")
    monkeypatch.delenv("XSH_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="XSH_API_KEY"):
        Settings.from_env()


def test_overrides_win_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XSH_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("XSH_MODEL", "env-model")
    monkeypatch.setenv("XSH_API_KEY", "env-key")
    settings = Settings.from_env(model="cli-model", max_steps=None)
    assert settings.model == "cli-model"
