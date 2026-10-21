"""Unit tests for the tree-sitter Java source index."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracemind.core.errors import JavaIndexError
from tracemind.core.models import StackFrame
from tracemind.indexing.java_index import TreeSitterJavaIndex

FIXTURE_REPO = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
ORDER_SERVICE = "src/main/java/com/example/order/OrderService.java"
ORDER_CONTROLLER = "src/main/java/com/example/order/OrderController.java"
ORDER_MAPPER = "src/main/java/com/example/order/OrderMapper.java"


@pytest.fixture()
def index() -> TreeSitterJavaIndex:
    java_index = TreeSitterJavaIndex()
    java_index.index(FIXTURE_REPO)
    return java_index


def _frame(
    class_name: str,
    method_name: str,
    file_name: str,
    line_number: int,
) -> StackFrame:
    return StackFrame(
        class_name=class_name,
        method_name=method_name,
        file_name=file_name,
        line_number=line_number,
        raw="",
    )


def test_index_stats() -> None:
    stats = TreeSitterJavaIndex().index(FIXTURE_REPO)

    assert stats.parser == "tree_sitter"
    assert stats.files_indexed == 3
    assert stats.symbols_indexed >= 15
    assert stats.errors == []


def test_find_symbol_class_and_method(index: TreeSitterJavaIndex) -> None:
    classes = [
        symbol
        for symbol in index.find_symbol("com.example.order.OrderService")
        if symbol.method_name is None
    ]
    assert classes
    assert classes[0].fqn == "com.example.order.OrderService"
    assert classes[0].symbol_type == "class"

    methods = index.find_symbol("OrderService.updateStatus")
    assert methods
    assert methods[0].fqn == "com.example.order.OrderService"
    assert methods[0].method_name == "updateStatus"
    assert methods[0].start_line == 17
    assert methods[0].end_line == 27


def test_find_nested_class(index: TreeSitterJavaIndex) -> None:
    matches = [
        symbol
        for symbol in index.find_symbol("Nested")
        if symbol.symbol_type == "class"
    ]
    assert matches
    assert matches[0].fqn == "com.example.order.OrderService$Nested"


def test_find_unknown_symbol_returns_empty(index: TreeSitterJavaIndex) -> None:
    assert index.find_symbol("does.not.Exist") == []


def test_resolve_order_service_frame(index: TreeSitterJavaIndex) -> None:
    matches = index.resolve_frame(
        _frame(
            "com.example.order.OrderService",
            "updateStatus",
            "OrderService.java",
            24,
        )
    )

    assert matches
    top = matches[0]
    assert top.file_path == ORDER_SERVICE
    assert top.start_line == 17
    assert top.end_line == 27
    assert top.confidence == 0.95
    assert top.match_reason == "fqn_method_line"
    assert top.provenance == "tree_sitter"


def test_resolve_overloaded_method_prefers_line_range(index: TreeSitterJavaIndex) -> None:
    matches = index.resolve_frame(
        _frame(
            "com.example.order.OrderService",
            "updateStatus",
            "OrderService.java",
            30,
        )
    )

    assert matches
    assert matches[0].start_line == 29
    assert matches[0].end_line == 31
    assert matches[0].confidence == 0.95


def test_resolve_controller_and_mapper_frames(index: TreeSitterJavaIndex) -> None:
    controller = index.resolve_frame(
        _frame(
            "com.example.order.OrderController",
            "handlePaid",
            "OrderController.java",
            41,
        )
    )
    mapper = index.resolve_frame(
        _frame(
            "com.example.order.OrderMapper",
            "updateStatus",
            "OrderMapper.java",
            18,
        )
    )

    assert controller and controller[0].file_path == ORDER_CONTROLLER
    assert controller[0].confidence == 0.95
    assert mapper and mapper[0].file_path == ORDER_MAPPER
    assert mapper[0].confidence == 0.95


def test_resolve_nested_class_frame(index: TreeSitterJavaIndex) -> None:
    matches = index.resolve_frame(
        _frame(
            "com.example.order.OrderService$Nested",
            "ping",
            "OrderService.java",
            35,
        )
    )

    assert matches
    assert matches[0].symbol.fqn == "com.example.order.OrderService$Nested"


def test_resolve_constructor_frame(index: TreeSitterJavaIndex) -> None:
    matches = index.resolve_frame(
        _frame(
            "com.example.order.OrderService",
            "<init>",
            "OrderService.java",
            10,
        )
    )

    assert matches
    assert matches[0].symbol.symbol_type == "constructor"


def test_resolve_line_outside_method_has_lower_confidence(
    index: TreeSitterJavaIndex,
) -> None:
    matches = index.resolve_frame(
        _frame(
            "com.example.order.OrderService",
            "updateStatus",
            "OrderService.java",
            999,
        )
    )

    assert matches
    assert matches[0].confidence == 0.70
    assert matches[0].match_reason == "fqn_method"


def test_resolve_missing_class_returns_empty(index: TreeSitterJavaIndex) -> None:
    assert (
        index.resolve_frame(
            _frame("com.example.missing.MissingService", "run", "MissingService.java", 1)
        )
        == []
    )


def test_get_source_range(index: TreeSitterJavaIndex) -> None:
    snippet = index.get_source_range(ORDER_SERVICE, 20, 26)

    assert snippet.file_path == ORDER_SERVICE
    assert snippet.start_line == 20
    assert snippet.end_line == 26
    assert snippet.truncated is False
    assert "24:" in snippet.text
    assert "throw new IllegalStateException" in snippet.text


def test_get_source_range_clamps(index: TreeSitterJavaIndex) -> None:
    snippet = index.get_source_range(ORDER_SERVICE, 1, 999)

    assert snippet.start_line == 1
    assert snippet.end_line == 38
    assert snippet.truncated is True


def test_get_source_range_rejects_path_escape(index: TreeSitterJavaIndex) -> None:
    with pytest.raises(JavaIndexError):
        index.get_source_range("../etc/passwd", 1, 2)


def test_get_source_range_missing_file(index: TreeSitterJavaIndex) -> None:
    with pytest.raises(JavaIndexError):
        index.get_source_range("src/main/java/com/example/Missing.java", 1, 2)


def test_get_source_range_before_index() -> None:
    with pytest.raises(JavaIndexError):
        TreeSitterJavaIndex().get_source_range(ORDER_SERVICE, 1, 2)
