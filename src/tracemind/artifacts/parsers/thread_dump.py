"""Deterministic parser for common jstack thread-dump text."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from tracemind.artifacts.parsers.common import (
    add_warning,
    truncate_text,
    unique_in_order,
)

MAX_THREADS = 4096
MAX_FRAMES = 8
MAX_LOCKS = 4

_THREAD_HEADER_RE = re.compile(r'^\s*"(?P<name>[^"]*)"\s+(?P<meta>.*)$')
_NID_RE = re.compile(r"\bnid=(?P<nid>\S+)")
_TID_RE = re.compile(r"\btid=(?P<tid>\S+)")
_JAVA_ID_RE = re.compile(r"#(?P<java_id>\d+)")
_HEADER_STATE_RE = re.compile(r"\bnid=\S+\s+(?P<state>[a-z_]+)")
_STATE_RE = re.compile(r"java\.lang\.Thread\.State:\s*(?P<state>[A-Z_]+)")
_FRAME_RE = re.compile(r"^\s+at\s+(?P<qualified>[^\s(]+)\((?P<location>[^)]*)\)")
_LOCK_PREFIXES = (
    "- locked ",
    "- waiting to lock ",
    "- parking to wait for ",
    "- waiting on ",
)
_DEADLOCK_START_RE = re.compile(r"Found .*Java-level deadlock", re.IGNORECASE)
_DEADLOCK_THREAD_RE = re.compile(r'^\s*"(?P<name>[^"]+)":\s*$')
_DEADLOCK_END_RE = re.compile(r"Found \d+ deadlocks?\.", re.IGNORECASE)
_DEADLOCK_OBJECT_RE = re.compile(r"\bobject\s+(?P<lock>0x[0-9a-fA-F]+)")
_DEADLOCK_ANGLE_RE = re.compile(r"(?P<lock><0x[0-9a-fA-F]+>)")
_DEADLOCK_HOLDER_RE = re.compile(r'which is held by "(?P<name>[^"]+)"')


class ThreadFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    class_name: str
    method: str
    file: str | None = None
    line: int | None = None
    frame_index: int


class ThreadSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    java_id: str | None = None
    nid: str | None = None
    state: str | None = None
    daemon: bool = False
    line_start: int
    line_end: int
    frames: list[ThreadFrame] = Field(default_factory=list)
    lock_events: list[str] = Field(default_factory=list)
    deadlock_related: bool = False


class DeadlockInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threads: list[str] = Field(default_factory=list)
    lock_ids: list[str] = Field(default_factory=list)
    line_start: int
    line_end: int


class ThreadDumpSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    threads: list[ThreadSnapshot] = Field(default_factory=list)
    deadlocks: list[DeadlockInfo] = Field(default_factory=list)
    thread_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False


@dataclass
class _ThreadBuilder:
    name: str
    line_start: int
    line_end: int
    java_id: str | None = None
    nid: str | None = None
    state: str | None = None
    daemon: bool = False
    frames: list[ThreadFrame] = field(default_factory=list)
    lock_events: list[str] = field(default_factory=list)
    dropped_frames: bool = False


@dataclass
class _DeadlockBuilder:
    line_start: int
    line_end: int
    threads: list[str] = field(default_factory=list)
    lock_ids: list[str] = field(default_factory=list)


def parse_thread_dump(lines: Sequence[str]) -> ThreadDumpSummary:
    """Parse jstack-style text into bounded thread and deadlock summaries."""
    if not lines:
        return ThreadDumpSummary(warnings=["thread dump is empty"])

    builders: list[_ThreadBuilder] = []
    deadlock_builders: list[_DeadlockBuilder] = []
    warnings: list[str] = []
    current: _ThreadBuilder | None = None
    current_deadlock: _DeadlockBuilder | None = None
    truncated = False

    def finish_current() -> None:
        nonlocal current
        if current is not None:
            builders.append(current)
            current = None

    def finish_deadlock() -> None:
        nonlocal current_deadlock
        if current_deadlock is not None:
            current_deadlock.threads = unique_in_order(current_deadlock.threads)
            current_deadlock.lock_ids = unique_in_order(current_deadlock.lock_ids)
            if not current_deadlock.threads and not current_deadlock.lock_ids:
                add_warning(warnings, "deadlock section could not be parsed")
            deadlock_builders.append(current_deadlock)
            current_deadlock = None

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")

        if _DEADLOCK_START_RE.search(line):
            finish_current()
            finish_deadlock()
            current_deadlock = _DeadlockBuilder(
                line_start=line_number,
                line_end=line_number,
            )
            continue

        if current_deadlock is not None:
            current_deadlock.line_end = line_number
            if _DEADLOCK_END_RE.search(line):
                finish_deadlock()
                continue
            thread_match = _DEADLOCK_THREAD_RE.match(line)
            if thread_match:
                current_deadlock.threads.append(
                    truncate_text(thread_match.group("name"))
                )
            holder_match = _DEADLOCK_HOLDER_RE.search(line)
            if holder_match:
                current_deadlock.threads.append(
                    truncate_text(holder_match.group("name"))
                )
            if "waiting to lock" in line.lower() or "lock" in line.lower():
                for lock_match in _DEADLOCK_OBJECT_RE.finditer(line):
                    current_deadlock.lock_ids.append(
                        lock_match.group("lock").strip("<>")
                    )
                for lock_match in _DEADLOCK_ANGLE_RE.finditer(line):
                    current_deadlock.lock_ids.append(
                        lock_match.group("lock").strip("<>")
                    )
            if line.strip().startswith('"') and _NID_RE.search(line):
                # Some tools omit the summary; resume normal thread parsing.
                finish_deadlock()

        header_match = _THREAD_HEADER_RE.match(line)
        if header_match is not None and _NID_RE.search(header_match.group("meta")):
            meta = header_match.group("meta")
            finish_current()
            if len(builders) >= MAX_THREADS:
                truncated = True
                add_warning(
                    warnings,
                    f"thread dump truncated at {MAX_THREADS} threads",
                )
                break
            nid_match = _NID_RE.search(meta)
            tid_match = _TID_RE.search(meta)
            java_id_match = _JAVA_ID_RE.search(meta)
            state_match = _HEADER_STATE_RE.search(meta)
            current = _ThreadBuilder(
                name=truncate_text(header_match.group("name")),
                line_start=line_number,
                line_end=line_number,
                java_id=(
                    truncate_text(java_id_match.group("java_id"), 64)
                    if java_id_match
                    else None
                ),
                nid=(
                    truncate_text(nid_match.group("nid"), 64)
                    if nid_match
                    else None
                ),
                state=(
                    truncate_text(state_match.group("state").upper(), 64)
                    if state_match
                    else None
                ),
                daemon=bool(re.search(r"\bdaemon\b", meta)),
            )
            if tid_match is not None:
                current.lock_events = []
            continue

        if current is None:
            continue

        if line.strip():
            current.line_end = line_number
        state_match = _STATE_RE.search(line)
        if state_match is not None:
            current.state = truncate_text(state_match.group("state").upper(), 64)
            continue

        frame_match = _FRAME_RE.match(line)
        if frame_match is not None:
            if len(current.frames) < MAX_FRAMES:
                current.frames.append(
                    _parse_frame(
                        frame_match.group("qualified"),
                        frame_match.group("location"),
                        len(current.frames),
                    )
                )
            elif not current.dropped_frames:
                current.dropped_frames = True
                add_warning(
                    warnings,
                    f"stack frames truncated at {MAX_FRAMES} frames per thread",
                )
            continue

        stripped = line.strip()
        if stripped.startswith(_LOCK_PREFIXES):
            if len(current.lock_events) < MAX_LOCKS:
                current.lock_events.append(truncate_text(stripped, 256))
            continue

    finish_current()
    finish_deadlock()

    if not builders:
        add_warning(warnings, "no parsable thread headers found")

    deadlock_thread_names = {
        name for deadlock in deadlock_builders for name in deadlock.threads
    }
    threads = [
        ThreadSnapshot(
            name=builder.name,
            java_id=builder.java_id,
            nid=builder.nid,
            state=builder.state,
            daemon=builder.daemon,
            line_start=builder.line_start,
            line_end=builder.line_end,
            frames=list(builder.frames),
            lock_events=list(builder.lock_events),
            deadlock_related=builder.name in deadlock_thread_names,
        )
        for builder in builders
    ]
    deadlocks = [
        DeadlockInfo(
            threads=list(builder.threads),
            lock_ids=list(builder.lock_ids),
            line_start=builder.line_start,
            line_end=min(builder.line_end, len(lines)),
        )
        for builder in deadlock_builders
    ]
    return ThreadDumpSummary(
        threads=threads,
        deadlocks=deadlocks,
        thread_count=len(threads),
        warnings=warnings,
        truncated=truncated,
    )


def _parse_frame(qualified: str, location: str, index: int) -> ThreadFrame:
    clean_qualified = qualified.rsplit("/", 1)[-1]
    if "." in clean_qualified:
        class_name, method = clean_qualified.rsplit(".", 1)
    else:
        class_name, method = clean_qualified, ""
    file_name: str | None
    line_number: int | None = None
    if location.isdigit():
        file_name = None
        line_number = int(location)
    else:
        file_name = location
        prefix, separator, suffix = location.rpartition(":")
        if separator and suffix.isdigit():
            file_name = prefix
            line_number = int(suffix)
    return ThreadFrame(
        class_name=truncate_text(class_name, 512),
        method=truncate_text(method, 256),
        file=truncate_text(file_name, 256) if file_name else None,
        line=line_number,
        frame_index=index,
    )
