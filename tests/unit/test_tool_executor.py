"""Unit tests for the controlled tool executor and built-in tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.log_analysis.parser import LogParser
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import (
    ToolContext,
    ToolHandlerResult,
    ToolRequest,
    ToolSpec,
)
from tracemind.tools.executor import ToolExecutor
from tracemind.tools.registry import ToolRegistry

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


def test_logs_search(executor: ToolExecutor) -> None:
    result = executor.execute(_request("logs.search", {"query": "rows=0"}))

    assert result.ok
    assert result.data["total_matched"] == 1
    item = result.data["items"][0]
    assert item["event_id"] == "evt_0002"
    assert item["source_ref"] == "log://evt_0002"
    assert result.source_ref == "log://evt_0002"


def test_logs_get_event_context(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request(
            "logs.get_event_context",
            {"event_id": "evt_0003", "before": 2, "after": 0},
        )
    )

    assert result.ok
    assert [item["event_id"] for item in result.data["items"]] == [
        "evt_0001",
        "evt_0002",
        "evt_0003",
    ]
    assert result.source_ref == "log://evt_0003"
    assert result.truncated is False


def test_logs_get_thread_context_defaults_to_primary(
    executor: ToolExecutor,
) -> None:
    result = executor.execute(
        _request("logs.get_thread_context", {"before": 3, "after": 3})
    )

    assert result.ok
    assert result.data["anchor_event_id"] == "evt_0003"
    assert result.data["thread"] == "http-nio-8080-exec-7"
    assert result.data["count"] == 3
    assert result.data["truncated"] is False
    assert result.source_ref == (
        "log://incident.log#thread=http-nio-8080-exec-7&L1-L3"
    )
    assert [item["event_id"] for item in result.data["items"]] == [
        "evt_0001",
        "evt_0002",
        "evt_0003",
    ]
    assert all(
        item["logger_class"]
        for item in result.data["items"]
    )
    assert all(
        "stack_frames" not in item
        for item in result.data["items"]
    )


def test_logs_get_thread_context_respects_radius(
    executor: ToolExecutor,
) -> None:
    result = executor.execute(
        _request(
            "logs.get_thread_context",
            {"event_id": "evt_0003", "before": 1, "after": 0},
        )
    )

    assert result.ok
    assert [item["event_id"] for item in result.data["items"]] == [
        "evt_0002",
        "evt_0003",
    ]
    assert result.data["line_start"] == 2
    assert result.data["line_end"] == 3
    assert result.data["truncated"] is True


def test_logs_get_thread_context_excludes_other_threads(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "threads.log"
    log_path.write_text(
        "2026-10-18 10:21:03.412 INFO  [http-a] c.e.X - start\n"
        "2026-10-18 10:21:03.413 INFO  [http-b] c.e.Y - other\n"
        "2026-10-18 10:21:03.416 ERROR [http-a] c.e.X - boom\n"
        "java.lang.IllegalStateException: boom\n"
        "    at com.example.order.OrderService.updateStatus(OrderService.java:24)\n",
        encoding="utf-8",
    )
    parsed = LogParser().parse(log_path)
    java_index = TreeSitterJavaIndex()
    java_index.index(REPO_FIXTURE)
    context = ToolContext(
        parsed_log=parsed,
        java_index=java_index,
        repo_root=REPO_FIXTURE,
        log_root=tmp_path,
    )
    executor = ToolExecutor(build_default_registry(), context)

    result = executor.execute(
        _request("logs.get_thread_context", {"event_id": "evt_0003"})
    )

    assert result.ok
    threads = {item["thread"] for item in result.data["items"]}
    assert threads == {"http-a"}
    assert [item["event_id"] for item in result.data["items"]] == [
        "evt_0001",
        "evt_0003",
    ]


def test_logs_get_thread_context_rejects_missing_thread(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "no-thread.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR c.e.X - boom\n"
        "java.lang.IllegalStateException: boom\n",
        encoding="utf-8",
    )
    parsed = LogParser().parse(log_path)
    executor = ToolExecutor(
        build_default_registry(),
        ToolContext(parsed_log=parsed, log_root=tmp_path),
    )

    result = executor.execute(
        _request("logs.get_thread_context", {"event_id": "evt_0001"})
    )

    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"
    assert "thread" in (result.error_message or "").lower()


def test_logs_get_thread_context_rejects_unknown_event(
    executor: ToolExecutor,
) -> None:
    result = executor.execute(
        _request("logs.get_thread_context", {"event_id": "evt_9999"})
    )

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"


def test_logs_get_thread_context_rejects_large_radius(
    executor: ToolExecutor,
) -> None:
    result = executor.execute(
        _request("logs.get_thread_context", {"before": 21})
    )

    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"


def test_code_find_symbol(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("code.find_symbol", {"query": "OrderService.updateStatus"})
    )

    assert result.ok
    assert result.data["items"]
    assert result.data["items"][0]["file_path"].endswith("OrderService.java")
    assert result.source_ref is not None
    assert result.source_ref.startswith("repo://")


def test_code_get_source_range(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request(
            "code.get_source_range",
            {"file_path": ORDER_SERVICE, "start_line": 20, "end_line": 26},
        )
    )

    assert result.ok
    assert "24:" in result.data["text"]
    assert "throw new IllegalStateException" in result.data["text"]
    assert result.source_ref == f"repo://{ORDER_SERVICE}#L20-L26"


def test_code_get_source_range_max_lines(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request(
            "code.get_source_range",
            {
                "file_path": ORDER_SERVICE,
                "start_line": 1,
                "end_line": 100,
                "max_lines": 5,
            },
        )
    )

    assert result.ok
    assert result.truncated is True
    assert result.data["end_line"] == 5


def test_path_escape_is_denied(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request(
            "code.get_source_range",
            {"file_path": "../etc/passwd", "start_line": 1, "end_line": 2},
        )
    )

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"


def test_absolute_path_is_denied(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request(
            "code.get_source_range",
            {"file_path": "/etc/passwd", "start_line": 1, "end_line": 2},
        )
    )

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"


def test_symlink_escape_is_denied(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.java"
    outside.write_text("class Outside {}\n", encoding="utf-8")
    (repo / "link.java").symlink_to(outside)

    context = ToolContext(
        java_index=TreeSitterJavaIndex(),
        repo_root=repo,
    )
    executor = ToolExecutor(build_default_registry(), context)
    result = executor.execute(
        _request(
            "code.get_source_range",
            {"file_path": "link.java", "start_line": 1, "end_line": 1},
        )
    )

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"


def test_unknown_tool_is_denied(executor: ToolExecutor) -> None:
    result = executor.execute(_request("shell.execute", {"command": "rm -rf /"}))

    assert not result.ok
    assert result.error_code == "TOOL_NOT_FOUND"


def test_invalid_arguments_are_rejected(executor: ToolExecutor) -> None:
    bad_limit = executor.execute(
        _request("logs.search", {"query": "rows=0", "limit": 999})
    )
    extra_field = executor.execute(
        _request("logs.search", {"query": "rows=0", "extra": True})
    )

    assert bad_limit.error_code == "INVALID_ARGUMENTS"
    assert extra_field.error_code == "INVALID_ARGUMENTS"


def test_missing_event_is_denied(executor: ToolExecutor) -> None:
    result = executor.execute(
        _request("logs.get_event_context", {"event_id": "evt_9999"})
    )

    assert not result.ok
    assert result.error_code == "TARGET_DENIED"


def test_duplicate_call_is_not_executed(executor: ToolExecutor) -> None:
    first = executor.execute(
        _request("logs.search", {"query": "rows=0"}, tool_call_id="call_1")
    )
    second = executor.execute(
        _request("logs.search", {"query": "rows=0"}, tool_call_id="call_2")
    )

    assert first.ok
    assert not second.ok
    assert second.error_code == "DUPLICATE_CALL"


def test_output_limit_truncates() -> None:
    class LargeArgs(BaseModel):
        size: int = 1000

    def _large(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
        return ToolHandlerResult(data="x" * getattr(args, "size", 1000))

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo.large",
            description="large output",
            input_model=LargeArgs,
            max_output_bytes=100,
        ),
        _large,
    )
    executor = ToolExecutor(registry, ToolContext())

    result = executor.execute(_request("demo.large", {"size": 1000}))

    assert result.ok
    assert result.truncated is True
    assert isinstance(result.data, str)
    assert len(result.data.encode("utf-8")) <= 100


def test_audit_events_record_outcomes(executor: ToolExecutor) -> None:
    executor.execute(_request("logs.search", {"query": "rows=0"}, "call_1"))
    executor.execute(_request("logs.search", {"query": "rows=0"}, "call_2"))
    executor.execute(
        _request(
            "code.get_source_range",
            {"file_path": "../etc/passwd", "start_line": 1, "end_line": 2},
            "call_3",
        )
    )

    outcomes = [event.outcome for event in executor.audit_events]
    assert outcomes == ["allowed", "duplicate", "denied"]
    assert executor.audit_events[0].run_id == "run_test"
    assert executor.audit_events[0].tool_name == "logs.search"
    assert executor.audit_events[0].tool_call_id == "call_1"
