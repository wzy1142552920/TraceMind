"""Deterministic tool-result to evidence mapping for the v0.3 runtime."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

from tracemind.diagnosis.evidence import EvidenceKind, EvidenceProvenance
from tracemind.tools.contracts import ToolResult

if TYPE_CHECKING:
    from tracemind.artifacts import ArtifactBundle

Strength = Literal["strong", "medium", "weak"]

_ARTIFACT_REF_RE = re.compile(
    r"^artifact://(?P<artifact_id>[a-z][a-z0-9_-]{0,31})"
    r"#L(?P<start>\d+)(?:-L(?P<end>\d+))?$"
)
_MAX_MAPPING_WARNINGS = 20


@dataclass(frozen=True)
class EvidenceDraft:
    """Evidence fields derived from a tool result before ledger insertion."""

    kind: EvidenceKind
    claim: str
    source_ref: str
    strength: Strength
    provenance: EvidenceProvenance
    content: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MappingOutcome:
    """Drafts plus non-fatal mapping failures."""

    drafts: list[EvidenceDraft] = field(default_factory=list)
    failure_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def map_tool_result(
    result: ToolResult,
    artifacts: ArtifactBundle | None = None,
) -> MappingOutcome:
    """Map one successful evidence-tool result into reviewable evidence drafts."""
    if not result.ok:
        return MappingOutcome()

    name = result.tool_name
    data = result.data
    if name in {"logs.search", "logs.get_event_context"}:
        return _map_log_events(data)
    if name == "logs.get_thread_context":
        return _map_thread_context(data)
    if name == "code.find_symbol":
        return _map_symbol_items(data)
    if name == "code.get_symbol":
        return _map_symbol(data)
    if name == "code.get_source_range":
        return _map_source_range(data)
    if name in {"code.get_callers", "code.get_callees"}:
        return _map_call_edges(data)
    if name == "code.find_sql":
        return _map_sql(data)
    if name == "db.describe_table":
        return _map_table(data)
    if name == "db.get_row":
        return _map_row(data)
    if name == "jvm.get_thread_dump":
        return _map_jvm_threads(data, artifacts)
    if name == "jvm.get_hot_threads":
        return _map_jvm_hot_threads(data, artifacts)
    if name == "jvm.get_deadlocks":
        return _map_jvm_deadlocks(data, artifacts)
    if name == "jvm.get_gc_summary":
        return _map_jvm_gc_summary(data, artifacts)
    if name == "jvm.get_gc_events":
        return _map_jvm_gc_events(data, artifacts)
    if name == "jvm.get_heap_histogram":
        return _map_jvm_heap(data, artifacts)
    return MappingOutcome()


def _map_log_events(data: Any) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _failure("logs: expected items[]")
    drafts: list[EvidenceDraft] = []
    for item in data["items"]:
        if not isinstance(item, dict):
            return _failure("logs: item is not an object")
        source_ref = item.get("source_ref")
        event_id = item.get("event_id")
        if not isinstance(source_ref, str) or not isinstance(event_id, str):
            return _failure("logs: item missing event_id/source_ref")
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.LOG_EVENT,
                claim=_truncate(
                    f"Log event {event_id}: {_text(item.get('message'))}",
                    240,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.TOOL,
                content={
                    key: item.get(key)
                    for key in ("event_id", "thread", "logger", "level")
                    if item.get(key) is not None
                },
            )
        )
    return MappingOutcome(drafts=drafts)


def _map_thread_context(data: Any) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("logs.get_thread_context: result is not an object")
    thread = data.get("thread")
    source_ref = data.get("source_ref")
    anchor = data.get("anchor_event_id")
    items = data.get("items")
    if (
        not isinstance(thread, str)
        or not isinstance(source_ref, str)
        or not isinstance(anchor, str)
        or not isinstance(items, list)
    ):
        return _failure(
            "logs.get_thread_context: missing thread/source_ref/anchor/items"
        )
    messages = [
        _text(item.get("message"))
        for item in items
        if isinstance(item, dict)
    ][:3]
    return MappingOutcome(
        drafts=[
            EvidenceDraft(
                kind=EvidenceKind.LOG_THREAD_CONTEXT,
                claim=_truncate(
                    f"Thread {thread} around {anchor}: " + "; ".join(messages),
                    300,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "thread": thread,
                    "anchor_event_id": anchor,
                    "line_start": data.get("line_start"),
                    "line_end": data.get("line_end"),
                    "items": items,
                    "count": data.get("count"),
                },
            )
        ]
    )


def _map_symbol_items(data: Any) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _failure("code.find_symbol: expected items[]")
    drafts: list[EvidenceDraft] = []
    for item in data["items"]:
        if not isinstance(item, dict):
            return _failure("code.find_symbol: item is not an object")
        file_path = item.get("file_path")
        start = item.get("start_line")
        end = item.get("end_line")
        if (
            not isinstance(file_path, str)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            return _failure("code.find_symbol: item missing file/range")
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str):
            source_ref = _repo_range_ref(file_path, start, end)
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.SOURCE_CODE,
                claim=_truncate(
                    f"Source {_text(item.get('fqn'))}"
                    f"{'.' + _text(item.get('method_name')) if item.get('method_name') else ''}"
                    f" at {file_path}:{start}-{end}",
                    240,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "symbol_id": item.get("symbol_id"),
                },
            )
        )
        annotation_outcome = _annotations(item, file_path)
        if annotation_outcome.failure_reason is not None:
            return annotation_outcome
        drafts.extend(annotation_outcome.drafts)
    return MappingOutcome(drafts=drafts)


def _map_symbol(data: Any) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("code.get_symbol: result is not an object")
    file_path = data.get("file_path")
    start = data.get("start_line")
    end = data.get("end_line")
    source_ref = data.get("source_ref")
    if (
        not isinstance(file_path, str)
        or not isinstance(start, int)
        or not isinstance(end, int)
    ):
        return _failure("code.get_symbol: missing file/range")
    if not isinstance(source_ref, str):
        source_ref = _repo_range_ref(file_path, start, end)
    drafts = [
        EvidenceDraft(
            kind=EvidenceKind.SOURCE_CODE,
            claim=_truncate(
                f"Source {_text(data.get('fqn'))} at "
                f"{file_path}:{start}-{end}",
                240,
            ),
            source_ref=source_ref,
            strength="strong",
            provenance=EvidenceProvenance.TOOL,
            content={
                "file_path": file_path,
                "start_line": start,
                "end_line": end,
                "symbol_id": data.get("symbol_id"),
            },
        )
    ]
    annotations = _annotations(data, file_path)
    if annotations.failure_reason is not None:
        return annotations
    drafts.extend(annotations.drafts)
    return MappingOutcome(drafts=drafts)


def _map_source_range(data: Any) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("code.get_source_range: result is not an object")
    file_path = data.get("file_path")
    start = data.get("start_line")
    end = data.get("end_line")
    if (
        not isinstance(file_path, str)
        or not isinstance(start, int)
        or not isinstance(end, int)
    ):
        return _failure("code.get_source_range: missing file/range")
    return MappingOutcome(
        drafts=[
            EvidenceDraft(
                kind=EvidenceKind.SOURCE_CODE,
                claim=f"Source range {file_path}:{start}-{end}",
                source_ref=_repo_range_ref(file_path, start, end),
                strength="strong",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "file_path": file_path,
                    "start_line": start,
                    "end_line": end,
                    "text": data.get("text"),
                },
            )
        ]
    )


def _map_call_edges(data: Any) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _failure("code call edges: expected items[]")
    drafts: list[EvidenceDraft] = []
    for item in data["items"]:
        if not isinstance(item, dict):
            return _failure("code call edges: item is not an object")
        source_ref = item.get("source_ref")
        line = item.get("line")
        if not isinstance(source_ref, str) or not isinstance(line, int):
            return _failure("code call edges: item missing source_ref/line")
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.CALL_PATH,
                claim=_truncate(
                    f"AST candidate call {_text(item.get('caller_fqn'))} -> "
                    f"{_text(item.get('callee_fqn'))} at line {line} "
                    f"(confidence={item.get('confidence')})",
                    300,
                ),
                source_ref=source_ref,
                strength="medium",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "caller_symbol_id": item.get("caller_symbol_id"),
                    "callee_symbol_id": item.get("callee_symbol_id"),
                    "line": line,
                    "confidence": item.get("confidence"),
                },
            )
        )
    return MappingOutcome(drafts=drafts)


def _map_sql(data: Any) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return _failure("code.find_sql: expected items[]")
    drafts: list[EvidenceDraft] = []
    for item in data["items"]:
        if not isinstance(item, dict):
            return _failure("code.find_sql: item is not an object")
        source_ref = item.get("source_ref")
        start = item.get("start_line")
        if not isinstance(source_ref, str) or not isinstance(start, int):
            return _failure("code.find_sql: item missing source_ref/start_line")
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.SQL,
                claim=_truncate(
                    f"SQL {_text(item.get('statement_type'))} on "
                    f"{', '.join(str(v) for v in item.get('tables') or []) or 'unknown'}"
                    f" at {_text(item.get('file_path'))}:{start}",
                    240,
                ),
                source_ref=source_ref,
                strength="medium",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "sql_text": item.get("sql_text"),
                    "statement_type": item.get("statement_type"),
                    "tables": item.get("tables"),
                    "symbol_id": item.get("symbol_id"),
                },
            )
        )
    return MappingOutcome(drafts=drafts)


def _map_table(data: Any) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("db.describe_table: result is not an object")
    table = data.get("table")
    source_ref = data.get("source_ref")
    if not isinstance(table, str) or not isinstance(source_ref, str):
        return _failure("db.describe_table: missing table/source_ref")
    return MappingOutcome(
        drafts=[
            EvidenceDraft(
                kind=EvidenceKind.DB_SCHEMA,
                claim=f"Fixture schema for table {table}",
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.FAKE_VERIFICATION,
                content={
                    "table": table,
                    "columns": data.get("columns"),
                    "primary_key": data.get("primary_key"),
                    "row_count": data.get("row_count"),
                    "environment": data.get("environment"),
                },
            )
        ]
    )


def _map_row(data: Any) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("db.get_row: result is not an object")
    table = data.get("table")
    key_column = data.get("key_column")
    key_value = data.get("key_value")
    found = data.get("found")
    source_ref = data.get("source_ref")
    if (
        not isinstance(table, str)
        or not isinstance(key_column, str)
        or not isinstance(found, bool)
        or not isinstance(source_ref, str)
    ):
        return _failure("db.get_row: missing table/key/found/source_ref")
    return MappingOutcome(
        drafts=[
            EvidenceDraft(
                kind=EvidenceKind.DB_ROW,
                claim=(
                    f"Fixture row {table} {key_column}={key_value}: "
                    f"{'found' if found else 'not found'}"
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.FAKE_VERIFICATION,
                content={
                    "table": table,
                    "key_column": key_column,
                    "key_value": key_value,
                    "found": found,
                    "row": data.get("row"),
                    "redacted_columns": data.get("redacted_columns"),
                    "environment": data.get("environment"),
                },
            )
        ]
    )


def _map_jvm_threads(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("threads"), list):
        return _failure("jvm.get_thread_dump: expected threads[]")
    drafts: list[EvidenceDraft] = []
    warnings: list[str] = []
    for item in data["threads"]:
        if not isinstance(item, dict):
            _warn_mapping(warnings, "jvm.get_thread_dump: item is not an object")
            continue
        source_ref = item.get("source_ref")
        if not _valid_artifact_ref(
            source_ref,
            artifacts,
            warnings,
            "jvm.get_thread_dump",
        ):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            _warn_mapping(warnings, "jvm.get_thread_dump: item missing name")
            continue
        drafts.append(_thread_draft(item, source_ref))
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _map_jvm_hot_threads(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        return _failure("jvm.get_hot_threads: expected samples[]")
    drafts: list[EvidenceDraft] = []
    warnings: list[str] = []
    for item in data["samples"]:
        if not isinstance(item, dict):
            _warn_mapping(warnings, "jvm.get_hot_threads: item is not an object")
            continue
        source_ref = item.get("source_ref")
        if not _valid_artifact_ref(
            source_ref,
            artifacts,
            warnings,
            "jvm.get_hot_threads",
        ):
            continue
        tid = item.get("tid_decimal")
        cpu_percent = item.get("cpu_percent")
        if (
            not isinstance(tid, int)
            or isinstance(tid, bool)
            or not isinstance(cpu_percent, (int, float))
            or isinstance(cpu_percent, bool)
        ):
            _warn_mapping(
                warnings,
                "jvm.get_hot_threads: item missing tid_decimal/cpu_percent",
            )
            continue
        tid_hex = _text(item.get("tid_hex"))
        command = _truncate(_text(item.get("command")), 128)
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.THREAD_CPU,
                claim=_truncate(
                    f"Thread {command or tid} used {float(cpu_percent):.1f}% CPU "
                    f"(tid={tid}, nid={tid_hex}) at {source_ref}",
                    240,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.USER_ARTIFACT,
                content={
                    "tid_decimal": tid,
                    "tid_hex": tid_hex,
                    "cpu_percent": float(cpu_percent),
                    "command": command or None,
                    "line_number": item.get("line_number"),
                    "thread_name": item.get("thread_name"),
                    "state": item.get("state"),
                },
            )
        )
        matched = item.get("matched_thread")
        if isinstance(matched, dict):
            matched_ref = matched.get("source_ref")
            if _valid_artifact_ref(
                matched_ref,
                artifacts,
                warnings,
                "jvm.get_hot_threads matched thread",
            ):
                drafts.append(_thread_draft(matched, matched_ref))
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _map_jvm_deadlocks(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("deadlocks"), list):
        return _failure("jvm.get_deadlocks: expected deadlocks[]")
    drafts: list[EvidenceDraft] = []
    warnings: list[str] = []
    for item in data["deadlocks"]:
        if not isinstance(item, dict):
            _warn_mapping(warnings, "jvm.get_deadlocks: item is not an object")
            continue
        source_ref = item.get("source_ref")
        if not _valid_artifact_ref(
            source_ref,
            artifacts,
            warnings,
            "jvm.get_deadlocks",
        ):
            continue
        threads = _bounded_strings(item.get("threads"), 16, 512)
        lock_ids = _bounded_strings(item.get("lock_ids"), 16, 64)
        if not threads and not lock_ids:
            _warn_mapping(
                warnings,
                "jvm.get_deadlocks: deadlock item has no threads or locks",
            )
            continue
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.THREAD_DUMP,
                claim=_truncate(
                    "JVM deadlock involving "
                    + (", ".join(threads[:4]) or "unknown threads")
                    + f" at {source_ref}",
                    240,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.USER_ARTIFACT,
                content={
                    "threads": threads,
                    "lock_ids": lock_ids,
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                },
            )
        )
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _map_jvm_gc_summary(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict):
        return _failure("jvm.get_gc_summary: result is not an object")
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return _failure("jvm.get_gc_summary: missing summary object")
    warnings: list[str] = []
    source_ref = data.get("source_ref")
    if not _valid_artifact_ref(
        source_ref,
        artifacts,
        warnings,
        "jvm.get_gc_summary",
    ):
        return MappingOutcome(warnings=warnings)
    total_events = summary.get("total_events")
    if not isinstance(total_events, int) or total_events <= 0:
        _warn_mapping(warnings, "jvm.get_gc_summary: no GC events found")
        return MappingOutcome(warnings=warnings)
    content: dict[str, Any] = {
        "summary": summary,
        "full_only": data.get("full_only") is True,
    }
    full_scope = data.get("full_scope")
    if isinstance(full_scope, dict):
        content["full_scope"] = full_scope
    drafts = [
        EvidenceDraft(
            kind=EvidenceKind.GC_SUMMARY,
            claim=_truncate(
                f"GC summary: {total_events} events "
                f"({summary.get('full_events')} full), "
                f"max pause {summary.get('max_pause_ms')} ms, "
                f"promotion failures {summary.get('promotion_failures')} "
                f"at {source_ref}",
                240,
            ),
            source_ref=source_ref,
            strength="strong",
            provenance=EvidenceProvenance.USER_ARTIFACT,
            content=content,
        )
    ]
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _map_jvm_gc_events(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return _failure("jvm.get_gc_events: expected events[]")
    drafts: list[EvidenceDraft] = []
    warnings: list[str] = []
    for item in data["events"]:
        if not isinstance(item, dict):
            _warn_mapping(warnings, "jvm.get_gc_events: item is not an object")
            continue
        source_ref = item.get("source_ref")
        if not _valid_artifact_ref(
            source_ref,
            artifacts,
            warnings,
            "jvm.get_gc_events",
        ):
            continue
        event_type = item.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            _warn_mapping(warnings, "jvm.get_gc_events: item missing event_type")
            continue
        cause = _truncate(_text(item.get("cause")), 128)
        pause_ms = item.get("pause_ms")
        pause_text = f"{pause_ms} ms" if pause_ms is not None else "unknown pause"
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.GC_EVENT,
                claim=_truncate(
                    f"{event_type.upper()} GC {cause or '(unknown cause)'}: "
                    f"{pause_text}, heap {item.get('heap_before_mb')}->"
                    f"{item.get('heap_after_mb')}/{item.get('heap_total_mb')} "
                    f"MiB at {source_ref}",
                    240,
                ),
                source_ref=source_ref,
                strength="strong",
                provenance=EvidenceProvenance.USER_ARTIFACT,
                content={
                    "event_type": event_type,
                    "cause": cause or None,
                    "heap_before_mb": item.get("heap_before_mb"),
                    "heap_after_mb": item.get("heap_after_mb"),
                    "heap_total_mb": item.get("heap_total_mb"),
                    "pause_ms": pause_ms,
                    "line_number": item.get("line_number"),
                    "summary": _truncate(_text(item.get("summary")), 512),
                },
            )
        )
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _map_jvm_heap(
    data: Any,
    artifacts: ArtifactBundle | None,
) -> MappingOutcome:
    if not isinstance(data, dict) or not isinstance(data.get("classes"), list):
        return _failure("jvm.get_heap_histogram: expected classes[]")
    warnings: list[str] = []
    source_ref = data.get("source_ref")
    if not _valid_artifact_ref(
        source_ref,
        artifacts,
        warnings,
        "jvm.get_heap_histogram",
    ):
        return MappingOutcome(warnings=warnings)
    classes = [
        item
        for item in data["classes"]
        if isinstance(item, dict)
    ][:50]
    if not classes:
        _warn_mapping(
            warnings,
            "jvm.get_heap_histogram: no heap classes found",
        )
        return MappingOutcome(warnings=warnings)
    top = classes[0]
    top_name = _truncate(_text(top.get("class_name")), 240)
    content_classes = [
        {
            "rank": item.get("rank"),
            "instances": item.get("instances"),
            "bytes": item.get("bytes"),
            "class_name": _truncate(_text(item.get("class_name")), 512),
            "line_number": item.get("line_number"),
        }
        for item in classes
    ]
    drafts = [
        EvidenceDraft(
            kind=EvidenceKind.HEAP_SUMMARY,
            claim=_truncate(
                f"Heap histogram: {len(classes)} classes, top {top_name} "
                f"({top.get('instances')} instances, {top.get('bytes')} bytes), "
                f"live={data.get('live') is True} at {source_ref}",
                240,
            ),
            source_ref=source_ref,
            strength="strong",
            provenance=EvidenceProvenance.USER_ARTIFACT,
            content={
                "live": data.get("live") is True,
                "classes": content_classes,
                "total_instances": data.get("total_instances"),
                "total_bytes": data.get("total_bytes"),
            },
        )
    ]
    return MappingOutcome(drafts=drafts, warnings=warnings)


def _thread_draft(item: dict[str, Any], source_ref: str) -> EvidenceDraft:
    name = _truncate(_text(item.get("name")), 120)
    state = _text(item.get("state")) or "unknown"
    return EvidenceDraft(
        kind=EvidenceKind.THREAD_DUMP,
        claim=_truncate(
            f"Thread {name} state={state} at {source_ref}",
            240,
        ),
        source_ref=source_ref,
        strength="strong",
        provenance=EvidenceProvenance.USER_ARTIFACT,
        content=_thread_content(item),
    )


def _thread_content(item: dict[str, Any]) -> dict[str, Any]:
    frames = item.get("frames")
    if not isinstance(frames, list):
        frames = item.get("top_frames")
    return {
        "name": _truncate(_text(item.get("name")), 512),
        "java_id": item.get("java_id"),
        "nid": item.get("nid"),
        "state": item.get("state"),
        "daemon": item.get("daemon") is True,
        "line_start": item.get("line_start"),
        "line_end": item.get("line_end"),
        "frames": _bounded_frames(frames),
        "lock_events": _bounded_strings(item.get("lock_events"), 4, 256),
        "deadlock_related": item.get("deadlock_related") is True,
    }


def _bounded_frames(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    frames: list[dict[str, Any]] = []
    for frame in value[:8]:
        if not isinstance(frame, dict):
            continue
        frames.append(
            {
                "class_name": _truncate(_text(frame.get("class_name")), 512),
                "method": _truncate(_text(frame.get("method")), 256),
                "file": (
                    _truncate(_text(frame.get("file")), 256)
                    if frame.get("file") is not None
                    else None
                ),
                "line": (
                    frame.get("line")
                    if isinstance(frame.get("line"), int)
                    else None
                ),
                "frame_index": (
                    frame.get("frame_index")
                    if isinstance(frame.get("frame_index"), int)
                    else None
                ),
            }
        )
    return frames


def _bounded_strings(
    value: Any,
    limit: int,
    max_length: int,
) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        if isinstance(item, str):
            result.append(_truncate(item, max_length))
    return result


def _valid_artifact_ref(
    source_ref: Any,
    artifacts: ArtifactBundle | None,
    warnings: list[str],
    label: str,
) -> TypeGuard[str]:
    if not isinstance(source_ref, str):
        _warn_mapping(warnings, f"{label}: missing artifact source_ref")
        return False
    match = _ARTIFACT_REF_RE.fullmatch(source_ref)
    if match is None:
        _warn_mapping(warnings, f"{label}: invalid artifact source_ref")
        return False
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    if start < 1 or end < start:
        _warn_mapping(warnings, f"{label}: invalid artifact line range")
        return False
    if artifacts is not None:
        document = artifacts.document(match.group("artifact_id"))
        if document is None:
            _warn_mapping(
                warnings,
                f"{label}: unknown artifact id "
                f"{match.group('artifact_id')!r}",
            )
            return False
        if end > document.line_count:
            _warn_mapping(
                warnings,
                f"{label}: artifact line range exceeds "
                f"{match.group('artifact_id')!r}",
            )
            return False
    return True


def _warn_mapping(warnings: list[str], message: str) -> None:
    if message in warnings or len(warnings) >= _MAX_MAPPING_WARNINGS:
        return
    warnings.append(message)


def _annotations(item: dict[str, Any], file_path: str) -> MappingOutcome:
    annotations = item.get("annotations")
    if annotations is None:
        return MappingOutcome()
    if not isinstance(annotations, list):
        return _failure("code symbol: annotations must be a list")
    drafts: list[EvidenceDraft] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            return _failure("code symbol: annotation is not an object")
        name = annotation.get("name")
        line = annotation.get("line")
        if not isinstance(name, str) or not isinstance(line, int):
            return _failure("code symbol: annotation missing name/line")
        drafts.append(
            EvidenceDraft(
                kind=EvidenceKind.ANNOTATION,
                claim=f"Annotation @{name} at {file_path}:{line}",
                source_ref=_repo_line_ref(file_path, line),
                strength="medium",
                provenance=EvidenceProvenance.TOOL,
                content={
                    "name": name,
                    "arguments": annotation.get("arguments"),
                    "line": line,
                },
            )
        )
    return MappingOutcome(drafts=drafts)


def _repo_range_ref(file_path: str, start_line: int, end_line: int) -> str:
    return f"repo://{file_path}#L{start_line}-L{end_line}"


def _repo_line_ref(file_path: str, line: int) -> str:
    return f"repo://{file_path}#L{line}"


def _failure(reason: str) -> MappingOutcome:
    return MappingOutcome(failure_reason=reason)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _truncate(value: str, limit: int) -> str:
    flattened = " ".join(value.split())
    return flattened[:limit]
