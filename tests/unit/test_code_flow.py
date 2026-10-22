"""Unit tests for AST-heuristic Java call-flow indexing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracemind.indexing.java_index import JavaSymbol, TreeSitterJavaIndex

FIXTURE_REPO = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
ORDER_CONTROLLER = "src/main/java/com/example/order/OrderController.java"
ORDER_MAPPER = "src/main/java/com/example/order/OrderMapper.java"
ORDER_SERVICE = "src/main/java/com/example/order/OrderService.java"


@pytest.fixture()
def index() -> TreeSitterJavaIndex:
    java_index = TreeSitterJavaIndex()
    java_index.index(FIXTURE_REPO)
    return java_index


def _symbol(
    index: TreeSitterJavaIndex,
    query: str,
    *,
    parameter_count: int | None = None,
) -> JavaSymbol:
    matches = [
        symbol
        for symbol in index.find_symbol(query)
        if parameter_count is None or symbol.parameter_count == parameter_count
    ]
    assert matches
    return matches[0]


def test_controller_to_service_call_edge(index: TreeSitterJavaIndex) -> None:
    controller = _symbol(index, "OrderController.paid", parameter_count=1)
    service = _symbol(index, "OrderService.handlePaid", parameter_count=1)

    edges = index.get_callees(controller.symbol_id)

    edge = next(edge for edge in edges if edge.callee_symbol_id == service.symbol_id)
    assert edge.caller_fqn == "com.example.order.OrderController"
    assert edge.callee_fqn == "com.example.order.OrderService"
    assert edge.file_path == ORDER_CONTROLLER
    assert edge.line == 16
    assert edge.receiver == "orderService"
    assert edge.confidence == 0.75
    assert edge.provenance == "ast_heuristic"


def test_self_call_and_mapper_field_call_edges(index: TreeSitterJavaIndex) -> None:
    handle_paid = _symbol(index, "OrderService.handlePaid", parameter_count=1)
    update_status = _symbol(index, "OrderService.updateStatus", parameter_count=2)
    mapper_update = _symbol(index, "OrderMapper.updateStatus", parameter_count=2)

    self_edges = index.get_callees(handle_paid.symbol_id)
    mapper_edges = index.get_callees(update_status.symbol_id)

    self_edge = next(
        edge for edge in self_edges if edge.callee_symbol_id == update_status.symbol_id
    )
    mapper_edge = next(
        edge for edge in mapper_edges if edge.callee_symbol_id == mapper_update.symbol_id
    )
    assert self_edge.receiver == "this"
    assert self_edge.confidence == 0.90
    assert self_edge.line == 14
    assert mapper_edge.receiver == "orderMapper"
    assert mapper_edge.confidence == 0.75
    assert mapper_edge.line == 21
    assert mapper_edge.file_path == ORDER_SERVICE


def test_mapper_default_method_implicit_self_call(index: TreeSitterJavaIndex) -> None:
    exists = _symbol(index, "OrderMapper.exists", parameter_count=1)
    find_status = _symbol(index, "OrderMapper.findStatus", parameter_count=1)

    edges = index.get_callees(exists.symbol_id)

    edge = next(edge for edge in edges if edge.callee_symbol_id == find_status.symbol_id)
    assert edge.receiver is None
    assert edge.confidence == 0.90


def test_overload_is_filtered_by_argument_count(index: TreeSitterJavaIndex) -> None:
    handle_paid = _symbol(index, "OrderService.handlePaid", parameter_count=1)
    update_two = _symbol(index, "OrderService.updateStatus", parameter_count=2)
    update_one = _symbol(index, "OrderService.updateStatus", parameter_count=1)

    callees = index.get_callees(handle_paid.symbol_id)

    target_ids = {edge.callee_symbol_id for edge in callees}
    assert update_two.symbol_id in target_ids
    assert update_one.symbol_id not in target_ids


def test_callers_are_the_inverse_of_callees(index: TreeSitterJavaIndex) -> None:
    update_two = _symbol(index, "OrderService.updateStatus", parameter_count=2)
    mapper_update = _symbol(index, "OrderMapper.updateStatus", parameter_count=2)

    callers = index.get_callers(update_two.symbol_id)
    mapper_callers = index.get_callers(mapper_update.symbol_id)

    assert {edge.caller_fqn for edge in callers} == {"com.example.order.OrderService"}
    assert len(callers) == 2
    assert [edge.caller_fqn for edge in mapper_callers] == [
        "com.example.order.OrderService"
    ]


def test_annotation_sql_is_extracted(index: TreeSitterJavaIndex) -> None:
    update_status = _symbol(index, "OrderMapper.updateStatus", parameter_count=2)

    artifacts = index.find_sql("UPDATE orders")
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.symbol_id == update_status.symbol_id
    assert artifact.file_path == ORDER_MAPPER
    assert artifact.start_line == 16
    assert artifact.end_line == 16
    assert artifact.statement_type == "UPDATE"
    assert artifact.tables == ["orders"]
    assert "#{status}" in artifact.sql_text
    assert artifact.provenance == "annotation_sql"


def test_sql_can_be_found_by_table_symbol_and_statement_type(
    index: TreeSitterJavaIndex,
) -> None:
    assert {
        item.symbol_id for item in index.find_sql("orders")
    } == {
        _symbol(index, "OrderMapper.updateStatus", parameter_count=2).symbol_id,
        _symbol(index, "OrderMapper.findStatus", parameter_count=1).symbol_id,
    }
    assert len(index.find_sql("findStatus")) == 1
    assert len(index.find_sql("SELECT")) == 1


def test_static_import_resolves_unqualified_call(tmp_path: Path) -> None:
    util = tmp_path / "src" / "com" / "example" / "util"
    util.mkdir(parents=True)
    caller_dir = tmp_path / "src" / "com" / "example" / "flow"
    caller_dir.mkdir(parents=True)
    (util / "Helper.java").write_text(
        "package com.example.util;\n"
        "public class Helper { public static void run() {} }\n",
        encoding="utf-8",
    )
    (caller_dir / "Caller.java").write_text(
        "package com.example.flow;\n"
        "import static com.example.util.Helper.run;\n"
        "public class Caller { public void go() { run(); } }\n",
        encoding="utf-8",
    )
    index = TreeSitterJavaIndex()
    index.index(tmp_path)
    caller = _symbol(index, "Caller.go")

    edges = index.get_callees(caller.symbol_id)

    assert len(edges) == 1
    assert edges[0].callee_fqn == "com.example.util.Helper"
    assert edges[0].callee_symbol_id == _symbol(
        index, "Helper.run"
    ).symbol_id
    assert edges[0].confidence == 0.65


def test_unresolved_receiver_falls_back_to_all_arity_candidates(tmp_path: Path) -> None:
    src = tmp_path / "src" / "com" / "example" / "flow"
    src.mkdir(parents=True)
    (src / "Alpha.java").write_text(
        "package com.example.flow;\n"
        "public class Alpha { public void call() {} }\n",
        encoding="utf-8",
    )
    (src / "Beta.java").write_text(
        "package com.example.flow;\n"
        "public class Beta { public void call() {} }\n",
        encoding="utf-8",
    )
    (src / "Caller.java").write_text(
        "package com.example.flow;\n"
        "public class Caller {\n"
        "    private External external;\n"
        "    public void run() { external.call(); }\n"
        "}\n",
        encoding="utf-8",
    )
    index = TreeSitterJavaIndex()
    index.index(tmp_path)
    caller = _symbol(index, "Caller.run")

    edges = index.get_callees(caller.symbol_id)

    assert {edge.callee_fqn for edge in edges} == {
        "com.example.flow.Alpha",
        "com.example.flow.Beta",
    }
    assert all(edge.confidence == 0.30 for edge in edges)
    assert all(edge.provenance == "ast_heuristic" for edge in edges)
