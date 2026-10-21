"""Opt-in live DeepSeek tests; skipped unless --run-live + env gate + key."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tracemind.cli.main import app
from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.llm.messages import LLMResponse, Message

pytestmark = pytest.mark.live

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)
REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
runner = CliRunner()


def test_live_adapter_returns_usage() -> None:
    provider = DeepSeekProvider(max_tokens=64, timeout=60)

    response = provider.complete(
        [Message(role="user", content="Reply with the single word ready.")],
        [],
    )

    assert isinstance(response, LLMResponse)
    assert response.content.strip() or response.tool_calls
    assert response.attempts >= 1
    assert response.usage is not None
    assert response.usage.input_tokens is not None
    assert response.usage.output_tokens is not None


def test_live_cli_completes_fixture(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    result = runner.invoke(
        app,
        [
            "diagnose",
            "--log",
            str(LOG_FIXTURE),
            "--repo",
            str(REPO_FIXTURE),
            "--service",
            "order-service",
            "--provider",
            "deepseek",
            "--output-dir",
            str(output_dir),
            "--max-iterations",
            "4",
            "--max-tool-calls",
            "6",
            "--llm-max-tokens",
            "800",
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = next(path for path in output_dir.iterdir() if path.is_dir())
    assert {
        "run.json",
        "events.jsonl",
        "audit.jsonl",
        "report.md",
        "report.json",
    } <= {path.name for path in run_dir.iterdir()}

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "0.2"
    assert report["status"] in {"confirmed", "probable"}
    assert report["validation"]["citations_valid"] is True
    assert report["validation"]["evidence_ids_valid"] is True
    kinds = {
        source["kind"]
        for source in report["sources"]
        if isinstance(source, dict) and "kind" in source
    }
    assert {"stack_frame", "log_event", "source_code"} <= kinds
    assert report["tool_calls"]
    assert report["llm_usage"]["calls"] >= 1
    assert report["llm_usage"]["input_tokens"] is not None

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    assert api_key
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "DEEPSEEK_API_KEY" not in text
        assert "sk-" not in text
        assert api_key not in text
