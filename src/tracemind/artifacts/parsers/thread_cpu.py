"""Parser for Linux thread-level CPU snapshots (top -H / ps -L)."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from tracemind.artifacts.parsers.common import (
    add_warning,
    nid_from_tid,
    truncate_text,
)

MAX_SAMPLES = 2048


class ThreadCpuSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tid_decimal: int
    tid_hex: str
    cpu_percent: float
    command: str | None = None
    line_number: int


class ThreadCpuSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    samples: list[ThreadCpuSample] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


def parse_thread_cpu(lines: Sequence[str]) -> ThreadCpuSummary:
    """Parse top/ps thread CPU tables, sorted by CPU percent."""
    if not lines:
        return ThreadCpuSummary(warnings=["thread CPU snapshot is empty"])

    warnings: list[str] = []
    samples: list[ThreadCpuSample] = []
    header: tuple[int, int, int | None] | None = None

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        columns = _header_columns(line)
        if columns is not None:
            header = columns
            continue
        if header is None:
            continue

        tid_index, cpu_index, command_index = header
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        parts = stripped.split()
        if len(parts) <= max(tid_index, cpu_index):
            add_warning(warnings, "some thread CPU rows could not be parsed")
            continue
        try:
            tid = int(parts[tid_index])
            cpu_percent = float(parts[cpu_index].rstrip("%"))
        except ValueError:
            add_warning(warnings, "some thread CPU rows could not be parsed")
            continue
        if tid < 0 or cpu_percent < 0:
            add_warning(warnings, "some thread CPU rows could not be parsed")
            continue
        command: str | None = None
        if command_index is not None and len(parts) > command_index:
            command = truncate_text(" ".join(parts[command_index:]), 128) or None
        samples.append(
            ThreadCpuSample(
                tid_decimal=tid,
                tid_hex=nid_from_tid(tid),
                cpu_percent=cpu_percent,
                command=command,
                line_number=line_number,
            )
        )

    if header is None:
        add_warning(warnings, "no thread CPU table header found")
    if not samples:
        add_warning(warnings, "no thread CPU samples found")

    samples.sort(key=lambda sample: (-sample.cpu_percent, sample.line_number))
    truncated = len(samples) > MAX_SAMPLES
    if truncated:
        samples = samples[:MAX_SAMPLES]
        add_warning(warnings, f"thread CPU samples truncated at {MAX_SAMPLES}")
    return ThreadCpuSummary(
        samples=samples,
        warnings=warnings,
        truncated=truncated,
    )


def _header_columns(line: str) -> tuple[int, int, int | None] | None:
    parts = line.strip().split()
    if not parts:
        return None
    lowered = [part.lower() for part in parts]
    if "lwp" in lowered:
        tid_index = lowered.index("lwp")
    elif "tid" in lowered:
        tid_index = lowered.index("tid")
    elif "pid" in lowered:
        tid_index = lowered.index("pid")
    else:
        return None

    cpu_index: int | None = None
    for index, value in enumerate(lowered):
        if value in {"%cpu", "cpu%", "%cpu%"}:
            cpu_index = index
            break
    if cpu_index is None:
        return None

    command_index: int | None = None
    for name in ("command", "cmd", "name"):
        if name in lowered:
            command_index = lowered.index(name)
            break
    return tid_index, cpu_index, command_index
