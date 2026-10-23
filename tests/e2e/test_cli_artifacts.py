"""End-to-end CLI validation for JVM artifact bundles."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tracemind.cli.main import app

ROOT = Path(__file__).resolve().parents[2]
LOG_FIXTURE = ROOT / "fixtures" / "logs" / "basic" / "incident.log"
REPO_FIXTURE = ROOT / "fixtures" / "repos" / "minimal-order-service"
runner = CliRunner()


def _write_bundle(
    root: Path,
    *,
    service: str = "order-service",
    path: str = "thread-dump.txt",
    schema_version: str = "1",
) -> Path:
    root.mkdir(parents=True)
    (root / "thread-dump.txt").write_text(
        '"main" #1 prio=5 os_prio=0 tid=0x1 nid=0x2 runnable\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": schema_version,
        "service": service,
        "artifacts": [
            {"id": "thread-dump", "kind": "thread_dump", "path": path},
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _invoke(
    output_dir: Path,
    *,
    artifacts: Path | None = None,
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
    if artifacts is not None:
        args.extend(["--artifacts", str(artifacts)])
    return runner.invoke(app, args)


def _run_dirs(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.iterdir() if path.is_dir())


def test_valid_artifacts_continue_diagnosis(tmp_path: Path) -> None:
    artifacts = _write_bundle(tmp_path / "artifacts")
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, artifacts=artifacts)

    assert result.exit_code == 0, result.output
    assert len(_run_dirs(output_dir)) == 1


def test_service_mismatch_exits_2_without_run_dir(tmp_path: Path) -> None:
    artifacts = _write_bundle(tmp_path / "artifacts", service="other-service")
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, artifacts=artifacts)

    assert result.exit_code == 2
    assert "artifacts error" in result.output
    assert not output_dir.exists()


def test_invalid_manifest_is_rejected_before_log_parsing(tmp_path: Path) -> None:
    artifacts = _write_bundle(tmp_path / "artifacts", schema_version="2")
    empty_log = tmp_path / "empty.log"
    empty_log.write_text("", encoding="utf-8")
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, artifacts=artifacts, log=empty_log)

    assert result.exit_code == 2
    assert "artifacts error" in result.output
    assert not output_dir.exists()


def test_missing_artifacts_directory_exits_2_without_run_dir(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, artifacts=tmp_path / "missing")

    assert result.exit_code == 2
    assert "artifacts error" in result.output
    assert not output_dir.exists()
