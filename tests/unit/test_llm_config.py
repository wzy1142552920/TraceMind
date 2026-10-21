"""Unit tests for LLM settings, .env loading, and API-key preflight."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tracemind.core.errors import LLMConfigError
from tracemind.llm.config import (
    LLMSettings,
    load_project_env,
    require_api_key,
    resolve_settings,
)


def test_default_settings() -> None:
    settings = resolve_settings({})

    assert settings.model == "deepseek-flash"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.timeout_seconds == 60.0
    assert settings.max_tokens == 4000
    assert settings.max_retries == 2
    assert settings.repair_attempts == 2
    assert "api_key" not in settings.public_config()
    assert "sk-" not in str(settings.public_config())


def test_env_settings() -> None:
    settings = resolve_settings(
        {
            "TRACEMIND_LLM_MODEL": "env-model",
            "TRACEMIND_LLM_BASE_URL": "https://env.example",
            "TRACEMIND_LLM_TIMEOUT": "12.5",
            "TRACEMIND_LLM_MAX_TOKENS": "512",
            "TRACEMIND_LLM_MAX_RETRIES": "1",
            "TRACEMIND_MAX_REPAIR_ATTEMPTS": "0",
        }
    )

    assert settings.model == "env-model"
    assert settings.base_url == "https://env.example"
    assert settings.timeout_seconds == 12.5
    assert settings.max_tokens == 512
    assert settings.max_retries == 1
    assert settings.repair_attempts == 0


def test_cli_overrides_env() -> None:
    settings = resolve_settings(
        {
            "TRACEMIND_LLM_MODEL": "env-model",
            "TRACEMIND_LLM_MAX_TOKENS": "512",
        },
        model="cli-model",
        max_tokens=128,
        timeout=5,
        max_retries=0,
        repair_attempts=1,
    )

    assert settings.model == "cli-model"
    assert settings.max_tokens == 128
    assert settings.timeout_seconds == 5
    assert settings.max_retries == 0
    assert settings.repair_attempts == 1


def test_invalid_numeric_env_raises_config_error() -> None:
    with pytest.raises(LLMConfigError):
        resolve_settings({"TRACEMIND_LLM_TIMEOUT": "not-a-number"})

    with pytest.raises(LLMConfigError):
        resolve_settings({"TRACEMIND_LLM_MAX_TOKENS": "0"})


def test_require_api_key() -> None:
    with pytest.raises(LLMConfigError) as exc_info:
        require_api_key(LLMSettings(), env={})
    assert "DEEPSEEK_API_KEY" in str(exc_info.value)
    assert ".env" in str(exc_info.value)

    assert (
        require_api_key(LLMSettings(), env={"DEEPSEEK_API_KEY": "  test-key  "})
        == "test-key"
    )


def test_dotenv_loads_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEMIND_LLM_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_KEY=from-dotenv\n"
        "TRACEMIND_LLM_MODEL=dotenv-model\n",
        encoding="utf-8",
    )

    loaded = load_project_env(env_file)

    assert loaded == env_file
    assert os.environ["DEEPSEEK_API_KEY"] == "from-dotenv"
    assert os.environ["TRACEMIND_LLM_MODEL"] == "dotenv-model"

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TRACEMIND_LLM_MODEL", raising=False)


def test_real_env_wins_over_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "real-key")
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=dotenv-key\n", encoding="utf-8")

    load_project_env(env_file)

    assert os.environ["DEEPSEEK_API_KEY"] == "real-key"


def test_missing_env_file_raises(tmp_path: Path) -> None:
    with pytest.raises(LLMConfigError):
        load_project_env(tmp_path / "missing.env")


def test_env_example_exists() -> None:
    root = Path(__file__).resolve().parents[2]
    example = root / ".env.example"

    assert example.is_file()
    assert "DEEPSEEK_API_KEY=" in example.read_text(encoding="utf-8")
