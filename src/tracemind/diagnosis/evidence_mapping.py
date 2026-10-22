"""Deterministic tool-result to evidence mapping for the v0.3 runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from tracemind.diagnosis.evidence import EvidenceKind, EvidenceProvenance
from tracemind.tools.contracts import ToolResult

Strength = Literal["strong", "medium", "weak"]


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
    """Drafts and an optional stable mapping failure."""

    drafts: list[EvidenceDraft] = field(default_factory=list)
    failure_reason: str | None = None


def map_tool_result(result: ToolResult) -> MappingOutcome:
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
