"""Fixture-only verification backend and strict JSON data loader."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from tracemind.verification.backend import (
    TableDescription,
    VerificationDataError,
    VerificationRowResult,
    VerificationTargetError,
)

MAX_FILE_BYTES = 1024 * 1024
MAX_TABLES = 10
MAX_COLUMNS = 30
MAX_ROWS = 1000
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_Scalar = str | int | float | bool | None


@dataclass(frozen=True)
class _TableData:
    primary_key: str
    columns: tuple[str, ...]
    sensitive_columns: frozenset[str]
    rows_by_key: Mapping[str, dict[str, _Scalar]]


class FakeVerificationBackend:
    """Serve synthetic, read-only rows from a validated fixture file."""

    def __init__(self, tables: Mapping[str, _TableData]) -> None:
        self._tables = dict(tables)
        self._rows = {
            name: len(table.rows_by_key) for name, table in self._tables.items()
        }

    @property
    def environment(self) -> str:
        return "fixture"

    @property
    def backend_name(self) -> str:
        return "fake"

    @property
    def table_names(self) -> list[str]:
        return list(self._tables)

    def metadata(self) -> dict[str, Any]:
        """Return non-sensitive backend metadata for run artifacts."""
        return {
            "environment": self.environment,
            "backend": self.backend_name,
            "tables": self.table_names,
        }

    def describe_table(self, table: str) -> TableDescription:
        table_data = self._get_table(table)
        return TableDescription(
            table=table,
            columns=list(table_data.columns),
            primary_key=table_data.primary_key,
            row_count=self._rows[table],
            sensitive_columns=sorted(table_data.sensitive_columns),
        )

    def get_row(
        self,
        table: str,
        key_value: str | int,
        columns: list[str] | None = None,
    ) -> VerificationRowResult:
        table_data = self._get_table(table)
        if isinstance(key_value, bool) or not isinstance(key_value, str | int):
            raise VerificationTargetError(
                "key_value must be a string or integer primary-key value"
            )
        selected = self._select_columns(table_data, columns)
        normalized_key = str(key_value)
        source_ref = (
            f"db://{table}/{table_data.primary_key}={normalized_key}"
        )
        row = table_data.rows_by_key.get(normalized_key)
        if row is None:
            return VerificationRowResult(
                found=False,
                table=table,
                key_column=table_data.primary_key,
                key_value=key_value,
                columns=selected,
                row=None,
                redacted_columns=[],
                environment="fixture",
                source_ref=source_ref,
            )

        selected_values: dict[str, Any] = {}
        redacted: list[str] = []
        for column in selected:
            if column not in row:
                continue
            if column in table_data.sensitive_columns:
                selected_values[column] = "***"
                redacted.append(column)
            else:
                selected_values[column] = row[column]
        return VerificationRowResult(
            found=True,
            table=table,
            key_column=table_data.primary_key,
            key_value=key_value,
            columns=selected,
            row=selected_values,
            redacted_columns=redacted,
            environment="fixture",
            source_ref=source_ref,
        )

    def _get_table(self, table: str) -> _TableData:
        table_data = self._tables.get(table)
        if table_data is None:
            raise VerificationTargetError(f"table is not available: {table}")
        return table_data

    def _select_columns(
        self,
        table_data: _TableData,
        columns: list[str] | None,
    ) -> list[str]:
        if columns is None:
            return list(table_data.columns)
        if not columns:
            raise VerificationTargetError("columns must not be empty when provided")
        if len(set(columns)) != len(columns):
            raise VerificationTargetError("columns must not contain duplicates")
        for column in columns:
            if column not in table_data.columns:
                raise VerificationTargetError(
                    f"column is not available: {column}"
                )
        return list(columns)


def load_verification_data(path: str | Path) -> FakeVerificationBackend:
    """Load and strictly validate a fixture-only verification data file."""
    source = Path(path)
    try:
        stat = source.stat()
    except OSError as exc:
        raise VerificationDataError(
            f"{source}: cannot read verification data: {exc.strerror or exc}"
        ) from exc
    if not source.is_file():
        raise VerificationDataError(f"{source}: not a regular file")
    if stat.st_size > MAX_FILE_BYTES:
        raise VerificationDataError(
            f"{source}: file exceeds the {MAX_FILE_BYTES}-byte limit"
        )

    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise VerificationDataError(
            f"{source}: cannot read verification data: {exc.strerror or exc}"
        ) from exc
    if len(raw) > MAX_FILE_BYTES:
        raise VerificationDataError(
            f"{source}: file exceeds the {MAX_FILE_BYTES}-byte limit"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationDataError(
            f"{source}: verification data must be UTF-8"
        ) from exc
    try:
        document = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise VerificationDataError(
            f"{source}: invalid verification JSON: {exc}"
        ) from exc

    tables = _validate_document(document, source)
    return FakeVerificationBackend(tables)


def _validate_document(
    document: Any,
    source: Path,
) -> dict[str, _TableData]:
    if not isinstance(document, dict):
        _invalid(source, "root", "must be a JSON object")
    unknown = set(document) - {"backend", "tables"}
    if unknown:
        _invalid(source, "root", f"unknown field(s): {sorted(unknown)}")
    if document.get("backend") != "fake":
        _invalid(source, "backend", 'must be "fake"')
    tables = document.get("tables")
    if not isinstance(tables, dict) or not tables:
        _invalid(source, "tables", "must be a non-empty object")
    if len(tables) > MAX_TABLES:
        _invalid(source, "tables", f"contains more than {MAX_TABLES} tables")

    validated: dict[str, _TableData] = {}
    for table_name, table_document in tables.items():
        if not isinstance(table_name, str) or not _is_identifier(table_name):
            _invalid(source, "tables", "table names must be SQL identifiers")
        validated[table_name] = _validate_table(
            table_name,
            table_document,
            source,
        )
    return validated


def _validate_table(
    table_name: str,
    document: Any,
    source: Path,
) -> _TableData:
    location = f"tables.{table_name}"
    if not isinstance(document, dict):
        _invalid(source, location, "must be an object")
    unknown = set(document) - {
        "primary_key",
        "columns",
        "sensitive_columns",
        "rows",
    }
    if unknown:
        _invalid(source, location, f"unknown field(s): {sorted(unknown)}")

    columns_document = document.get("columns")
    if not isinstance(columns_document, list) or not columns_document:
        _invalid(source, f"{location}.columns", "must be a non-empty array")
    if len(columns_document) > MAX_COLUMNS:
        _invalid(
            source,
            f"{location}.columns",
            f"contains more than {MAX_COLUMNS} columns",
        )
    columns: list[str] = []
    for index, column in enumerate(columns_document):
        if not isinstance(column, str) or not _is_identifier(column):
            _invalid(
                source,
                f"{location}.columns[{index}]",
                "must be a SQL identifier",
            )
        columns.append(column)
    if len(set(columns)) != len(columns):
        _invalid(source, f"{location}.columns", "contains duplicates")

    primary_key = document.get("primary_key")
    if not isinstance(primary_key, str) or not _is_identifier(primary_key):
        _invalid(source, f"{location}.primary_key", "must be a SQL identifier")
    if primary_key not in columns:
        _invalid(
            source,
            f"{location}.primary_key",
            "must be present in columns",
        )

    sensitive_document = document.get("sensitive_columns", [])
    if not isinstance(sensitive_document, list):
        _invalid(source, f"{location}.sensitive_columns", "must be an array")
    sensitive_columns: set[str] = set()
    for index, column in enumerate(sensitive_document):
        if not isinstance(column, str) or column not in columns:
            _invalid(
                source,
                f"{location}.sensitive_columns[{index}]",
                "must reference a declared column",
            )
        sensitive_columns.add(column)

    rows_document = document.get("rows")
    if not isinstance(rows_document, list):
        _invalid(source, f"{location}.rows", "must be an array")
    if len(rows_document) > MAX_ROWS:
        _invalid(
            source,
            f"{location}.rows",
            f"contains more than {MAX_ROWS} rows",
        )

    rows_by_key: dict[str, dict[str, _Scalar]] = {}
    allowed_columns = set(columns)
    for index, row_document in enumerate(rows_document):
        row_location = f"{location}.rows[{index}]"
        if not isinstance(row_document, dict):
            _invalid(source, row_location, "must be an object")
        unknown_columns = set(row_document) - allowed_columns
        if unknown_columns:
            _invalid(
                source,
                row_location,
                f"unknown column(s): {sorted(unknown_columns)}",
            )
        if primary_key not in row_document:
            _invalid(source, row_location, "must contain the primary key")
        for column, value in row_document.items():
            if not _is_scalar(value):
                _invalid(
                    source,
                    f"{row_location}.{column}",
                    "must be a scalar value",
                )
        key = row_document[primary_key]
        if isinstance(key, bool) or not isinstance(key, str | int):
            _invalid(
                source,
                f"{row_location}.{primary_key}",
                "primary-key values must be strings or integers",
            )
        normalized_key = str(key)
        if normalized_key in rows_by_key:
            _invalid(
                source,
                row_location,
                "duplicates another row's canonical primary-key value",
            )
        rows_by_key[normalized_key] = cast(dict[str, _Scalar], row_document)

    return _TableData(
        primary_key=primary_key,
        columns=tuple(columns),
        sensitive_columns=frozenset(sensitive_columns),
        rows_by_key=rows_by_key,
    )


def _is_identifier(value: str) -> bool:
    return IDENTIFIER_PATTERN.fullmatch(value) is not None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _invalid(source: Path, location: str, message: str) -> NoReturn:
    raise VerificationDataError(f"{source}: {location}: {message}")


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite number is not allowed: {value}")
