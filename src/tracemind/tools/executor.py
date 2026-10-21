"""Tool executor with validation, deduplication, output limits, and audit."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from pydantic import ValidationError

from tracemind.tools.contracts import (
    AuditEvent,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolRequest,
    ToolResult,
)
from tracemind.tools.registry import ToolRegistry


class ToolExecutor:
    """Execute registered tools through one controlled path."""

    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        default_max_output_bytes: int = 32768,
    ) -> None:
        self._registry = registry
        self._context = context
        self._default_max_output_bytes = default_max_output_bytes
        self._seen: set[tuple[str, str]] = set()
        self.audit_events: list[AuditEvent] = []

    def execute(self, request: ToolRequest) -> ToolResult:
        started = perf_counter()
        registered = self._registry.get(request.tool_name)
        if registered is None:
            return self._error(
                request,
                ToolErrorCode.TOOL_NOT_FOUND,
                f"unknown tool: {request.tool_name}",
                started,
                _hash_args(request.arguments),
                "denied",
            )

        try:
            args = registered.spec.input_model.model_validate(request.arguments)
        except ValidationError as exc:
            return self._error(
                request,
                ToolErrorCode.INVALID_ARGUMENTS,
                _format_validation(exc),
                started,
                _hash_args(request.arguments),
                "invalid_arguments",
            )

        args_hash = _hash_args(args.model_dump())
        dedup_key = (request.tool_name, args_hash)
        if dedup_key in self._seen:
            return self._error(
                request,
                ToolErrorCode.DUPLICATE_CALL,
                "duplicate tool call",
                started,
                args_hash,
                "duplicate",
            )
        self._seen.add(dedup_key)

        try:
            handler_result = registered.handler(self._context, args)
        except ToolError as exc:
            outcome = "denied" if exc.code is ToolErrorCode.TARGET_DENIED else "error"
            return self._error(
                request,
                exc.code,
                exc.message,
                started,
                args_hash,
                outcome,
            )
        except Exception as exc:  # keep one bad tool from killing the loop
            return self._error(
                request,
                ToolErrorCode.TOOL_ERROR,
                f"{type(exc).__name__}: {exc}",
                started,
                args_hash,
                "error",
            )

        limit = registered.spec.max_output_bytes or self._default_max_output_bytes
        data, truncated = _truncate(handler_result.data, limit)
        truncated = truncated or handler_result.truncated
        duration_ms = _duration_ms(started)
        result = ToolResult(
            ok=True,
            tool_name=request.tool_name,
            data=data,
            source_ref=handler_result.source_ref,
            duration_ms=duration_ms,
            truncated=truncated,
        )
        self._audit(
            request,
            args_hash,
            "allowed",
            None,
            duration_ms,
            handler_result.source_ref,
        )
        return result

    def _error(
        self,
        request: ToolRequest,
        code: ToolErrorCode,
        message: str,
        started: float,
        args_hash: str,
        outcome: str,
    ) -> ToolResult:
        duration_ms = _duration_ms(started)
        self._audit(request, args_hash, outcome, code.value, duration_ms, None)
        return ToolResult(
            ok=False,
            tool_name=request.tool_name,
            error_code=code.value,
            error_message=message[:500],
            duration_ms=duration_ms,
        )

    def _audit(
        self,
        request: ToolRequest,
        args_hash: str,
        outcome: str,
        error_code: str | None,
        duration_ms: int,
        source_ref: str | None,
    ) -> None:
        self.audit_events.append(
            AuditEvent(
                timestamp=datetime.now(UTC).isoformat(),
                run_id=request.run_id,
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                args_hash=args_hash,
                outcome=outcome,
                error_code=error_code,
                duration_ms=duration_ms,
                source_ref=source_ref,
            )
        )


def _hash_args(arguments: Any) -> str:
    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _truncate(data: Any, limit: int) -> tuple[Any, bool]:
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    raw = encoded.encode("utf-8")
    if len(raw) <= limit:
        return data, False
    return raw[:limit].decode("utf-8", errors="ignore"), True


def _duration_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _format_validation(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    )
