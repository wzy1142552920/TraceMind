"""GC log parser tests for unified and JDK 8 text formats."""

from __future__ import annotations

import pytest

from tracemind.artifacts.parsers import gc_log as module
from tracemind.artifacts.parsers import parse_gc_log

JDK9_YOUNG = (
    "[2026-10-23T10:00:00.123+0800][info][gc] GC(12) Pause Young "
    "(Normal) (G1 Evacuation Pause) 512M->256M(1024M) 12.345ms"
)
JDK9_FULL = (
    "[2026-10-23T10:00:00.123+0800][info][gc] GC(13) Pause Full "
    "(System.gc()) 1024M->900M(1024M) 1234.567ms"
)
JDK8_YOUNG = (
    "2026-10-23T10:00:00.123+0800: 12.345: [GC (Allocation Failure) "
    "[PSYoungGen: 512K->256K(1024K)] 512K->300K(2048K), 0.0123456 secs]"
)
JDK8_FULL = (
    "2026-10-23T10:00:00.123+0800: 99.345: [Full GC (Ergonomics) "
    "[PSYoungGen: 2048K->0K(3072K)] [ParOldGen: 1000K->900K(2048K)] "
    "3048K->1900K(5120K), [Metaspace: 100K->100K(1024K)], 0.1234567 secs]"
)


def test_parses_unified_young_gc() -> None:
    result = parse_gc_log([JDK9_YOUNG])

    assert result.summary.total_events == 1
    assert result.summary.young_events == 1
    assert result.summary.full_events == 0
    assert result.summary.max_pause_ms == 12.345
    event = result.events[0]
    assert event.event_type == "young"
    assert event.cause == "Normal / G1 Evacuation Pause"
    assert event.heap_before_mb == 512.0
    assert event.heap_after_mb == 256.0
    assert event.heap_total_mb == 1024.0
    assert event.pause_ms == 12.345
    assert event.line_number == 1


def test_parses_unified_full_gc() -> None:
    result = parse_gc_log([JDK9_FULL])
    assert result.summary.full_events == 1
    assert result.events[0].event_type == "full"
    assert result.events[0].cause == "System.gc()"
    assert result.summary.total_pause_ms == 1234.567


def test_parses_jdk8_young_and_full_gc() -> None:
    result = parse_gc_log([JDK8_YOUNG, JDK8_FULL])

    assert result.summary.total_events == 2
    assert result.summary.young_events == 1
    assert result.summary.full_events == 1
    young, full = result.events
    assert young.cause == "Allocation Failure"
    assert young.heap_before_mb == 0.5
    assert young.heap_after_mb == pytest.approx(300 / 1024, rel=1e-3)
    assert young.heap_total_mb == 2.0
    assert young.pause_ms == pytest.approx(12.3456)
    assert full.cause == "Ergonomics"
    assert full.heap_before_mb == pytest.approx(3048 / 1024, rel=1e-3)
    assert full.heap_after_mb == pytest.approx(1900 / 1024, rel=1e-3)
    assert full.heap_total_mb == 5.0
    assert full.pause_ms == pytest.approx(123.4567)


def test_counts_promotion_failure_markers() -> None:
    line = (
        "[2026-10-23T10:00:00.123+0800][info][gc] GC(14) Pause Young "
        "(G1 Evacuation Pause) (to-space exhausted) 1024M->1000M(1024M) 50.0ms"
    )
    result = parse_gc_log([line])
    assert result.summary.promotion_failures == 1


def test_other_gc_events_are_counted_but_not_young_or_full() -> None:
    line = (
        "2026-10-23T10:00:00.123+0800: 12.345: [GC (CMS Initial Mark) "
        "[ParNew: 512K->256K(1024K)] 512K->300K(2048K), 0.0123456 secs]"
    )
    result = parse_gc_log([line])
    assert result.summary.total_events == 1
    assert result.summary.young_events == 0
    assert result.summary.full_events == 0
    assert result.events[0].event_type == "other"


def test_empty_and_unparsable_inputs_warn_without_raising() -> None:
    empty = parse_gc_log([])
    assert empty.events == []
    assert empty.summary.warnings == ["GC log is empty"]

    unparsable = parse_gc_log(["GC log started", "[gc] nothing to see"])
    assert unparsable.events == []
    assert any("no parsable" in warning for warning in unparsable.summary.warnings)


def test_summary_text_is_bounded_and_results_are_deterministic() -> None:
    line = JDK9_YOUNG + " x" * 1000
    result = parse_gc_log([line])

    assert result == parse_gc_log([line])
    assert len(result.events[0].summary) <= 512


def test_event_limit_and_summary_cover_all_events(monkeypatch) -> None:
    monkeypatch.setattr(module, "MAX_EVENTS", 2)
    lines = [JDK9_YOUNG.replace("GC(12)", f"GC({index})") for index in range(5)]
    result = parse_gc_log(lines)
    assert result.summary.total_events == 5
    assert len(result.events) == 2
    assert result.truncated is True
    assert result.events[-1].line_number == 5
