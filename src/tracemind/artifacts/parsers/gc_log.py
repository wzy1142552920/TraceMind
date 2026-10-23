"""Parser for common JDK 8 and JDK 9+ GC log text."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tracemind.artifacts.parsers.common import add_warning, parse_size_mb, truncate_text

MAX_EVENTS = 2000

_HEAP_RE = re.compile(
    r"(?P<before>\d+(?:\.\d+)?)(?P<before_unit>[BKMG])?"
    r"->(?P<after>\d+(?:\.\d+)?)(?P<after_unit>[BKMG])?"
    r"\((?P<total>\d+(?:\.\d+)?)(?P<total_unit>[BKMG])?\)",
    re.IGNORECASE,
)
_EVENT_MARKER_RE = re.compile(
    r"\[Full GC\b|\[GC\b|Pause\s+(?:Young|Full)\b",
    re.IGNORECASE,
)
_PAUSE_MS_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*ms\b", re.IGNORECASE)
_PAUSE_SECONDS_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*secs?\b",
    re.IGNORECASE,
)
_UNIFIED_CAUSE_START_RE = re.compile(
    r"Pause\s+(?:Young|Full)\b",
    re.IGNORECASE,
)
_LEGACY_CAUSE_START_RE = re.compile(
    r"\[(?:Full\s+)?GC\b",
    re.IGNORECASE,
)
_PROMOTION_MARKERS = ("to-space exhausted", "promotion failed")

EventType = Literal["young", "full", "other"]


class GcEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: EventType
    cause: str | None = None
    heap_before_mb: float | None = None
    heap_after_mb: float | None = None
    heap_total_mb: float | None = None
    pause_ms: float | None = None
    line_number: int
    summary: str


class GcSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_events: int = 0
    young_events: int = 0
    full_events: int = 0
    max_pause_ms: float | None = None
    total_pause_ms: float = 0.0
    promotion_failures: int = 0
    warnings: list[str] = Field(default_factory=list)


class GcLogResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: GcSummary
    events: list[GcEvent] = Field(default_factory=list)
    truncated: bool = False


def parse_gc_log(lines: Sequence[str]) -> GcLogResult:
    """Parse Young/Full GC pause lines and summarize GC pressure facts."""
    if not lines:
        return GcLogResult(
            summary=GcSummary(warnings=["GC log is empty"]),
        )

    warnings: list[str] = []
    recent_events: deque[GcEvent] = deque(maxlen=MAX_EVENTS)
    total_events = 0
    young_events = 0
    full_events = 0
    max_pause_ms: float | None = None
    total_pause_ms = 0.0
    promotion_failures = 0
    unparsed_candidates = 0

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        lowered = line.lower()
        if any(marker in lowered for marker in _PROMOTION_MARKERS):
            promotion_failures += 1
        if _EVENT_MARKER_RE.search(line) is None:
            continue

        event_type = _event_type(line)
        heap_match = list(_HEAP_RE.finditer(line))
        pause_ms = _pause_ms(line)
        cause = _cause(line)
        if not heap_match and pause_ms is None:
            unparsed_candidates += 1
            continue

        selected_heap = _select_heap_match(heap_match)
        event = GcEvent(
            event_type=event_type,
            cause=cause,
            heap_before_mb=(
                _match_size_mb(selected_heap, "before") if selected_heap else None
            ),
            heap_after_mb=(
                _match_size_mb(selected_heap, "after") if selected_heap else None
            ),
            heap_total_mb=(
                _match_size_mb(selected_heap, "total") if selected_heap else None
            ),
            pause_ms=pause_ms,
            line_number=line_number,
            summary=truncate_text(line),
        )
        total_events += 1
        if event_type == "young":
            young_events += 1
        elif event_type == "full":
            full_events += 1
        if pause_ms is not None:
            total_pause_ms += pause_ms
            if max_pause_ms is None or pause_ms > max_pause_ms:
                max_pause_ms = pause_ms
        recent_events.append(event)

    if unparsed_candidates:
        add_warning(warnings, "some GC log lines could not be parsed")
    if total_events == 0:
        add_warning(warnings, "no parsable GC events found")
    if total_events > MAX_EVENTS:
        add_warning(warnings, f"GC events truncated at {MAX_EVENTS}")

    summary = GcSummary(
        total_events=total_events,
        young_events=young_events,
        full_events=full_events,
        max_pause_ms=round(max_pause_ms, 3) if max_pause_ms is not None else None,
        total_pause_ms=round(total_pause_ms, 3),
        promotion_failures=promotion_failures,
        warnings=warnings,
    )
    return GcLogResult(
        summary=summary,
        events=list(recent_events),
        truncated=total_events > MAX_EVENTS,
    )


def _event_type(line: str) -> EventType:
    lowered = line.lower()
    if "pause full" in lowered or "[full gc" in lowered:
        return "full"
    if "pause young" in lowered or "psyounggen" in lowered or "younggen" in lowered:
        return "young"
    return "other"


def _pause_ms(line: str) -> float | None:
    millisecond_match = _PAUSE_MS_RE.search(line)
    if millisecond_match is not None:
        return float(millisecond_match.group("value"))
    second_match = _PAUSE_SECONDS_RE.search(line)
    if second_match is not None:
        return float(second_match.group("value")) * 1000.0
    return None


def _cause(line: str) -> str | None:
    match = _UNIFIED_CAUSE_START_RE.search(line) or _LEGACY_CAUSE_START_RE.search(line)
    if match is None:
        return None
    groups = _leading_groups(line[match.end() :])
    groups = [group.strip() for group in groups if group.strip()]
    if not groups:
        return None
    return truncate_text(" / ".join(groups), 128)


def _leading_groups(text: str) -> list[str]:
    groups: list[str] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text) or text[index] != "(":
            break
        depth = 1
        start = index + 1
        index += 1
        while index < len(text) and depth:
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
            index += 1
        if depth:
            break
        groups.append(text[start : index - 1])
    return groups


def _select_heap_match(matches: list[re.Match[str]]) -> re.Match[str] | None:
    if not matches:
        return None
    # JDK 8 lines contain young/old/metaspace triples; the overall heap entry
    # has the largest total in the common formats.
    return max(
        matches,
        key=lambda match: (
            parse_size_mb(
                f"{match.group('total')}{match.group('total_unit') or ''}"
            )
            or 0.0,
            match.start(),
        ),
    )


def _match_size_mb(match: re.Match[str], prefix: str) -> float | None:
    value = match.group(prefix)
    unit = match.group(f"{prefix}_unit") or ""
    return parse_size_mb(f"{value}{unit}")
