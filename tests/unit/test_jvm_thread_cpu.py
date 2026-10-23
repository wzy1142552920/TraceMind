"""Thread CPU parser tests for top -H and ps -L text."""

from __future__ import annotations

from tracemind.artifacts.parsers import parse_thread_cpu
from tracemind.artifacts.parsers import thread_cpu as module

TOP = """\
top - 10:15:00 up 1 day,  2:03,  0 users,  load average: 2.10, 2.00, 1.50
Threads:  42 total,   1 running,  41 sleeping,   0 stopped,   0 zombie
  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
  123 app       20   0  4200000 120000 20000 R  92.3   3.0  10:15.00 pricing-exec-1
  124 app       20   0  4200000 120000 20000 S   3.1   3.0   0:10.00 worker-1
  125 app       20   0  4200000 120000 20000 S   3.1   3.0   0:09.00 worker-2
"""

PS = """\
  LWP %CPU COMMAND
 1234 12.5 java
 1235  0.1 worker
"""

PS_WITH_PID = """\
  PID   TID %CPU COMMAND
 9999 4242 55.0 pricing-exec-1
 9999 4243  1.0 worker
"""


def test_parses_top_headers_and_sorts_stably() -> None:
    summary = parse_thread_cpu(TOP.splitlines())

    assert summary.truncated is False
    assert [sample.tid_decimal for sample in summary.samples] == [123, 124, 125]
    assert summary.samples[0].cpu_percent == 92.3
    assert summary.samples[0].tid_hex == "0x7b"
    assert summary.samples[0].line_number == 4
    assert summary.samples[0].command == "pricing-exec-1"
    assert summary.samples[1].cpu_percent == summary.samples[2].cpu_percent


def test_parses_ps_lwp_and_prefers_tid_over_pid() -> None:
    lwp = parse_thread_cpu(PS.splitlines())
    assert [sample.tid_decimal for sample in lwp.samples] == [1234, 1235]
    assert lwp.samples[0].tid_hex == "0x4d2"
    assert lwp.samples[0].command == "java"

    with_pid = parse_thread_cpu(PS_WITH_PID.splitlines())
    assert [sample.tid_decimal for sample in with_pid.samples] == [4242, 4243]


def test_warns_when_header_is_missing_or_rows_are_malformed() -> None:
    missing = parse_thread_cpu(["123 90.0 java"])
    assert missing.samples == []
    assert any("header" in warning for warning in missing.warnings)

    malformed = parse_thread_cpu(
        ["PID %CPU COMMAND", "123 not-a-number java", "not-a-row"]
    )
    assert malformed.samples == []
    assert any("could not be parsed" in warning for warning in malformed.warnings)


def test_empty_input() -> None:
    summary = parse_thread_cpu([])
    assert summary.samples == []
    assert summary.warnings == ["thread CPU snapshot is empty"]


def test_sample_limit(monkeypatch) -> None:
    monkeypatch.setattr(module, "MAX_SAMPLES", 2)
    lines = ["PID %CPU COMMAND"]
    lines.extend(f"{index} {index}.0 java" for index in range(1, 5))
    summary = parse_thread_cpu(lines)
    assert len(summary.samples) == 2
    assert summary.samples[0].cpu_percent == 4.0
    assert summary.truncated is True
    assert any("truncated" in warning for warning in summary.warnings)


def test_command_is_bounded_and_results_are_deterministic() -> None:
    lines = ["PID %CPU COMMAND", f"123 50.0 {'c' * 500}"]
    summary = parse_thread_cpu(lines)

    assert summary == parse_thread_cpu(lines)
    assert len(summary.samples[0].command or "") <= 128


def test_hex_nid_formatting() -> None:
    summary = parse_thread_cpu(["LWP %CPU COMMAND", "6692 1.0 java"])
    assert summary.samples[0].tid_hex == "0x1a24"
