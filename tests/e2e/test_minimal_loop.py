"""End-to-end tests for the v0.1 CLI and run artifacts."""

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


def _invoke(
    output_dir: Path,
    mock_script: Path = MOCK_SCRIPT,
    extra: list[str] | None = None,
):
    args = [
        "diagnose",
        "--log",
        str(LOG_FIXTURE),
        "--repo",
        str(REPO_FIXTURE),
        "--service",
        "order-service",
        "--provider",
        "mock",
        "--mock-script",
        str(mock_script),
        "--output-dir",
        str(output_dir),
    ]
    if extra:
        args.extend(extra)
    return runner.invoke(app, args)


def _run_dirs(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.iterdir() if path.is_dir())


def test_happy_path_cli_and_repeat_run(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"
    first = _invoke(output_dir)

    assert first.exit_code == 0, first.output
    assert "TraceMind" in first.output
    assert "Status:" in first.output

    run_dirs = _run_dirs(output_dir)
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert {
        "run.json",
        "events.jsonl",
        "audit.jsonl",
        "report.md",
        "report.json",
    } <= {path.name for path in run_dir.iterdir()}

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "confirmed"
    assert report["validation"]["citations_valid"] is True
    assert report["validation"]["evidence_ids_valid"] is True
    assert report["root_causes"]
    assert report["sources"]
    assert report["stop"]["reason"] == "evidence_sufficient"

    run_text = (run_dir / "run.json").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" not in run_text
    assert "sk-" not in run_text

    for filename in ("events.jsonl", "audit.jsonl"):
        lines = (run_dir / filename).read_text(encoding="utf-8").splitlines()
        assert lines
        for line in lines:
            json.loads(line)

    second = _invoke(output_dir)
    assert second.exit_code == 0, second.output
    assert len(_run_dirs(output_dir)) == 2


def test_insufficient_data_exit_code(tmp_path: Path) -> None:
    empty_script = tmp_path / "empty.json"
    empty_script.write_text('{"responses": []}\n', encoding="utf-8")
    output_dir = tmp_path / "insufficient"

    result = _invoke(output_dir, empty_script)

    assert result.exit_code == 3, result.output
    run_dir = _run_dirs(output_dir)[0]
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "insufficient_data"
    assert report["stop"]["reason"] == "no_progress"


def test_budget_exit_code(tmp_path: Path) -> None:
    budget_script = tmp_path / "budget.json"
    budget_script.write_text(
        json.dumps(
            {
                "responses": [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "name": "logs.search",
                                "arguments": {"query": "rows=0"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "budget"

    result = _invoke(
        output_dir,
        budget_script,
        extra=["--max-iterations", "1"],
    )

    assert result.exit_code == 4, result.output
    run_dir = _run_dirs(output_dir)[0]
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["stop"]["reason"] == "budget_exhausted"
    assert report["stop"]["state"] == "STOPPED_BUDGET"


def test_json_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "json"

    result = _invoke(output_dir, extra=["--json"])

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["run_id"].startswith("run_")
    assert summary["status"] == "confirmed"
    assert Path(summary["report_path"]).exists()
    assert Path(summary["run_dir"]).exists()
