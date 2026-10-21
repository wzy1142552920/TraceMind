"""Pytest configuration for the TraceMind test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tracemind.core.errors import LLMConfigError  # noqa: E402
from tracemind.llm.config import load_project_env  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests marked live (requires network and DEEPSEEK_API_KEY).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.getoption("--run-live"):
        skip = pytest.mark.skip(reason="live tests require --run-live")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
        return

    try:
        load_project_env()
    except LLMConfigError:
        pass

    enabled = os.environ.get("TRACEMIND_LIVE_TESTS") == "1"
    has_key = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if enabled and has_key:
        return

    reason = (
        "live tests require TRACEMIND_LIVE_TESTS=1 and "
        "a non-empty DEEPSEEK_API_KEY (env or .env)"
    )
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
