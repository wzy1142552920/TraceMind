"""Deterministic same-thread log context shared by seeding and tools."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, Field

from tracemind.core.models import LogEvent, ParsedLog

MAX_RADIUS = 20


class ThreadContextError(ValueError):
    """A stable failure while collecting same-thread context."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ThreadContextItem(BaseModel):
    """One same-thread log event rendered without stack frames."""

    event_id: str
    line: int
    timestamp: str | None = None
    level: str | None = None
    thread: str
    logger: str
    logger_class: str
    message: str


class ThreadContext(BaseModel):
    """Ordered same-thread context around one anchor event."""

    anchor_event_id: str
    thread: str
    source_ref: str
    line_start: int
    line_end: int
    items: list[ThreadContextItem] = Field(default_factory=list)
    count: int = 0
    truncated: bool = False


def collect_thread_context(
    parsed_log: ParsedLog,
    anchor_event_id: str | None = None,
    *,
    before: int = 3,
    after: int = 3,
) -> ThreadContext:
    """Collect same-thread events around an anchor in log order.

    Cross-thread events never enter ``items`` or the source-ref line range.
    """
    if not 0 <= before <= MAX_RADIUS or not 0 <= after <= MAX_RADIUS:
        raise ThreadContextError(
            "INVALID_ARGUMENTS",
            f"before/after must be within 0..{MAX_RADIUS}",
        )
    if not parsed_log.events:
        raise ThreadContextError("TARGET_DENIED", "log contains no events")

    target_id = anchor_event_id or parsed_log.primary_event_id
    if target_id is None:
        raise ThreadContextError(
            "TARGET_DENIED",
            "no primary event is available; provide event_id",
        )
    anchor = next(
        (event for event in parsed_log.events if event.event_id == target_id),
        None,
    )
    if anchor is None:
        raise ThreadContextError(
            "TARGET_DENIED",
            f"log event not found: {target_id}",
        )
    if not anchor.thread:
        raise ThreadContextError(
            "INVALID_ARGUMENTS",
            f"log event {anchor.event_id} has no thread",
        )

    thread_events = [
        event for event in parsed_log.events if event.thread == anchor.thread
    ]
    anchor_index = next(
        index
        for index, event in enumerate(thread_events)
        if event.event_id == anchor.event_id
    )
    start = max(0, anchor_index - before)
    end = min(len(thread_events), anchor_index + after + 1)
    selected = thread_events[start:end]
    if not selected:
        raise ThreadContextError(
            "TARGET_DENIED",
            f"no same-thread events for {anchor.event_id}",
        )

    line_start = min(event.line_start for event in selected)
    line_end = max(event.line_start for event in selected)
    return ThreadContext(
        anchor_event_id=anchor.event_id,
        thread=anchor.thread,
        source_ref=(
            f"log://{Path(parsed_log.source_file).name}"
            f"#thread={quote(anchor.thread, safe='')}&L{line_start}-L{line_end}"
        ),
        line_start=line_start,
        line_end=line_end,
        items=[_context_item(event) for event in selected],
        count=len(selected),
        truncated=(
            start > 0
            or end < len(thread_events)
        ),
    )


def _context_item(event: LogEvent) -> ThreadContextItem:
    logger = event.logger or ""
    return ThreadContextItem(
        event_id=event.event_id,
        line=event.line_start,
        timestamp=event.timestamp,
        level=event.level,
        thread=event.thread or "",
        logger=logger,
        logger_class=logger.rsplit(".", 1)[-1],
        message=event.message,
    )
