"""config.py - 配置类"""

import os
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator

from xsh.constants import (
    CONFIG_DEFAULT_MAX_RETRIES,
    CONFIG_DEFAULT_MAX_STEPS,
    CONFIG_DEFAULT_MAX_TOKENS,
    CONFIG_DEFAULT_REQUEST_TIMEOUT,
    CONFIG_MAX_RETRIES,
)


class Settings(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: SecretStr
    max_steps: int = Field(default=CONFIG_DEFAULT_MAX_STEPS, ge=1)
    max_tokens: int = Field(default=CONFIG_DEFAULT_MAX_TOKENS, ge=1)
    context_window: int | None = Field(default=None, ge=1)
    request_timeout: float = Field(default=CONFIG_DEFAULT_REQUEST_TIMEOUT, gt=0)
    max_retries: int = Field(default=CONFIG_DEFAULT_MAX_RETRIES, ge=0, le=CONFIG_MAX_RETRIES)

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("Expected an http(s) API base URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Use a base URL without credentials, query, or fragment")
        if url.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("Provide the base URL, without /chat/completions")
        return value.rstrip("/")

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        values = {
            name: os.environ[f"XSH_{name.upper()}"]
            for name in cls.model_fields
            if f"XSH_{name.upper()}" in os.environ
        }
        for name in ("base_url", "api_key", "model"):
            if name not in values and os.environ.get(f"OPENAI_{name.upper()}"):
                values[name] = os.environ[f"OPENAI_{name.upper()}"]
        values.update({key: value for key, value in overrides.items() if value is not None})
        if not values.get("api_key"):
            raise ValueError("Set XSH_API_KEY (or OPENAI_API_KEY) in the environment or .env")
        return cls.model_validate(values)
