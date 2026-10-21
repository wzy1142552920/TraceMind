"""Unit tests for the text log parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracemind.core.errors import LogParseError
from tracemind.core.models import LogEvent, ParsedLog
from tracemind.log_analysis.parser import LogParser

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"


def _primary(parsed: ParsedLog) -> LogEvent:
    assert parsed.primary_event_id is not None
    return next(event for event in parsed.events if event.event_id == parsed.primary_event_id)


def test_fixture_parses_three_events_and_primary_error() -> None:
    parsed = LogParser().parse(FIXTURE)

    assert len(parsed.events) == 3
    assert [event.level for event in parsed.events] == ["INFO", "WARN", "ERROR"]
    assert parsed.primary_event_id == "evt_0003"

    primary = _primary(parsed)
    assert primary.level == "ERROR"
    assert primary.thread == "http-nio-8080-exec-7"
    assert primary.logger == "c.e.order.OrderService"
    assert primary.message == "failed to update order status"
    assert primary.timestamp is not None
    assert primary.timestamp.startswith("2026-10-18T10:21:03")
    assert primary.line_start == 3
    assert primary.line_end == 10
    assert primary.parse_warnings == []


def test_fixture_exception_and_stack_frames() -> None:
    primary = _primary(LogParser().parse(FIXTURE))

    assert primary.exception_type == "java.lang.IllegalStateException"
    assert primary.exception_message == "update failed for orderId=10086"
    assert len(primary.stack_frames) == 3

    top = primary.stack_frames[0]
    assert top.class_name == "com.example.order.OrderService"
    assert top.method_name == "updateStatus"
    assert top.file_name == "OrderService.java"
    assert top.line_number == 24
    assert primary.stack_frames[2].class_name == "java.lang.Thread"


def test_fixture_cause_chain() -> None:
    primary = _primary(LogParser().parse(FIXTURE))

    assert len(primary.cause_chain) == 1
    cause = primary.cause_chain[0]
    assert cause.kind == "caused_by"
    assert cause.exception_type == "org.springframework.dao.DataAccessException"
    assert cause.exception_message == "mapper update failed"
    assert cause.stack_frames[0].class_name == "com.example.order.OrderMapper"
    assert cause.stack_frames[0].line_number == 18


def test_fixture_is_pydantic_serializable() -> None:
    parsed = LogParser().parse(FIXTURE)

    data = json.loads(parsed.model_dump_json())
    assert data["primary_event_id"] == "evt_0003"
    assert data["events"][2]["exception_type"] == "java.lang.IllegalStateException"


def test_unknown_line_records_warning_with_line_number(tmp_path: Path) -> None:
    log_path = tmp_path / "unknown.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR [t] c.e.X - boom\n"
        "this is not a known continuation\n",
        encoding="utf-8",
    )

    parsed = LogParser().parse(log_path)

    assert len(parsed.events) == 1
    assert parsed.primary_event_id == "evt_0001"
    assert any("line 2" in warning for warning in parsed.events[0].parse_warnings)


def test_missing_file_raises_log_parse_error(tmp_path: Path) -> None:
    with pytest.raises(LogParseError):
        LogParser().parse(tmp_path / "missing.log")


def test_empty_file_returns_warning(tmp_path: Path) -> None:
    log_path = tmp_path / "empty.log"
    log_path.write_text("", encoding="utf-8")

    parsed = LogParser().parse(log_path)

    assert parsed.events == []
    assert parsed.primary_event_id is None
    assert parsed.warnings == ["empty log file"]


def test_truncated_stack_trace_does_not_crash(tmp_path: Path) -> None:
    log_path = tmp_path / "truncated.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR [t] c.e.X - boom\n"
        "java.lang.IllegalStateException: boom\n"
        "    at com.example.A.b(A.java:1)\n",
        encoding="utf-8",
    )

    parsed = LogParser().parse(log_path)

    primary = _primary(parsed)
    assert len(primary.stack_frames) == 1
    assert primary.cause_chain == []


def test_suppressed_exception_is_captured(tmp_path: Path) -> None:
    log_path = tmp_path / "suppressed.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR [t] c.e.X - boom\n"
        "java.lang.IllegalStateException: boom\n"
        "    at com.example.A.b(A.java:1)\n"
        "Suppressed: java.io.IOException: io\n"
        "    at com.example.C.d(C.java:2)\n",
        encoding="utf-8",
    )

    parsed = LogParser().parse(log_path)

    primary = _primary(parsed)
    assert len(primary.cause_chain) == 1
    cause = primary.cause_chain[0]
    assert cause.kind == "suppressed"
    assert cause.exception_type == "java.io.IOException"
    assert cause.stack_frames[0].class_name == "com.example.C"
