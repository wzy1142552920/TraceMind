"""Read-only fixture verification tools for database-state hypotheses."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import BaseModel, Field, field_validator

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
from tracemind.verification import (
    FakeVerificationBackend,
    ReadOnlyVerificationBackend,
    VerificationTargetError,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_KEY_CHARS = 200
_DB_OUTPUT_BYTES = 8192


class DescribeTableArgs(EvidenceToolMeta):
    """Arguments for ``db.describe_table``."""

    table: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )


class GetRowArgs(EvidenceToolMeta):
    """Arguments for ``db.get_row``."""

    table: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    key_value: str | int
    columns: list[str] | None = Field(default=None, min_length=1, max_length=30)

    @field_validator("key_value", mode="before")
    @classmethod
    def _validate_key_value(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("key_value must be a string or integer")
        if isinstance(value, str):
            if not value:
                raise ValueError("key_value must not be empty")
            if len(value) > _MAX_KEY_CHARS:
                raise ValueError(
                    f"key_value must be at most {_MAX_KEY_CHARS} characters"
                )
            return value
        if not isinstance(value, int):
            raise ValueError("key_value must be a string or integer")
        return value

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError("columns must not contain duplicates")
        for column in value:
            if _IDENTIFIER.fullmatch(column) is None:
                raise ValueError(f"invalid column identifier: {column}")
        return value


def register_verification_tools(
    registry: ToolRegistry,
    backend: ReadOnlyVerificationBackend,
) -> None:
    """Register DB tools only when a verification backend is available."""
    registry.register(
        ToolSpec(
            name="db.describe_table",
            description=(
                "Read-only fixture (non-production) table schema and row count. "
                "No arbitrary SQL or write access."
            ),
            input_model=DescribeTableArgs,
            max_output_bytes=_DB_OUTPUT_BYTES,
        ),
        _describe_table_handler(backend),
    )
    registry.register(
        ToolSpec(
            name="db.get_row",
            description=(
                "Read-only fixture (non-production) single-row lookup by primary "
                "key. No arbitrary SQL, filters, joins, or writes."
            ),
            input_model=GetRowArgs,
            max_output_bytes=_DB_OUTPUT_BYTES,
        ),
        _get_row_handler(backend),
    )


def _describe_table_handler(
    fallback_backend: ReadOnlyVerificationBackend,
) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(DescribeTableArgs, args)
        backend = _backend(context, fallback_backend)
        try:
            description = backend.describe_table(params.table)
        except VerificationTargetError as exc:
            raise ToolError(ToolErrorCode.TARGET_DENIED, str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                ToolErrorCode.TOOL_ERROR,
                f"verification backend failed: {type(exc).__name__}",
            ) from exc

        source_ref = f"db://{description.table}#schema"
        data = description.model_dump()
        data.update(
            {
                "environment": backend.environment,
                "provenance": _provenance(backend),
                "source_ref": source_ref,
            }
        )
        return ToolHandlerResult(data=data, source_ref=source_ref)

    return handler


def _get_row_handler(
    fallback_backend: ReadOnlyVerificationBackend,
) -> ToolHandler:
    def handler(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        params = cast(GetRowArgs, args)
        backend = _backend(context, fallback_backend)
        try:
            result = backend.get_row(
                params.table,
                params.key_value,
                params.columns,
            )
        except VerificationTargetError as exc:
            raise ToolError(ToolErrorCode.TARGET_DENIED, str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                ToolErrorCode.TOOL_ERROR,
                f"verification backend failed: {type(exc).__name__}",
            ) from exc

        data = result.model_dump()
        data["provenance"] = _provenance(backend)
        return ToolHandlerResult(data=data, source_ref=result.source_ref)

    return handler


def _backend(
    context: ToolContext,
    fallback: ReadOnlyVerificationBackend,
) -> ReadOnlyVerificationBackend:
    return context.verification_backend or fallback


def _provenance(backend: ReadOnlyVerificationBackend) -> str:
    if isinstance(backend, FakeVerificationBackend):
        return "fake_verification"
    return "read_only_verification"
