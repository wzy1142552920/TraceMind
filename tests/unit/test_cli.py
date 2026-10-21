"""Smoke tests for the Typer CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from tracemind.cli.main import app

runner = CliRunner()


def test_help_lists_diagnose() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "diagnose" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "tracemind" in result.stdout.lower()


def test_diagnose_help_lists_options() -> None:
    result = runner.invoke(app, ["diagnose", "--help"])
    assert result.exit_code == 0
    for option in ("--log", "--repo", "--service", "--provider"):
        assert option in result.stdout
