"""Smoke tests for the package skeleton."""

from __future__ import annotations

import importlib

import pytest

import tracemind


def test_version_is_available() -> None:
    assert tracemind.__version__
    assert isinstance(tracemind.__version__, str)


@pytest.mark.parametrize(
    "package",
    [
        "tracemind.cli",
        "tracemind.core",
        "tracemind.log_analysis",
        "tracemind.indexing",
        "tracemind.tools",
        "tracemind.llm",
        "tracemind.diagnosis",
        "tracemind.workspace",
        "tracemind.observability",
        "tracemind.storage",
    ],
)
def test_subpackages_importable(package: str) -> None:
    assert importlib.import_module(package) is not None
