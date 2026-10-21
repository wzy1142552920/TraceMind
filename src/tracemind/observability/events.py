"""Serialization helpers for runtime events."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.diagnosis.state import RuntimeEvent


def write_events_jsonl(path: Path, events: list[RuntimeEvent]) -> None:
    """Write runtime events as one JSON object per line."""
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            payload = event.model_dump(mode="json")
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
