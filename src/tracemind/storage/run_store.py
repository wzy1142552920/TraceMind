"""Local run-directory persistence for v0.1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracemind.diagnosis.evidence import RunResult
from tracemind.diagnosis.report import Report, render_markdown
from tracemind.observability.events import write_events_jsonl


class RunStore:
    """Create immutable run directories with reports and observability files."""

    def __init__(self, output_dir: Path | str = ".tracemind/runs") -> None:
        self._output_dir = Path(output_dir)

    def write(
        self,
        result: RunResult,
        report: Report,
        run_meta: dict[str, Any],
    ) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = self._output_dir / result.run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        (run_dir / "run.json").write_text(
            json.dumps(run_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_events_jsonl(run_dir / "events.jsonl", result.events)
        self._write_audit(run_dir / "audit.jsonl", result)
        (run_dir / "report.json").write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (run_dir / "report.md").write_text(
            render_markdown(report),
            encoding="utf-8",
        )
        return run_dir

    def _write_audit(self, path: Path, result: RunResult) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in result.tool_calls:
                payload = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "run_id": result.run_id,
                    "tool_call_id": record.tool_call_id,
                    "tool_name": record.tool_name,
                    "args_hash": _hash_arguments(record.arguments),
                    "ok": record.ok,
                    "error_code": record.error_code,
                    "duration_ms": record.duration_ms,
                    "evidence_ids": record.evidence_ids,
                }
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _hash_arguments(arguments: Any) -> str:
    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
