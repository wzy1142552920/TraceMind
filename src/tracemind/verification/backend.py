"""Read-only verification backend contract for database-state hypotheses."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class TableDescription(BaseModel):
    """The schema and bounded row count exposed for one verification table."""

    table: str
    columns: list[str]
    primary_key: str
    row_count: int
    sensitive_columns: list[str] = Field(default_factory=list)


class VerificationRowResult(BaseModel):
    """One primary-key lookup against a read-only verification backend."""

    found: bool
    table: str
    key_column: str
    key_value: str | int
    columns: list[str]
    row: dict[str, Any] | None = None
    redacted_columns: list[str] = Field(default_factory=list)
    environment: Literal["fixture"] = "fixture"
    source_ref: str | None = None


class VerificationDataError(ValueError):
    """The verification data file is missing, malformed, or out of bounds."""


class VerificationTargetError(ValueError):
    """The requested table or column is outside the verification whitelist."""


class ReadOnlyVerificationBackend(Protocol):
    """A read-only, primary-key-only verification backend."""

    @property
    def environment(self) -> str: ...

    def describe_table(self, table: str) -> TableDescription: ...

    def get_row(
        self,
        table: str,
        key_value: str | int,
        columns: list[str] | None = None,
    ) -> VerificationRowResult: ...
