"""Built-in read-only tools for the TraceMind minimal loop."""

from __future__ import annotations

from typing import Any, Self, cast

from pydantic import BaseModel, Field, model_validator

from tracemind.core.models import LogEvent, ParsedLog
from tracemind.indexing.java_index import JavaIndex, JavaIndexError, SourceMatch
from tracemind.log_analysis.thread_context import (
    ThreadContextError,
    collect_thread_context,
)
from tracemind.tools.code_flow import register_code_flow_tools
from tracemind.tools.contracts import (
    EvidenceToolMeta,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolHandlerResult,
    ToolSpec,
)
from tracemind.tools.control import register_control_tools
from tracemind.tools.registry import ToolRegistry
from tracemind.tools.verification import register_verification_tools
from tracemind.verification import ReadOnlyVerificationBackend
from tracemind.workspace.paths import resolve_under_root


class LogSearchArgs(EvidenceToolMeta):
    """Arguments for ``logs.search``."""

    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class LogEventContextArgs(EvidenceToolMeta):
    """Arguments for ``logs.get_event_context``."""

    event_id: str = Field(min_length=1)
    before: int = Field(default=2, ge=0, le=20)
    after: int = Field(default=2, ge=0, le=20)


class LogThreadContextArgs(EvidenceToolMeta):
    """Arguments for ``logs.get_thread_context``."""

    event_id: str | None = Field(default=None, min_length=1)
    before: int = Field(default=3, ge=0, le=20)
    after: int = Field(default=3, ge=0, le=20)


class CodeFindSymbolArgs(EvidenceToolMeta):
    """Arguments for ``code.find_symbol``."""

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


class CodeGetSourceRangeArgs(EvidenceToolMeta):
    """Arguments for ``code.get_source_range``."""

    file_path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    max_lines: int = Field(default=80, ge=1, le=200)

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


