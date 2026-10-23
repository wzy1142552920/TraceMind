"""Read-only tools over user-provided JVM text snapshots."""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable
from typing import Any, cast

from pydantic import BaseModel, Field, field_validator

from tracemind.artifacts import ArtifactBundle, ArtifactDocument, ArtifactKind
from tracemind.artifacts.parsers import (
    GcEvent,
    HeapClassStat,
    ThreadSnapshot,
    parse_gc_log,
    parse_heap_histogram,
    parse_thread_cpu,
    parse_thread_dump,
)
from tracemind.artifacts.parsers.common import normalize_nid
from tracemind.tools.contracts import (
    EvidenceToolMeta,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolHandler,
    ToolHandlerResult,
    ToolSpec,
)
from tracemind.tools.registry import ToolRegistry

_SNAPSHOT_NOTE = (
    "Read-only query over a user-provided point-in-time JVM text snapshot; "
    "not live collection."
)
_CLASS_PATTERN_RE = re.compile(
    r"^[A-Za-z0-9._$*?]+(?: [A-Za-z0-9._$*?]+)*$"
)

MAX_TOOL_ITEMS_BYTES = 24_000
MAX_WARNINGS = 20
MAX_FRAMES = 8
MAX_HOT_FRAMES = 3
MAX_DEADLOCKS = 50


class GetThreadDumpArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_thread_dump``."""

    thread_name: str | None = Field(default=None, min_length=1, max_length=128)
    state: str | None = Field(default=None, min_length=1, max_length=32)
    deadlock_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class GetHotThreadsArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_hot_threads``."""

    limit: int = Field(default=10, ge=1, le=100)
    min_cpu_percent: float = Field(default=1.0, ge=0.0, le=100.0)


class GetDeadlocksArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_deadlocks``."""


class GetGcSummaryArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_gc_summary``."""

    full_only: bool = False


class GetGcEventsArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_gc_events``."""

    limit: int = Field(default=20, ge=1, le=100)
    full_only: bool = False


class GetHeapHistogramArgs(EvidenceToolMeta):
    """Arguments for ``jvm.get_heap_histogram``."""

    limit: int = Field(default=20, ge=1, le=100)
    class_pattern: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("class_pattern")
    @classmethod
    def _validate_class_pattern(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _CLASS_PATTERN_RE.fullmatch(value) is None:
            raise ValueError(
                "class_pattern allows only letters, digits, '.', '_', '$', "
                "'*', '?' and single spaces"
            )
        return value


def register_jvm_tools(
    registry: ToolRegistry,
    artifacts: ArtifactBundle,
) -> None:
    """Register JVM tools only for artifact kinds present in the bundle."""
    kinds = {document.kind for document in artifacts.documents}
    has_dump = ArtifactKind.THREAD_DUMP in kinds
    has_cpu = ArtifactKind.THREAD_CPU in kinds

    if has_dump:
        registry.register(
            ToolSpec(
                name="jvm.get_thread_dump",
                description=(
                    "Return bounded thread states, stack frames, lock lines, and "
                    "deadlocks from a user-provided jstack thread dump. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetThreadDumpArgs,
            ),
            _get_thread_dump_handler(artifacts),
        )
        registry.register(
            ToolSpec(
                name="jvm.get_deadlocks",
                description=(
                    "Return Java-level deadlocks explicitly reported in a "
                    "user-provided jstack thread dump. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetDeadlocksArgs,
            ),
            _get_deadlocks_handler(artifacts),
        )
    if has_dump and has_cpu:
        registry.register(
            ToolSpec(
                name="jvm.get_hot_threads",
                description=(
                    "Combine a user-provided top -H/ps -L thread CPU snapshot "
                    "with a jstack thread dump, map TIDs to nids, and return the "
                    "highest-CPU threads with matched stack heads. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetHotThreadsArgs,
            ),
            _get_hot_threads_handler(artifacts),
        )
    if ArtifactKind.GC_LOG in kinds:
        registry.register(
            ToolSpec(
                name="jvm.get_gc_summary",
                description=(
                    "Summarize Young/Full GC counts, pauses, heap before/after, "
                    "and promotion failures from a user-provided GC log. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetGcSummaryArgs,
            ),
            _get_gc_summary_handler(artifacts),
        )
        registry.register(
            ToolSpec(
                name="jvm.get_gc_events",
                description=(
                    "Return recent GC events from a user-provided GC log; "
                    "optionally restrict to Full GC. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetGcEventsArgs,
            ),
            _get_gc_events_handler(artifacts),
        )
    if ArtifactKind.HEAP_HISTOGRAM in kinds:
        registry.register(
            ToolSpec(
                name="jvm.get_heap_histogram",
                description=(
                    "Return top classes by retained bytes from a user-provided "
                    "jmap -histo[:live] snapshot, with an optional class filter. "
                    f"{_SNAPSHOT_NOTE}"
                ),
                input_model=GetHeapHistogramArgs,
            ),
            _get_heap_histogram_handler(artifacts),
        )


def _get_thread_dump_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetThreadDumpArgs, args)
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        document = _document(bundle, ArtifactKind.THREAD_DUMP, warnings)
        summary = parse_thread_dump(document.lines)
        _merge_warnings(warnings, document.warnings)
        _merge_warnings(warnings, summary.warnings)

        filtered = [
            thread
            for thread in summary.threads
            if _thread_matches(thread, params)
        ]
        items = [
            _thread_item(thread, document.artifact_id)
            for thread in filtered[: params.limit]
        ]
        items, fit_truncated = _fit_items(
            items,
            warnings,
            "thread dump",
        )
        if not items and summary.threads:
            _warn(warnings, "no threads matched the requested filters")

        deadlock_items = [
            _deadlock_item(deadlock, document.artifact_id)
            for deadlock in summary.deadlocks[:MAX_DEADLOCKS]
        ]
        if len(summary.deadlocks) > MAX_DEADLOCKS:
            _warn(warnings, f"deadlock output truncated at {MAX_DEADLOCKS}")
        truncated = (
            summary.truncated
            or len(filtered) > params.limit
            or fit_truncated
            or len(summary.deadlocks) > MAX_DEADLOCKS
        )
        source_refs = [item["source_ref"] for item in items]
        source_refs.extend(item["source_ref"] for item in deadlock_items)
        data = {
            "threads": items,
            "deadlocks": deadlock_items,
            "artifact_ids": [document.artifact_id],
            "source_refs": source_refs,
            "warnings": warnings,
            "truncated": truncated,
        }
        return ToolHandlerResult(
            data=data,
            source_ref=source_refs[0] if source_refs else None,
            truncated=truncated,
        )

    return handler


def _get_hot_threads_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetHotThreadsArgs, args)
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        cpu_document = _document(bundle, ArtifactKind.THREAD_CPU, warnings)
        dump_document = _document(bundle, ArtifactKind.THREAD_DUMP, warnings)
        cpu = parse_thread_cpu(cpu_document.lines)
        dump = parse_thread_dump(dump_document.lines)
        _merge_warnings(warnings, cpu_document.warnings)
        _merge_warnings(warnings, dump_document.warnings)
        _merge_warnings(warnings, cpu.warnings)
        _merge_warnings(warnings, dump.warnings)

        threads_by_nid: dict[str, ThreadSnapshot] = {}
        for thread in dump.threads:
            normalized = normalize_nid(thread.nid)
            if normalized is not None:
                threads_by_nid.setdefault(normalized, thread)

        eligible = [
            sample
            for sample in cpu.samples
            if sample.cpu_percent >= params.min_cpu_percent
        ]
        selected = eligible[: params.limit]
        items: list[dict[str, Any]] = []
        for sample in selected:
            sample_nid = normalize_nid(sample.tid_hex)
            matched = threads_by_nid.get(sample_nid) if sample_nid else None
            items.append(
                {
                    "source_ref": _artifact_ref(
                        cpu_document.artifact_id,
                        sample.line_number,
                        sample.line_number,
                    ),
                    "tid_decimal": sample.tid_decimal,
                    "tid_hex": sample.tid_hex,
                    "cpu_percent": sample.cpu_percent,
                    "command": sample.command,
                    "line_number": sample.line_number,
                    "thread_name": matched.name if matched else None,
                    "state": matched.state if matched else None,
                    "matched_thread": (
                        _hot_thread_item(matched, dump_document.artifact_id)
                        if matched
                        else None
                    ),
                }
            )
        items, fit_truncated = _fit_items(items, warnings, "hot thread")
        unmatched_tids = [
            int(item["tid_decimal"])
            for item in items
            if item["matched_thread"] is None
        ]
        if unmatched_tids:
            _warn(
                warnings,
                f"{len(unmatched_tids)} CPU sample(s) did not match a "
                "thread dump nid",
            )
        if not eligible:
            _warn(warnings, "no CPU samples matched min_cpu_percent")
        truncated = (
            cpu.truncated
            or dump.truncated
            or len(eligible) > params.limit
            or fit_truncated
        )
        source_refs = [item["source_ref"] for item in items]
        data = {
            "samples": items,
            "unmatched_tids": unmatched_tids,
            "artifact_ids": [
                cpu_document.artifact_id,
                dump_document.artifact_id,
            ],
            "source_refs": source_refs,
            "warnings": warnings,
            "truncated": truncated,
        }
        return ToolHandlerResult(
            data=data,
            source_ref=source_refs[0] if source_refs else None,
            truncated=truncated,
        )

    return handler


def _get_deadlocks_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        del args
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        document = _document(bundle, ArtifactKind.THREAD_DUMP, warnings)
        summary = parse_thread_dump(document.lines)
        _merge_warnings(warnings, document.warnings)
        _merge_warnings(warnings, summary.warnings)

        items = [
            _deadlock_item(deadlock, document.artifact_id)
            for deadlock in summary.deadlocks[:MAX_DEADLOCKS]
        ]
        if not summary.deadlocks:
            _warn(
                warnings,
                "no Java-level deadlocks reported in the thread dump",
            )
        if len(summary.deadlocks) > MAX_DEADLOCKS:
            _warn(warnings, f"deadlock output truncated at {MAX_DEADLOCKS}")
        truncated = summary.truncated or len(summary.deadlocks) > MAX_DEADLOCKS
        source_refs = [item["source_ref"] for item in items]
        data = {
            "deadlocks": items,
            "artifact_ids": [document.artifact_id],
            "source_refs": source_refs,
            "warnings": warnings,
            "truncated": truncated,
        }
        return ToolHandlerResult(
            data=data,
            source_ref=source_refs[0] if source_refs else None,
            truncated=truncated,
        )

    return handler


def _get_gc_summary_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetGcSummaryArgs, args)
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        document = _document(bundle, ArtifactKind.GC_LOG, warnings)
        result = parse_gc_log(document.lines)
        _merge_warnings(warnings, document.warnings)
        _merge_warnings(warnings, result.summary.warnings)

        source_ref = _artifact_ref(
            document.artifact_id,
            1,
            document.line_count,
        )
        data: dict[str, Any] = {
            "summary": result.summary.model_dump(),
            "full_only": params.full_only,
            "source_ref": source_ref,
            "artifact_ids": [document.artifact_id],
            "source_refs": [source_ref],
            "warnings": warnings,
            "truncated": result.truncated,
        }
        if params.full_only:
            full_events = [
                event for event in result.events if event.event_type == "full"
            ]
            pauses = [
                event.pause_ms
                for event in full_events
                if event.pause_ms is not None
            ]
            data["full_scope"] = {
                "event_count_in_retained_window": len(full_events),
                "max_pause_ms": round(max(pauses), 3) if pauses else None,
                "total_pause_ms": round(sum(pauses), 3) if pauses else 0.0,
                "window_truncated": result.truncated,
            }
            if not full_events:
                _warn(warnings, "no Full GC events found")
            if result.truncated:
                _warn(
                    warnings,
                    "full-only aggregates use the most recent retained GC events",
                )
        return ToolHandlerResult(
            data=data,
            source_ref=source_ref,
            truncated=result.truncated,
        )

    return handler


def _get_gc_events_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetGcEventsArgs, args)
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        document = _document(bundle, ArtifactKind.GC_LOG, warnings)
        result = parse_gc_log(document.lines)
        _merge_warnings(warnings, document.warnings)
        _merge_warnings(warnings, result.summary.warnings)

        filtered = (
            [event for event in result.events if event.event_type == "full"]
            if params.full_only
            else list(result.events)
        )
        selected = filtered[-params.limit :]
        items = [_gc_event_item(event, document.artifact_id) for event in selected]
        items, fit_truncated = _fit_items(items, warnings, "GC event")
        if not items and params.full_only:
            _warn(warnings, "no Full GC events matched the requested filter")
        truncated = (
            result.truncated
            or len(filtered) > params.limit
            or fit_truncated
        )
        source_refs = [item["source_ref"] for item in items]
        data = {
            "events": items,
            "artifact_ids": [document.artifact_id],
            "source_refs": source_refs,
            "warnings": warnings,
            "truncated": truncated,
        }
        return ToolHandlerResult(
            data=data,
            source_ref=source_refs[-1] if source_refs else None,
            truncated=truncated,
        )

    return handler


def _get_heap_histogram_handler(fallback: ArtifactBundle) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetHeapHistogramArgs, args)
        warnings: list[str] = []
        bundle = _bundle(context, fallback)
        document = _document(bundle, ArtifactKind.HEAP_HISTOGRAM, warnings)
        result = parse_heap_histogram(document.lines)
        _merge_warnings(warnings, document.warnings)
        _merge_warnings(warnings, result.warnings)

        filtered = [
            item
            for item in result.classes
            if params.class_pattern is None
            or _class_matches(item.class_name, params.class_pattern)
        ]
        selected = filtered[: params.limit]
        items = [_heap_class_item(item) for item in selected]
        items, fit_truncated = _fit_items(items, warnings, "heap histogram")
        if not items and result.classes:
            _warn(warnings, "no heap classes matched class_pattern")
        source_ref = _artifact_ref(
            document.artifact_id,
            1,
            document.line_count,
        )
        truncated = (
            result.truncated
            or len(filtered) > params.limit
            or fit_truncated
        )
        data = {
            "live": result.live,
            "classes": items,
            "total_instances": result.total_instances,
            "total_bytes": result.total_bytes,
            "source_ref": source_ref,
            "artifact_ids": [document.artifact_id],
            "source_refs": [source_ref],
            "warnings": warnings,
            "truncated": truncated,
        }
        return ToolHandlerResult(
            data=data,
            source_ref=source_ref,
            truncated=truncated,
        )

    return handler


def _bundle(context: ToolContext, fallback: ArtifactBundle) -> ArtifactBundle:
    bundle = context.artifacts or fallback
    if bundle is None:  # defensive: registration always provides a bundle
        raise ToolError(
            ToolErrorCode.TOOL_ERROR,
            "artifact bundle is not available",
        )
    return bundle


def _document(
    bundle: ArtifactBundle,
    kind: ArtifactKind,
    warnings: list[str],
) -> ArtifactDocument:
    documents = bundle.by_kind(kind)
    if not documents:
        raise ToolError(
            ToolErrorCode.TOOL_ERROR,
            f"no {kind.value} artifact is available",
        )
    if len(documents) > 1:
        _warn(
            warnings,
            f"multiple {kind.value} artifacts; using {documents[0].artifact_id}",
        )
    return documents[0]


def _thread_matches(
    thread: ThreadSnapshot,
    params: GetThreadDumpArgs,
) -> bool:
    if (
        params.thread_name is not None
        and params.thread_name.lower() not in thread.name.lower()
    ):
        return False
    if params.state is not None:
        expected = params.state.strip().upper()
        if (thread.state or "").upper() != expected:
            return False
    if params.deadlock_only and not thread.deadlock_related:
        return False
    return True


def _thread_item(
    thread: ThreadSnapshot,
    artifact_id: str,
) -> dict[str, Any]:
    return {
        "source_ref": _artifact_ref(
            artifact_id,
            thread.line_start,
            thread.line_end,
        ),
        "name": thread.name,
        "java_id": thread.java_id,
        "nid": thread.nid,
        "state": thread.state,
        "daemon": thread.daemon,
        "line_start": thread.line_start,
        "line_end": thread.line_end,
        "frames": [
            _frame_item(frame) for frame in thread.frames[:MAX_FRAMES]
        ],
        "lock_events": list(thread.lock_events),
        "deadlock_related": thread.deadlock_related,
    }


def _hot_thread_item(
    thread: ThreadSnapshot,
    artifact_id: str,
) -> dict[str, Any]:
    return {
        "source_ref": _artifact_ref(
            artifact_id,
            thread.line_start,
            thread.line_end,
        ),
        "name": thread.name,
        "nid": thread.nid,
        "state": thread.state,
        "daemon": thread.daemon,
        "line_start": thread.line_start,
        "line_end": thread.line_end,
        "top_frames": [
            _frame_item(frame) for frame in thread.frames[:MAX_HOT_FRAMES]
        ],
        "deadlock_related": thread.deadlock_related,
    }


def _frame_item(frame: Any) -> dict[str, Any]:
    return {
        "class_name": frame.class_name,
        "method": frame.method,
        "file": frame.file,
        "line": frame.line,
        "frame_index": frame.frame_index,
    }


def _deadlock_item(deadlock: Any, artifact_id: str) -> dict[str, Any]:
    return {
        "source_ref": _artifact_ref(
            artifact_id,
            deadlock.line_start,
            deadlock.line_end,
        ),
        "threads": list(deadlock.threads),
        "lock_ids": list(deadlock.lock_ids),
        "line_start": deadlock.line_start,
        "line_end": deadlock.line_end,
    }


def _gc_event_item(event: GcEvent, artifact_id: str) -> dict[str, Any]:
    return {
        "source_ref": _artifact_ref(
            artifact_id,
            event.line_number,
            event.line_number,
        ),
        **event.model_dump(),
    }


def _heap_class_item(item: HeapClassStat) -> dict[str, Any]:
    return item.model_dump()


def _class_matches(class_name: str, pattern: str) -> bool:
    lowered_name = class_name.lower()
    lowered_pattern = pattern.lower()
    if "*" in lowered_pattern or "?" in lowered_pattern:
        return fnmatch.fnmatchcase(lowered_name, lowered_pattern)
    return lowered_pattern in lowered_name


def _artifact_ref(artifact_id: str, start: int, end: int) -> str:
    if start == end:
        return f"artifact://{artifact_id}#L{start}"
    return f"artifact://{artifact_id}#L{start}-L{end}"


def _fit_items(
    items: list[dict[str, Any]],
    warnings: list[str],
    label: str,
) -> tuple[list[dict[str, Any]], bool]:
    kept: list[dict[str, Any]] = []
    total = 2
    for item in items:
        size = len(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        )
        if kept and total + size > MAX_TOOL_ITEMS_BYTES:
            _warn(warnings, f"{label} output truncated to the tool byte bound")
            return kept, True
        kept.append(item)
        total += size + 1
    return kept, len(kept) < len(items)


def _merge_warnings(warnings: list[str], values: Iterable[str]) -> None:
    for value in values:
        _warn(warnings, value)


def _warn(warnings: list[str], message: str) -> None:
    if message in warnings or len(warnings) >= MAX_WARNINGS:
        return
    warnings.append(message)
