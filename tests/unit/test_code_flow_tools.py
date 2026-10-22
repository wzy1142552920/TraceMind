"""Unit tests for read-only Java code-flow tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.diagnosis.workspace import (
    DiagnosisWorkspace,
    HypothesisProposal,
    RequirementProposal,
)
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.log_analysis.parser import LogParser
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolRequest
from tracemind.tools.executor import ToolExecutor

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)
REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
ORDER_SERVICE = "src/main/java/com/example/order/OrderService.java"
ORDER_MAPPER = "src/main/java/com/example/order/OrderMapper.java"


@pytest.fixture()
def executor() -> ToolExecutor:
    parsed = LogParser().parse(LOG_FIXTURE)
    java_index = TreeSitterJavaIndex()
    java_index.index(REPO_FIXTURE)
    context = ToolContext(
        parsed_log=parsed,
        java_index=java_index,
        repo_root=REPO_FIXTURE,
        log_root=LOG_FIXTURE.parent,
    )
    return ToolExecutor(build_default_registry(), context)


def _request(
    tool_name: str,
    arguments: dict[str, object],
    tool_call_id: str = "call_1",
) -> ToolRequest:
    return ToolRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        run_id="run_test",
    )


def _find_symbol_id(
    executor: ToolExecutor,
    query: str,
    *,
    parameter_count: int | None = None,
    tool_call_id: str = "call_find",
) -> str:
    result = executor.execute(
        _request(
            "code.find_symbol",
            {"query": query, "limit": 20},
            tool_call_id=tool_call_id,
        )
    )
    assert result.ok, result.error_message
    for item in result.data["items"]:
        if parameter_count is None or item.get("parameter_count") == parameter_count:
            return str(item["symbol_id"])
    raise AssertionError(f"symbol not found: {query}/{parameter_count}")


def test_find_symbol_returns_enhanced_symbol_fields(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("code.find_symbol", {"query": "OrderMapper.updateStatus", "limit": 20})
    )

    assert result.ok
    item = next(
        item for item in result.data["items"] if item.get("parameter_count") == 2
    )
    assert item["symbol_id"].startswith("sym_")
    assert item["fqn"] == "com.example.order.OrderMapper"
    assert item["class_name"] == "OrderMapper"
    assert item["method_name"] == "updateStatus"
    assert item["parameter_count"] == 2
    assert [annotation["name"] for annotation in item["annotations"]] == ["Update"]
    assert item["source_ref"] == f"repo://{ORDER_MAPPER}#L16-L19"
    assert item["provenance"] == "tree_sitter"
    assert item["symbol"]["symbol_id"] == item["symbol_id"]


def test_get_symbol_returns_annotations_and_call_summary(
    executor: ToolExecutor,
) -> None:
    symbol_id = _find_symbol_id(
        executor,
        "OrderService.updateStatus",
        parameter_count=2,
    )

    result = executor.execute(
        _request("code.get_symbol", {"symbol_id": symbol_id})
    )

    assert result.ok
    assert result.data["symbol_id"] == symbol_id
    assert result.data["fqn"] == "com.example.order.OrderService"
    assert result.data["parameter_count"] == 2
    assert result.data["return_type"] == "int"
    assert result.data["modifiers"] == ["public"]
    assert result.data["source_ref"] == f"repo://{ORDER_SERVICE}#L17-L27"
    assert result.data["calls"] == {"callee_count": 1, "caller_count": 2}


def test_get_symbol_rejects_unknown_symbol(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("code.get_symbol", {"symbol_id": "sym_9999"})
    )

    assert result.ok is False
    assert result.error_code == "TARGET_DENIED"
    assert "sym_9999" in (result.error_message or "")


def test_get_callees_and_callers_include_provenance_and_source_ref(
    executor: ToolExecutor,
) -> None:
    service_update = _find_symbol_id(
        executor,
        "OrderService.updateStatus",
        parameter_count=2,
        tool_call_id="call_find_service",
    )
    mapper_update = _find_symbol_id(
        executor,
        "OrderMapper.updateStatus",
        parameter_count=2,
        tool_call_id="call_find_mapper",
    )

    callees = executor.execute(
        _request(
            "code.get_callees",
            {"symbol_id": service_update},
            tool_call_id="call_callees",
        )
    )
    callers = executor.execute(
        _request(
            "code.get_callers",
            {"symbol_id": mapper_update},
            tool_call_id="call_callers",
        )
    )

    assert callees.ok
    assert callees.data["count"] == 1
    assert callees.data["provenance"] == "ast_heuristic"
    callee = callees.data["items"][0]
    assert callee["callee_symbol_id"] == mapper_update
    assert callee["callee_fqn"] == "com.example.order.OrderMapper"
    assert callee["line"] == 21
    assert callee["source_ref"] == f"repo://{ORDER_SERVICE}#L21"
    assert callee["confidence"] == 0.75
    assert callee["provenance"] == "ast_heuristic"

    assert callers.ok
    assert callers.data["count"] == 1
    caller = callers.data["items"][0]
    assert caller["caller_fqn"] == "com.example.order.OrderService"
    assert caller["confidence"] == 0.75
    assert caller["source_ref"] == f"repo://{ORDER_SERVICE}#L21"


def test_callers_are_truncated_at_limit(executor: ToolExecutor) -> None:
    symbol_id = _find_symbol_id(
        executor,
        "OrderService.updateStatus",
        parameter_count=2,
    )

    result = executor.execute(
        _request(
            "code.get_callers",
            {"symbol_id": symbol_id, "limit": 1},
        )
    )

    assert result.ok
    assert result.data["count"] == 1
    assert result.truncated is True


def test_find_sql_matches_text_table_and_symbol(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("code.find_sql", {"query": "UPDATE orders", "limit": 10})
    )

    assert result.ok
    assert result.data["count"] == 1
    item = result.data["items"][0]
    assert item["fqn"] == "com.example.order.OrderMapper"
    assert item["statement_type"] == "UPDATE"
    assert item["tables"] == ["orders"]
    assert item["source_ref"] == f"repo://{ORDER_MAPPER}#L16"
    assert item["provenance"] == "annotation_sql"

    by_table = executor.execute(
        _request(
            "code.find_sql",
            {"query": "orders", "limit": 10},
            tool_call_id="call_sql_table",
        )
    )
    assert by_table.ok
    assert by_table.data["count"] == 2

    by_symbol = executor.execute(
        _request(
            "code.find_sql",
            {"query": "findStatus", "limit": 10},
            tool_call_id="call_sql_symbol",
        )
    )
    assert by_symbol.ok
    assert by_symbol.data["count"] == 1
    assert by_symbol.data["items"][0]["statement_type"] == "SELECT"


def test_invalid_limits_are_rejected(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("code.find_sql", {"query": "orders", "limit": 21})
    )

    assert result.ok is False
    assert result.error_code == "INVALID_ARGUMENTS"


def test_tool_descriptions_do_not_claim_a_runtime_call_graph() -> None:
    registry = build_default_registry()

    for name in ("code.get_callers", "code.get_callees"):
        spec = registry.get(name)
        assert spec is not None
        assert "AST-heuristic" in spec.spec.description
        assert "not a runtime call graph" in spec.spec.description


def test_call_edges_accept_evidence_binding_metadata(
    executor: ToolExecutor,
) -> None:
    symbol_id = _find_symbol_id(
        executor,
        "OrderService.updateStatus",
        parameter_count=2,
    )
    ledger = EvidenceLedger()
    ledger.add(
        Evidence(
            evidence_id="ev_0001",
            kind=EvidenceKind.LOG_EVENT,
            claim="zero rows were reported",
            source_ref="log://evt_0002",
            provenance=EvidenceProvenance.LOG_PARSER,
            observed_at="2026-10-22T00:00:00+00:00",
        )
    )
    workspace = DiagnosisWorkspace(ledger)
    workspace.propose_hypothesis(
        HypothesisProposal(
            statement="the order row is missing",
            cause_chain=["callback", "zero rows"],
            basis_evidence_ids=["ev_0001"],
            requirements=[
                RequirementProposal(
                    description="the mapper update code",
                    evidence_kinds=[EvidenceKind.SOURCE_CODE],
                    discriminating=True,
                )
            ],
            falsifiers=["the row exists"],
        )
    )
    java_index = TreeSitterJavaIndex()
    java_index.index(REPO_FIXTURE)
    bound_executor = ToolExecutor(
        build_default_registry(),
        ToolContext(
            parsed_log=LogParser().parse(LOG_FIXTURE),
            java_index=java_index,
            repo_root=REPO_FIXTURE,
            log_root=LOG_FIXTURE.parent,
            workspace=workspace,
        ),
    )

    result = bound_executor.execute(
        _request(
            "code.get_callers",
            {
                "symbol_id": symbol_id,
                "hypothesis_id": "hyp_001",
                "requirement_id": "hyp_001_req_01",
            },
            tool_call_id="call_bound",
        )
    )

    assert result.ok, result.error_message
    assert result.bound_hypothesis_id == "hyp_001"
    assert result.bound_requirement_id == "hyp_001_req_01"


def test_logger_and_stack_frame_queries_resolve_to_code(
    executor: ToolExecutor,
) -> None:
    logger = executor.execute(
        _request(
            "code.find_symbol",
            {"query": "c.e.order.OrderService"},
            tool_call_id="call_logger",
        )
    )
    frame = executor.execute(
        _request(
            "code.find_symbol",
            {"query": "com.example.order.OrderMapper"},
            tool_call_id="call_frame",
        )
    )

    assert logger.ok
    assert {
        item["fqn"] for item in logger.data["items"]
    } == {"com.example.order.OrderService"}
    assert any(item.get("method_name") is None for item in logger.data["items"])
    assert frame.ok
    assert {
        item["class_name"] for item in frame.data["items"]
    } == {"OrderMapper"}
