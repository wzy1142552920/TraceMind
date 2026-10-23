"""Parser for jmap -histo[:live] text output."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from tracemind.artifacts.parsers.common import add_warning, truncate_text

MAX_CLASSES = 200

_HEADER_RE = re.compile(
    r"^\s*num\s+#instances\s+#bytes\s+class\s+name\b",
    re.IGNORECASE,
)
_ROW_RE = re.compile(
    r"^\s*(?P<rank>\d+):\s+(?P<instances>\d+)\s+(?P<bytes>\d+)\s+"
    r"(?P<class_name>\S.*?)\s*$"
)
_TOTAL_RE = re.compile(
    r"^\s*Total\s+(?P<instances>\d+)\s+(?P<bytes>\d+)\s*$",
    re.IGNORECASE,
)


class HeapClassStat(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int
    instances: int
    bytes: int
    class_name: str
    line_number: int


class HeapHistogramSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    live: bool = False
    classes: list[HeapClassStat] = Field(default_factory=list)
    total_instances: int | None = None
    total_bytes: int | None = None
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


def parse_heap_histogram(
    lines: Sequence[str],
    *,
    live_hint: bool = False,
) -> HeapHistogramSummary:
    """Parse a jmap histogram, retaining the leading classes."""
    if not lines:
        return HeapHistogramSummary(warnings=["heap histogram is empty"])

    warnings: list[str] = []
    live = live_hint or any(":live" in line.lower() for line in lines[:5])
    classes: list[HeapClassStat] = []
    seen_header = False
    total_instances: int | None = None
    total_bytes: int | None = None
    truncated = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if _HEADER_RE.search(line.lstrip("﻿")):
            seen_header = True
            continue

        total_match = _TOTAL_RE.match(line)
        if total_match is not None:
            total_instances = int(total_match.group("instances"))
            total_bytes = int(total_match.group("bytes"))
            continue

        if not seen_header:
            continue
        row_match = _ROW_RE.match(line)
        if row_match is None:
            continue
        if len(classes) >= MAX_CLASSES:
            truncated = True
            continue
        classes.append(
            HeapClassStat(
                rank=int(row_match.group("rank")),
                instances=int(row_match.group("instances")),
                bytes=int(row_match.group("bytes")),
                class_name=truncate_text(row_match.group("class_name"), 512),
                line_number=line_number,
            )
        )

    if not seen_header:
        add_warning(warnings, "no heap histogram table found")
    elif not classes:
        add_warning(warnings, "no heap histogram classes found")
    if total_bytes is None:
        add_warning(warnings, "heap histogram total is missing")
    if not live:
        add_warning(warnings, "heap histogram may include unreachable objects")
    if truncated:
        add_warning(warnings, f"heap histogram classes truncated at {MAX_CLASSES}")

    return HeapHistogramSummary(
        live=live,
        classes=classes,
        total_instances=total_instances,
        total_bytes=total_bytes,
        warnings=warnings,
        truncated=truncated,
    )
