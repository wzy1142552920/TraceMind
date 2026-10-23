"""Heap histogram parser tests for jmap -histo[:live]."""

from __future__ import annotations

from tracemind.artifacts.parsers import heap_histogram as module
from tracemind.artifacts.parsers import parse_heap_histogram

HISTO = """\
 num     #instances         #bytes  class name (module)
-------------------------------------------------------
   1:       1234567       98765432  [B (java.base@17.0.1)
   2:        234567       12345678  com.example.ReportEntry
   3:        100000        3200000  java.util.concurrent.ConcurrentHashMap$Node
Total       1569134      114311010
"""

LIVE_HISTO = """\
jmap -histo:live 12345
 num     #instances         #bytes  class name (module)
   1:             10             100  com.example.Entry
Total              10             100
"""


def test_parses_header_rows_and_total() -> None:
    summary = parse_heap_histogram(HISTO.splitlines())

    assert summary.live is False
    assert len(summary.classes) == 3
    assert summary.classes[0].rank == 1
    assert summary.classes[0].instances == 1234567
    assert summary.classes[0].bytes == 98765432
    assert summary.classes[0].class_name == "[B (java.base@17.0.1)"
    assert summary.classes[2].class_name.endswith("ConcurrentHashMap$Node")
    assert summary.total_instances == 1569134
    assert summary.total_bytes == 114311010
    assert any("unreachable" in warning for warning in summary.warnings)


def test_live_hint_and_header_marker_disable_unreachable_warning() -> None:
    summary = parse_heap_histogram(LIVE_HISTO.splitlines())
    assert summary.live is True
    assert not any("unreachable" in warning for warning in summary.warnings)

    hinted = parse_heap_histogram(HISTO.splitlines(), live_hint=True)
    assert hinted.live is True


def test_bom_is_tolerated_on_header() -> None:
    summary = parse_heap_histogram(["﻿ num #instances #bytes class name", "1: 1 2 A"])
    assert len(summary.classes) == 1
    assert summary.classes[0].class_name == "A"


def test_missing_header_and_empty_input_warn() -> None:
    empty = parse_heap_histogram([])
    assert empty.classes == []
    assert empty.warnings == ["heap histogram is empty"]

    missing = parse_heap_histogram(["1: 10 20 com.example.Entry"])
    assert missing.classes == []
    assert any("no heap histogram table" in warning for warning in missing.warnings)


def test_class_name_is_bounded_and_results_are_deterministic() -> None:
    lines = ["num #instances #bytes class name", f"1: 1 2 {'C' * 1000}"]
    summary = parse_heap_histogram(lines)

    assert summary == parse_heap_histogram(lines)
    assert len(summary.classes[0].class_name) <= 512


def test_class_limit(monkeypatch) -> None:
    monkeypatch.setattr(module, "MAX_CLASSES", 2)
    lines = ["num #instances #bytes class name"]
    lines.extend(f"{index}: 1 2 com.example.C{index}" for index in range(1, 5))
    summary = parse_heap_histogram(lines)
    assert len(summary.classes) == 2
    assert summary.truncated is True
    assert any("truncated" in warning for warning in summary.warnings)