def build_default_registry(
    verification_backend: ReadOnlyVerificationBackend | None = None,
) -> ToolRegistry:
    """Register local read-only tools and v0.3 diagnosis control tools."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="logs.search",
            description="Search parsed log events by case-insensitive literal text.",
            input_model=LogSearchArgs,
        ),
        _logs_search,
    )
    registry.register(
        ToolSpec(
            name="logs.get_event_context",
            description="Return parsed log events around a target event.",
            input_model=LogEventContextArgs,
        ),
        _logs_get_event_context,
    )
    registry.register(
        ToolSpec(
            name="logs.get_thread_context",
            description=(
                "Return ordered log events from the anchor event's own thread "
                "within a bounded radius. Cross-thread events are excluded and "
                "stack frames are not included."
            ),
            input_model=LogThreadContextArgs,
        ),
        _logs_get_thread_context,
    )
    registry.register(
        ToolSpec(
            name="code.find_symbol",
            description="Find Java classes, methods, or constructors by name.",
            input_model=CodeFindSymbolArgs,
        ),
        _code_find_symbol,
    )
    registry.register(
        ToolSpec(
            name="code.get_source_range",
            description="Read a line-numbered source range from the indexed repository.",
            input_model=CodeGetSourceRangeArgs,
        ),
        _code_get_source_range,
    )
    register_code_flow_tools(registry)
    if verification_backend is not None:
        register_verification_tools(registry, verification_backend)
    register_control_tools(registry)
    return registry


def _logs_search(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(LogSearchArgs, args)
    parsed = _require_parsed_log(context)
    query = params.query.lower()
    matches = [event for event in parsed.events if _event_matches(event, query)]
    total = len(matches)
    items = [_event_summary(event) for event in matches[: params.limit]]
    return ToolHandlerResult(
        data={"items": items, "total_matched": total},
        source_ref=items[0]["source_ref"] if items else None,
        truncated=total > params.limit,
    )


def _logs_get_event_context(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(LogEventContextArgs, args)
    parsed = _require_parsed_log(context)
    target_index = next(
        (
            index
            for index, event in enumerate(parsed.events)
            if event.event_id == params.event_id
        ),
        None,
    )
    if target_index is None:
        raise ToolError(
            ToolErrorCode.TARGET_DENIED,
            f"log event not found: {params.event_id}",
        )

    start = max(0, target_index - params.before)
    end = min(len(parsed.events), target_index + params.after + 1)
    requested_start = target_index - params.before
    requested_end = target_index + params.after + 1
    items = [_event_summary(event) for event in parsed.events[start:end]]
    return ToolHandlerResult(
        data={"items": items, "target_event_id": params.event_id},
        source_ref=f"log://{params.event_id}",
        truncated=start != requested_start or end != requested_end,
    )


def _logs_get_thread_context(
    context: ToolContext,
    args: BaseModel,
) -> ToolHandlerResult:
    params = cast(LogThreadContextArgs, args)
    parsed = _require_parsed_log(context)
    try:
        thread_context = collect_thread_context(
            parsed,
            params.event_id,
            before=params.before,
            after=params.after,
        )
    except ThreadContextError as exc:
        raise ToolError(ToolErrorCode(exc.code), exc.message) from exc
    return ToolHandlerResult(
        data=thread_context.model_dump(),
        source_ref=thread_context.source_ref,
        truncated=thread_context.truncated,
    )


def _code_find_symbol(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeFindSymbolArgs, args)
    java_index = _require_java_index(context)
    source_matches = [
        SourceMatch(
            symbol=symbol,
            file_path=symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            matched_line=None,
            confidence=0.80,
            match_reason="symbol_query",
            provenance=symbol.provenance,
        )
        for symbol in java_index.find_symbol(params.query, params.limit)
    ]
    items: list[dict[str, Any]] = []
    for match in source_matches:
        item = match.model_dump()
        item.update(match.symbol.model_dump())
        item["source_ref"] = _repo_ref(
            match.file_path,
            match.start_line,
            match.end_line,
        )
        items.append(item)
    source_ref = items[0]["source_ref"] if items else None
    return ToolHandlerResult(
        data={"items": items, "count": len(items)},
        source_ref=source_ref,
    )


def _code_get_source_range(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeGetSourceRangeArgs, args)
    java_index = _require_java_index(context)
    if context.repo_root is None:
        raise ToolError(ToolErrorCode.TOOL_ERROR, "repository root is not available")

    try:
        target = resolve_under_root(context.repo_root, params.file_path)
    except ValueError as exc:
        raise ToolError(ToolErrorCode.TARGET_DENIED, str(exc)) from exc

    repo_root = context.repo_root.resolve()
    relative_path = target.relative_to(repo_root).as_posix()
    capped_end = min(params.end_line, params.start_line + params.max_lines - 1)
    try:
        snippet = java_index.get_source_range(
            relative_path,
            params.start_line,
            capped_end,
        )
    except JavaIndexError as exc:
        raise ToolError(ToolErrorCode.TOOL_ERROR, str(exc)) from exc

    return ToolHandlerResult(
        data=snippet.model_dump(),
        source_ref=_repo_ref(
            snippet.file_path,
            snippet.start_line,
            snippet.end_line,
        ),
        truncated=snippet.truncated or capped_end != params.end_line,
    )


def _require_parsed_log(context: ToolContext) -> ParsedLog:
    if context.parsed_log is None:
        raise ToolError(ToolErrorCode.TOOL_ERROR, "parsed log context is not available")
    return context.parsed_log


def _require_java_index(context: ToolContext) -> JavaIndex:
    if context.java_index is None:
        raise ToolError(ToolErrorCode.TOOL_ERROR, "Java index context is not available")
    return context.java_index


def _event_matches(event: LogEvent, query: str) -> bool:
    parts = [
        event.message,
        event.exception_type or "",
        event.exception_message or "",
    ]
    parts.extend(frame.raw for frame in event.stack_frames)
    parts.extend(cause.exception_type for cause in event.cause_chain)
    parts.extend(cause.exception_message or "" for cause in event.cause_chain)
    return query in " ".join(parts).lower()


def _event_summary(event: LogEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "source_ref": f"log://{event.event_id}",
        "timestamp": event.timestamp,
        "level": event.level,
        "thread": event.thread,
        "logger": event.logger,
        "message": event.message,
        "exception_type": event.exception_type,
        "line_start": event.line_start,
        "line_end": event.line_end,
    }


def _repo_ref(file_path: str, start_line: int, end_line: int) -> str:
    return f"repo://{file_path}#L{start_line}-L{end_line}"
