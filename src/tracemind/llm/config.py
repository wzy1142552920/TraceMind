"""LLM configuration, .env loading, and API-key preflight."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field, ValidationError

from tracemind.core.errors import LLMConfigError

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"


class LLMSettings(BaseModel):
    """Validated LLM settings with no credential value in the model."""

    model: str = Field(default=DEFAULT_MODEL, min_length=1)
    base_url: str = Field(default=DEFAULT_BASE_URL, min_length=1)
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_tokens: int = Field(default=4000, gt=0)
    max_retries: int = Field(default=2, ge=0, le=2)
    repair_attempts: int = Field(default=2, ge=0, le=5)

    def public_config(self) -> dict[str, Any]:
        """Return sanitized settings suitable for run.json/reporting."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "repair_attempts": self.repair_attempts,
        }


def load_project_env(dotenv_path: Path | str | None = None) -> Path | None:
    """Load .env without overriding real environment variables."""
    if dotenv_path is None:
        found = find_dotenv(usecwd=True)
        if not found:
            return None
        path = Path(found)
    else:
        path = Path(dotenv_path)

    if not path.is_file():
        raise LLMConfigError(f"env file not found: {path}")
    load_dotenv(dotenv_path=path, override=False)
    return path


def resolve_settings(
    env: Mapping[str, str] | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
    repair_attempts: int | None = None,
) -> LLMSettings:
    """Resolve CLI > environment > defaults into validated settings."""
    source = os.environ if env is None else env

    try:
        return LLMSettings(
            model=_pick_text(model, source.get("TRACEMIND_LLM_MODEL"), DEFAULT_MODEL),
            base_url=_pick_text(
                base_url,
                source.get("TRACEMIND_LLM_BASE_URL"),
                DEFAULT_BASE_URL,
            ),
            timeout_seconds=_pick_float(
                timeout,
                source.get("TRACEMIND_LLM_TIMEOUT"),
                60.0,
                "TRACEMIND_LLM_TIMEOUT",
            ),
            max_tokens=_pick_int(
                max_tokens,
                source.get("TRACEMIND_LLM_MAX_TOKENS"),
                4000,
                "TRACEMIND_LLM_MAX_TOKENS",
            ),
            max_retries=_pick_int(
                max_retries,
                source.get("TRACEMIND_LLM_MAX_RETRIES"),
                2,
                "TRACEMIND_LLM_MAX_RETRIES",
            ),
            repair_attempts=_pick_int(
                repair_attempts,
                source.get("TRACEMIND_MAX_REPAIR_ATTEMPTS"),
                2,
                "TRACEMIND_MAX_REPAIR_ATTEMPTS",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise LLMConfigError(f"invalid LLM configuration: {exc}") from exc


def require_api_key(
    settings: LLMSettings,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return the API key or raise a clear, non-secret error."""
    source = os.environ if env is None else env
    key = source.get(settings.api_key_env, "").strip()
    if not key:
        raise LLMConfigError(
            f"{settings.api_key_env} is not set. "
            "Put it in .env or export it, or use --provider mock."
        )
    return key


def _pick_text(cli_value: str | None, env_value: str | None, default: str) -> str:
    if cli_value is not None:
        return cli_value
    if env_value is not None and env_value.strip():
        return env_value.strip()
    return default


def _pick_int(
    cli_value: int | None,
    env_value: str | None,
    default: int,
    env_name: str,
) -> int:
    if cli_value is not None:
        return cli_value
    if env_value is None or not env_value.strip():
        return default
    try:
        return int(env_value)
    except ValueError as exc:
        raise LLMConfigError(
            f"{env_name} must be an integer, got {env_value!r}"
        ) from exc


def _pick_float(
    cli_value: float | None,
    env_value: str | None,
    default: float,
    env_name: str,
) -> float:
    if cli_value is not None:
        return cli_value
    if env_value is None or not env_value.strip():
        return default
    try:
        return float(env_value)
    except ValueError as exc:
        raise LLMConfigError(
            f"{env_name} must be a number, got {env_value!r}"
        ) from exc
