"""E2E tests for DeepSeek preflight and Mock independence."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tracemind.cli.main import app

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)
REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
MOCK_SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "mock_responses.json"
runner = CliRunner()


def _base_args(output_dir: Path) -> list[str]:
    return [
        "diagnose",
        "--log",
        str(LOG_FIXTURE),
        "--repo",
        str(REPO_FIXTURE),
        "--service",
        "order-service",
        "--output-dir",
        str(output_dir),
    ]


def test_missing_deepseek_key_exits_before_run_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    output_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [*_base_args(output_dir), "--provider", "deepseek"],
    )

    assert result.exit_code == 2, result.output
    assert "DEEPSEEK_API_KEY" in result.output
    assert ".env" in result.output
    assert not output_dir.exists()


def test_mock_does_not_require_deepseek_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    output_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [
            *_base_args(output_dir),
            "--provider",
            "mock",
            "--mock-script",
            str(MOCK_SCRIPT),
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = next(path for path in output_dir.iterdir() if path.is_dir())
    run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_data["llm"]["provider"] == "mock"
    assert "DEEPSEEK_API_KEY" not in (run_dir / "run.json").read_text(
        encoding="utf-8"
    )
