"""Text log parser for the TraceMind v0.1 minimal loop."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tracemind.core.errors import LogParseError
from tracemind.core.models import ExceptionCause, LogEvent, ParsedLog
from tracemind.log_analysis.stacktrace import parse_exception_line, parse_frame

_HEADER_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)"
    r"\s+(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+"
    r"(?:\[(?P<thread>[^\]]+)\]\s+)?"
    r"(?P<logger>[^\s]+)\s+-\s+(?P<message>.*)$",
    re.IGNORECASE,
)
_CAUSE_RE = re.compile(r"^\s*Caused by:\s*(?P<rest>.+?)\s*$")
_SUPPRESSED_RE = re.compile(r"^\s*Suppressed:\s*(?P<rest>.+?)\s*$")
_MORE_RE = re.compile(r"^\s*\.\.\.\s+\d+\s+more\s*$")


@dataclass(frozen=True)
class _Header:
    timestamp: str | None
    level: str
    thread: str | None
    logger: str
    message: str
    warning: str | None


class LogParser:
    """Parse one text log file into structured events and stack frames."""

    def parse(self, path: Path | str, source_label: str | None = None) -> ParsedLog:
        log_path = Path(path)
        source_file = source_label or str(log_path)
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LogParseError(f"cannot read log file {log_path}: {exc}") from exc

        if not text.strip():
            return ParsedLog(source_file=source_file, warnings=["empty log file"])

        events: list[LogEvent] = []
        warnings: list[str] = []
        current: LogEvent | None = None
        current_cause: ExceptionCause | None = None

        for line_number, line in enumerate(text.splitlines(), start=1):
            header = _parse_header(line)
            if header is not None:
                if current is not None:
                    events.append(current)
                current = LogEvent(
                    event_id=f"evt_{len(events) + 1:04d}",
                    source_file=source_file,
                    line_start=line_number,
                    line_end=line_number,
                    timestamp=header.timestamp,
                    level=header.level,
                    thread=header.thread,
                    logger=header.logger,
                    message=header.message,
                )
                if header.warning is not None:
                    current.parse_warnings.append(header.warning)
                current_cause = None
                continue

            if current is None:
                if line.strip():
                    warnings.append(
                        f"line {line_number}: text before first log header"
                    )
                continue

            current.line_end = line_number
            stripped = line.strip()
            if not stripped:
                continue
            if _MORE_RE.match(line):
                continue

            cause_match = _CAUSE_RE.match(line)
            if cause_match is not None:
                current_cause = _create_cause(
                    current,
                    cause_match.group("rest"),
                    "caused_by",
                    line_number,
                )
                continue

            suppressed_match = _SUPPRESSED_RE.match(line)
            if suppressed_match is not None:
                current_cause = _create_cause(
                    current,
                    suppressed_match.group("rest"),
                    "suppressed",
                    line_number,
                )
                continue

            frame = parse_frame(line)
            if frame is not None:
                if current_cause is not None:
                    current_cause.stack_frames.append(frame)
                else:
                    current.stack_frames.append(frame)
                continue

            exception = parse_exception_line(line)
            if exception is not None:
                if current.exception_type is None:
                    current.exception_type, current.exception_message = exception
                else:
                    current.parse_warnings.append(
                        f"line {line_number}: additional exception line ignored"
                    )
                continue

            current.parse_warnings.append(
                f"line {line_number}: unrecognized line: {stripped[:80]}"
            )

        if current is not None:
            events.append(current)

        return ParsedLog(
            source_file=source_file,
            events=events,
            primary_event_id=_select_primary(events),
            warnings=warnings,
        )


def _create_cause(
    event: LogEvent,
    rest: str,
    kind: str,
    line_number: int,
) -> ExceptionCause | None:
    exception = parse_exception_line(rest)
    if exception is None:
        event.parse_warnings.append(
            f"line {line_number}: unrecognized {kind} line"
        )
        return None

    cause = ExceptionCause(
        kind=kind,
        exception_type=exception[0],
        exception_message=exception[1],
    )
    event.cause_chain.append(cause)
    return cause


def _parse_header(line: str) -> _Header | None:
    match = _HEADER_RE.match(line)
    if match is None:
        return None

    raw_timestamp = match.group("timestamp")
    timestamp: str | None = None
    warning: str | None = None
    try:
        timestamp = _parse_timestamp(raw_timestamp)
    except ValueError:
        warning = f"invalid timestamp: {raw_timestamp}"

    return _Header(
        timestamp=timestamp,
        level=match.group("level").upper(),
        thread=match.group("thread"),
        logger=match.group("logger"),
        message=match.group("message").strip(),
        warning=warning,
    )


def _parse_timestamp(raw: str) -> str:
    normalized = raw.replace("T", " ")
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in normalized else "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(normalized, fmt).isoformat()


def _select_primary(events: list[LogEvent]) -> str | None:
    for event in events:
        if event.exception_type is not None and _has_frames(event):
            return event.event_id
    for event in events:
        if event.level == "ERROR":
            return event.event_id
    for event in events:
        if event.level == "WARN":
            return event.event_id
    return None


def _has_frames(event: LogEvent) -> bool:
    return bool(event.stack_frames) or any(
        cause.stack_frames for cause in event.cause_chain
    )
