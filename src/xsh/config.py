"""config.py - 配置类"""

import os
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class Settings(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: SecretStr
    max_steps: int = Field(default=100000, ge=1)
    max_tokens: int = Field(default=65536, ge=1)
    context_window: int | None = Field(default=None, ge=1)
    auto_compact: bool = True
    compact_threshold: float = Field(default=0.8, gt=0, lt=1)
    compact_retain_ratio: float = Field(default=0.16, ge=0, lt=1)
    compact_max_tokens: int = Field(default=8192, ge=1)
    request_timeout: float = Field(default=600, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)

    @model_validator(mode="after")
    def check_compaction(self) -> "Settings":
        if self.compact_retain_ratio >= self.compact_threshold:
            raise ValueError("compact_retain_ratio must be less than compact_threshold")
        return self

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
        # 自动提取该类的所有字段，尝试从前缀 XSH_ 的大写环境变量中获取对应的值
        values = {
            name: os.environ[f"XSH_{name.upper()}"]
            for name in cls.model_fields
            if f"XSH_{name.upper()}" in os.environ
        }
        # 兼容 OpenAI 的环境变量，如果找不到 XSH_ 前缀就找 OPENAI_ 前缀
        for name in ("base_url", "api_key", "model"):
            if name not in values and os.environ.get(f"OPENAI_{name.upper()}"):
                values[name] = os.environ[f"OPENAI_{name.upper()}"]
        # 然后用命令行参数覆盖环境变量
        values.update({key: value for key, value in overrides.items() if value is not None})
        # 检查 API Key 是否存在，若不存在则抛出异常
        if not values.get("api_key"):
            raise ValueError("Set XSH_API_KEY (or OPENAI_API_KEY) in the environment or .env")
        return cls.model_validate(values)
