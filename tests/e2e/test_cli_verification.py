"""End-to-end CLI tests for fixture-only DB verification."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tracemind.cli.main import app

ROOT = Path(__file__).resolve().parents[2]
LOG_FIXTURE = ROOT / "fixtures" / "logs" / "basic" / "incident.log"
REPO_FIXTURE = ROOT / "fixtures" / "repos" / "minimal-order-service"
runner = CliRunner()

VALID_DATA = {
    "backend": "fake",
    "tables": {
        "orders": {
            "primary_key": "id",
            "columns": ["id", "status", "customer_email"],
            "sensitive_columns": ["customer_email"],
            "rows": [
                {
                    "id": 10086,
                    "status": "PAID",
                    "customer_email": "buyer@example.test",
                }
            ],
        }
    },
}

DB_SCRIPT = {
    "responses": [
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_db",
                    "name": "db.get_row",
                    "arguments": {"table": "orders", "key_value": 10086},
                }
            ],
            "finish_reason": "tool_calls",
        },
        {"content": "done", "tool_calls": [], "finish_reason": "stop"},
    ]
}


def _invoke(
    output_dir: Path,
    *,
    verification_data: Path | None = None,
    mock_script: Path | None = None,
    log: Path = LOG_FIXTURE,
):
    args = [
        "diagnose",
        "--log",
        str(log),
        "--repo",
        str(REPO_FIXTURE),
        "--service",
        "order-service",
        "--provider",
        "mock",
        "--output-dir",
        str(output_dir),
    ]
    if verification_data is not None:
        args.extend(["--verification-data", str(verification_data)])
    if mock_script is not None:
        args.extend(["--mock-script", str(mock_script)])
    return runner.invoke(app, args)


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _run_dirs(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.iterdir() if path.is_dir())


def test_missing_verification_file_exits_2_without_run_dir(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "runs"

    result = _invoke(
        output_dir,
        verification_data=tmp_path / "missing.json",
    )

    assert result.exit_code == 2
    assert not output_dir.exists()


def test_invalid_verification_json_exits_before_log_parsing(
    tmp_path: Path,
) -> None:
    empty_log = tmp_path / "empty.log"
    empty_log.write_text("", encoding="utf-8")
    verification = tmp_path / "verification.json"
    verification.write_text("{not json", encoding="utf-8")
    output_dir = tmp_path / "runs"

    result = _invoke(
        output_dir,
        verification_data=verification,
        log=empty_log,
    )

    assert result.exit_code == 2
    assert "verification data error" in result.output
    assert not output_dir.exists()


def test_invalid_verification_schema_exits_2_without_run_dir(
    tmp_path: Path,
) -> None:
    invalid = _write_json(
        tmp_path / "verification.json",
        {
            "backend": "fake",
            "tables": {
                "orders": {
                    "primary_key": "id",
                    "columns": ["status"],
                    "rows": [{"id": 1, "status": "PAID"}],
                }
            },
        },
    )
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, verification_data=invalid)

    assert result.exit_code == 2
    assert "verification data error" in result.output
    assert not output_dir.exists()


def test_valid_verification_data_enables_db_tool_in_mock_run(
    tmp_path: Path,
) -> None:
    verification = _write_json(tmp_path / "verification.json", VALID_DATA)
    script = _write_json(tmp_path / "script.json", DB_SCRIPT)
    output_dir = tmp_path / "runs"

    result = _invoke(
        output_dir,
        verification_data=verification,
        mock_script=script,
    )

    assert result.exit_code in (0, 3), result.output
    run_dirs = _run_dirs(output_dir)
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    audit_lines = (run_dir / "audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    audit = [json.loads(line) for line in audit_lines]
    db_records = [record for record in audit if record["tool_name"] == "db.get_row"]
    assert db_records
    assert db_records[0]["ok"] is True
    assert db_records[0]["error_code"] is None

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert any(
        event["event_type"] == "tool.called"
        and event["data"]["tool_name"] == "db.get_row"
        and event["data"]["ok"] is True
        for event in events
    )

    run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    verification_meta = run_data["verification"]
    assert verification_meta["environment"] == "fixture"
    assert verification_meta["backend"] == "fake"
    assert verification_meta["tables_queried"] == ["orders"]
    assert verification_meta["backend_tables"] == ["orders"]
    assert "fixture" in verification_meta["note"].lower()

    artifacts = "\n".join(
        (run_dir / filename).read_text(encoding="utf-8")
        for filename in (
            "run.json",
            "audit.jsonl",
            "events.jsonl",
            "report.json",
            "report.md",
        )
    )
    assert "buyer@example.test" not in artifacts


def test_run_without_verification_data_reports_none(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir)

    assert result.exit_code == 0, result.output
    run_dir = _run_dirs(output_dir)[0]
    run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    verification_meta = run_data["verification"]
    assert verification_meta["environment"] == "none"
    assert verification_meta["backend"] is None
    assert verification_meta["tables_queried"] == []
    assert verification_meta["backend_tables"] == []
