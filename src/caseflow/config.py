"""Runtime configuration: environment variables + CLI overrides, validated at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

ProviderName = Literal["mock", "openai"]

# The single place a default model is named. Override with OPENAI_MODEL.
# gpt-5.5 is the model used throughout the official openai-python 3.x README and
# supports Structured Outputs through the Responses API.
DEFAULT_OPENAI_MODEL = "gpt-5.5"


class ConfigError(Exception):
    """Invalid or incomplete configuration. Fatal at startup."""


@dataclass(frozen=True)
class Settings:
    provider: ProviderName = "mock"
    input_dir: Path = Path("data")
    output_dir: Path = Path("output")
    log_dir: Path = Path("logs")
    recursive: bool = False
    openai_api_key: str | None = field(default=None, repr=False)
    openai_model: str = DEFAULT_OPENAI_MODEL
    company_name: str = "Brightlane Home Supplies"
    batch_concurrency: int = 4
    llm_concurrency: int = 3
    request_timeout_seconds: float = 60.0
    max_retries: int = 3
    max_file_bytes: int = 10 * 1024 * 1024
    max_document_chars: int = 60_000
    log_level: str = "INFO"

    def public_dict(self) -> dict[str, Any]:
        """Settings safe to write to the manifest (never includes secrets)."""
        return {
            "provider": self.provider,
            "model": self.model_label,
            "input_dir": self.input_dir.as_posix(),
            "recursive": self.recursive,
            "company_name": self.company_name,
            "batch_concurrency": self.batch_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_retries": self.max_retries,
            "max_file_bytes": self.max_file_bytes,
            "max_document_chars": self.max_document_chars,
        }

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"

    @property
    def model_label(self) -> str:
        return "mock-fixtures" if self.is_mock else self.openai_model


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def load_settings(overrides: dict[str, Any] | None = None, *, dotenv: bool = True) -> Settings:
    """Build Settings from .env / environment, apply CLI overrides, then validate."""
    if dotenv:
        load_dotenv(override=False)
    base = Settings()
    settings = Settings(
        openai_api_key=(os.getenv("OPENAI_API_KEY") or None),
        openai_model=(os.getenv("OPENAI_MODEL") or base.openai_model).strip(),
        company_name=(os.getenv("COMPANY_NAME") or base.company_name).strip(),
        batch_concurrency=_env_int("BATCH_CONCURRENCY", base.batch_concurrency),
        llm_concurrency=_env_int("LLM_CONCURRENCY", base.llm_concurrency),
        request_timeout_seconds=_env_float("REQUEST_TIMEOUT_SECONDS", base.request_timeout_seconds),
        max_retries=_env_int("MAX_RETRIES", base.max_retries),
        max_file_bytes=_env_int("MAX_FILE_BYTES", base.max_file_bytes),
        max_document_chars=_env_int("MAX_DOCUMENT_CHARS", base.max_document_chars),
        log_level=(os.getenv("LOG_LEVEL") or base.log_level).upper(),
    )
    clean = {k: v for k, v in (overrides or {}).items() if v is not None}
    if clean:
        settings = replace(settings, **clean)
    validate_settings(settings)
    return settings


def validate_settings(s: Settings) -> None:
    if s.provider not in ("mock", "openai"):
        raise ConfigError(f"Unknown provider {s.provider!r}; use 'mock' or 'openai'.")
    if s.provider == "openai":
        if not s.openai_api_key:
            raise ConfigError(
                "OPENAI_API_KEY is not set. Real mode requires an API key "
                "(add it to .env), or run with --provider mock."
            )
        if not s.openai_model:
            raise ConfigError("OPENAI_MODEL must not be empty in real mode.")
    for name in ("batch_concurrency", "llm_concurrency"):
        value = getattr(s, name)
        if not 1 <= value <= 64:
            raise ConfigError(f"{name.upper()} must be between 1 and 64, got {value}.")
    if not 0 <= s.max_retries <= 10:
        raise ConfigError(f"MAX_RETRIES must be between 0 and 10, got {s.max_retries}.")
    if s.request_timeout_seconds <= 0:
        raise ConfigError("REQUEST_TIMEOUT_SECONDS must be positive.")
    if s.max_file_bytes <= 0 or s.max_document_chars <= 0:
        raise ConfigError("MAX_FILE_BYTES and MAX_DOCUMENT_CHARS must be positive.")
    if not s.company_name:
        raise ConfigError("COMPANY_NAME must not be empty.")
    if s.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ConfigError(f"LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {s.log_level!r}.")
    if not s.input_dir.is_dir():
        raise ConfigError(f"Input folder not found: {s.input_dir}")
