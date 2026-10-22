"""Unit tests for fixture-only read-only verification data."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tracemind.verification import (
    VerificationDataError,
    VerificationTargetError,
    load_verification_data,
)

VALID_DATA = {
    "backend": "fake",
    "tables": {
        "orders": {
            "primary_key": "id",
            "columns": ["id", "status", "customer_email"],
            "sensitive_columns": ["customer_email"],
            "rows": [
                {
                    "id": 10086,
                    "status": "PAID",
                    "customer_email": "buyer@example.test",
                },
                {
                    "id": 10087,
                    "status": "CREATED",
                    "customer_email": "second@example.test",
                },
            ],
        }
    },
}


def _write(tmp_path: Path, data: object, name: str = "verification.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _load(tmp_path: Path, data: object):
    return load_verification_data(_write(tmp_path, data))


def test_load_and_describe_fixture_table(tmp_path: Path) -> None:
    backend = _load(tmp_path, VALID_DATA)

    assert backend.environment == "fixture"
    assert backend.backend_name == "fake"
    assert backend.table_names == ["orders"]
    assert backend.metadata() == {
        "environment": "fixture",
        "backend": "fake",
        "tables": ["orders"],
    }
    description = backend.describe_table("orders")
    assert description.table == "orders"
    assert description.columns == ["id", "status", "customer_email"]
    assert description.primary_key == "id"
    assert description.row_count == 2
    assert description.sensitive_columns == ["customer_email"]


def test_get_row_found_not_found_and_string_key_equivalence(
    tmp_path: Path,
) -> None:
    backend = _load(tmp_path, VALID_DATA)

    found = backend.get_row("orders", 10086)
    equivalent = backend.get_row("orders", "10086")
    missing = backend.get_row("orders", 99999)

    assert found.found is True
    assert found.environment == "fixture"
    assert found.source_ref == "db://orders/id=10086"
    assert found.row is not None
    assert found.row["status"] == "PAID"
    assert found.row["customer_email"] == "***"
    assert found.redacted_columns == ["customer_email"]
    assert equivalent.found is True
    assert equivalent.source_ref == found.source_ref
    assert missing.found is False
    assert missing.row is None
    assert missing.source_ref == "db://orders/id=99999"


def test_column_subset_and_sensitive_redaction(tmp_path: Path) -> None:
    backend = _load(tmp_path, VALID_DATA)

    result = backend.get_row(
        "orders",
        "10086",
        columns=["id", "customer_email"],
    )

    assert result.columns == ["id", "customer_email"]
    assert result.row == {"id": 10086, "customer_email": "***"}
    assert result.redacted_columns == ["customer_email"]


@pytest.mark.parametrize(
    ("columns", "expected_message"),
    [
        (["missing"], "column is not available"),
        ([], "columns must not be empty"),
        (["id", "id"], "duplicates"),
    ],
)
def test_invalid_column_selection_is_rejected(
    tmp_path: Path,
    columns: list[str],
    expected_message: str,
) -> None:
    backend = _load(tmp_path, VALID_DATA)

    with pytest.raises(VerificationTargetError, match=expected_message):
        backend.get_row("orders", 10086, columns=columns)


def test_unknown_table_is_rejected(tmp_path: Path) -> None:
    backend = _load(tmp_path, VALID_DATA)

    with pytest.raises(VerificationTargetError, match="missing"):
        backend.describe_table("missing")
    with pytest.raises(VerificationTargetError, match="missing"):
        backend.get_row("missing", 10086)


def test_invalid_key_type_is_rejected(tmp_path: Path) -> None:
    backend = _load(tmp_path, VALID_DATA)

    with pytest.raises(VerificationTargetError, match="string or integer"):
        backend.get_row("orders", True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"backend": "mysql"}),
        lambda data: data.update({"tables": {}}),
        lambda data: data.update({"unexpected": True}),
        lambda data: data["tables"]["orders"].update({"columns": []}),
        lambda data: data["tables"]["orders"].update({"columns": ["id", "id"]}),
        lambda data: data["tables"]["orders"].update({"primary_key": "missing"}),
        lambda data: data["tables"]["orders"].update({"primary_key": ""}),
        lambda data: data["tables"]["orders"].update({"columns": ["id-status"]}),
        lambda data: data["tables"].update({"orders;drop": data["tables"]["orders"]}),
        lambda data: data["tables"]["orders"].update({"extra": 1}),
        lambda data: data["tables"]["orders"].update(
            {"sensitive_columns": ["password"]}
        ),
        lambda data: data["tables"]["orders"]["rows"][0].update(
            {"nested": {"a": 1}}
        ),
        lambda data: data["tables"]["orders"]["rows"][0].update({"nested": [1]}),
        lambda data: data["tables"]["orders"]["rows"][0].pop("id"),
        lambda data: data["tables"]["orders"]["rows"][0].update({"unknown": 1}),
        lambda data: data["tables"]["orders"]["rows"][0].update({"id": None}),
        lambda data: data["tables"]["orders"]["rows"][0].update({"id": True}),
        lambda data: data["tables"]["orders"]["rows"].append(
            copy.deepcopy(data["tables"]["orders"]["rows"][0])
        ),
        lambda data: data["tables"]["orders"]["rows"].append(
            {**copy.deepcopy(data["tables"]["orders"]["rows"][0]), "id": "10086"}
        ),
    ],
)
def test_invalid_data_is_rejected(tmp_path: Path, mutate) -> None:
    data = copy.deepcopy(VALID_DATA)
    mutate(data)

    with pytest.raises(VerificationDataError):
        _load(tmp_path, data)


def test_too_many_columns_is_rejected(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    columns = ["id", *(f"col_{index}" for index in range(30))]
    data["tables"]["orders"]["columns"] = columns
    data["tables"]["orders"]["rows"][0] = {"id": 10086}

    with pytest.raises(VerificationDataError, match="30 columns"):
        _load(tmp_path, data)


def test_too_many_rows_is_rejected(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["tables"]["orders"]["rows"] = [
        {"id": index} for index in range(1001)
    ]

    with pytest.raises(VerificationDataError, match="1000 rows"):
        _load(tmp_path, data)


def test_too_many_tables_is_rejected(tmp_path: Path) -> None:
    data = {
        "backend": "fake",
        "tables": {
            f"table_{index}": copy.deepcopy(VALID_DATA["tables"]["orders"])
            for index in range(11)
        },
    }

    with pytest.raises(VerificationDataError, match="10 tables"):
        _load(tmp_path, data)


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(VerificationDataError, match="invalid verification JSON"):
        load_verification_data(path)


def test_non_finite_number_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nan.json"
    path.write_text(
        '{"backend":"fake","tables":{"t":{"primary_key":"id",'
        '"columns":["id"],"rows":[{"id":NaN}]}}}',
        encoding="utf-8",
    )

    with pytest.raises(VerificationDataError):
        load_verification_data(path)


def test_non_utf8_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe{}")

    with pytest.raises(VerificationDataError, match="UTF-8"):
        load_verification_data(path)


def test_oversized_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * (1024 * 1024 + 1))

    with pytest.raises(VerificationDataError, match="limit"):
        load_verification_data(path)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(VerificationDataError, match="cannot read"):
        load_verification_data(tmp_path / "missing.json")
