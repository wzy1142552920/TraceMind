"""Unit tests for read-only fixture DB verification tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolRequest
from tracemind.tools.executor import ToolExecutor
from tracemind.verification import FakeVerificationBackend, load_verification_data

DATA = {
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
                }
            ],
        }
    },
}


def _backend(tmp_path: Path, data: object = DATA) -> FakeVerificationBackend:
    path = tmp_path / "verification.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_verification_data(path)


def _executor(
    backend: FakeVerificationBackend | None,
    *,
    context_backend: bool = True,
) -> ToolExecutor:
    registry = build_default_registry(verification_backend=backend)
    context = ToolContext(
        verification_backend=backend if context_backend else None
    )
    return ToolExecutor(registry, context)


def _request(
    tool_name: str,
    arguments: dict[str, object],
    call_id: str = "call_db_1",
) -> ToolRequest:
    return ToolRequest(
        tool_call_id=call_id,
        tool_name=tool_name,
        arguments=arguments,
        run_id="run_test",
    )


def test_db_tools_are_not_registered_without_backend() -> None:
    registry = build_default_registry()

    assert not [
        spec for spec in registry.list_tools() if spec.name.startswith("db.")
    ]


def test_db_tools_are_registered_only_with_backend(tmp_path: Path) -> None:
    registry = build_default_registry(verification_backend=_backend(tmp_path))

    tools = {
        spec.name: spec for spec in registry.list_tools() if spec.name.startswith("db.")
    }

    assert set(tools) == {"db.describe_table", "db.get_row"}
    assert all(spec.read_only for spec in tools.values())
    describe = tools["db.describe_table"].description.lower()
    get_row = tools["db.get_row"].description.lower()
    assert "read-only" in describe
    assert "fixture" in describe
    assert "non-production" in describe
    assert "no arbitrary sql" in describe
    assert "single-row" in get_row
    assert "primary key" in get_row
    assert "no arbitrary sql" in get_row


def test_describe_table_returns_fixture_schema(tmp_path: Path) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(
        _request("db.describe_table", {"table": "orders"})
    )

    assert result.ok
    assert isinstance(result.data, dict)
    assert result.data["table"] == "orders"
    assert result.data["primary_key"] == "id"
    assert result.data["row_count"] == 1
    assert result.data["environment"] == "fixture"
    assert result.data["provenance"] == "fake_verification"
    assert result.data["source_ref"] == "db://orders#schema"
    assert result.source_ref == "db://orders#schema"
    audit = executor.audit_events[-1]
    assert audit.outcome == "allowed"
    assert audit.source_ref == "db://orders#schema"


def test_get_row_found_redacts_sensitive_columns(tmp_path: Path) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(
        _request(
            "db.get_row",
            {
                "table": "orders",
                "key_value": 10086,
                "columns": ["id", "status", "customer_email"],
            },
        )
    )

    assert result.ok
    assert isinstance(result.data, dict)
    assert result.data["found"] is True
    assert result.data["key_column"] == "id"
    assert result.data["key_value"] == 10086
    assert result.data["row"] == {
        "id": 10086,
        "status": "PAID",
        "customer_email": "***",
    }
    assert result.data["redacted_columns"] == ["customer_email"]
    assert result.data["environment"] == "fixture"
    assert result.data["provenance"] == "fake_verification"
    assert result.data["source_ref"] == "db://orders/id=10086"
    assert result.source_ref == "db://orders/id=10086"
    assert result.bound_hypothesis_id is None


def test_get_row_not_found_is_structured(tmp_path: Path) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(
        _request(
            "db.get_row",
            {"table": "orders", "key_value": "99999"},
        )
    )

    assert result.ok
    assert isinstance(result.data, dict)
    assert result.data["found"] is False
    assert result.data["row"] is None
    assert result.data["key_value"] == "99999"
    assert result.data["source_ref"] == "db://orders/id=99999"
    assert result.source_ref == "db://orders/id=99999"


@pytest.mark.parametrize(
    "arguments",
    [
        {"table": "missing", "key_value": 10086},
        {"table": "orders", "key_value": 10086, "columns": ["missing"]},
    ],
)
def test_unknown_table_or_column_is_denied(
    tmp_path: Path,
    arguments: dict[str, object],
) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(_request("db.get_row", arguments))

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"
    assert executor.audit_events[-1].outcome == "denied"


@pytest.mark.parametrize(
    "arguments",
    [
        {"table": "orders", "key_value": True},
        {"table": "orders", "key_value": [10086]},
        {"table": "orders", "key_value": 10086, "columns": []},
        {"table": "orders", "key_value": 10086, "columns": ["id", "id"]},
        {"table": "orders; DROP TABLE orders", "key_value": 10086},
        {"table": "orders", "key_value": 10086, "sql": "SELECT * FROM orders"},
    ],
)
def test_invalid_arguments_are_rejected(
    tmp_path: Path,
    arguments: dict[str, object],
) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(_request("db.get_row", arguments))

    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"
    assert executor.audit_events[-1].outcome == "invalid_arguments"


def test_no_arbitrary_sql_tool_exists(tmp_path: Path) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(
        _request("db.query", {"sql": "SELECT * FROM orders"})
    )

    assert not result.ok
    assert result.error_code == "TOOL_NOT_FOUND"


def test_binding_metadata_is_consumed_and_rejected_without_workspace(
    tmp_path: Path,
) -> None:
    executor = _executor(_backend(tmp_path))

    result = executor.execute(
        _request(
            "db.get_row",
            {
                "table": "orders",
                "key_value": 10086,
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
        )
    )

    assert not result.ok
    assert result.error_code == "INVALID_BINDING"
    assert executor.audit_events[-1].bound_hypothesis_id == "hyp_001"


def test_backend_registered_in_registry_works_without_context_backend(
    tmp_path: Path,
) -> None:
    executor = _executor(_backend(tmp_path), context_backend=False)

    result = executor.execute(
        _request("db.get_row", {"table": "orders", "key_value": 10086})
    )

    assert result.ok
    assert isinstance(result.data, dict)
    assert result.data["environment"] == "fixture"


def test_db_output_is_truncated_and_marked(tmp_path: Path) -> None:
    data = {
        "backend": "fake",
        "tables": {
            "orders": {
                "primary_key": "id",
                "columns": ["id", "note"],
                "rows": [{"id": 1, "note": "x" * 9000}],
            }
        },
    }
    executor = _executor(_backend(tmp_path, data))

    result = executor.execute(
        _request("db.get_row", {"table": "orders", "key_value": 1})
    )

    assert result.ok
    assert result.truncated is True
    assert isinstance(result.data, str)
    assert len(result.data) <= 8192
