"""Integration tests for the v0.1 minimal diagnosis runtime."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.budget import Budget
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.diagnosis.state import RuntimeState, StopReason
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
    ToolCall,
    ToolDefinition,
)
from tracemind.llm.mock import MockProvider
from tracemind.llm.provider import LLMProviderError
from tracemind.log_analysis.parser import LogParser

LOG_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logs" / "basic" / "incident.log"
)
REPO_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "repos"
    / "minimal-order-service"
)
MOCK_SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "mock_responses.json"


def _index() -> TreeSitterJavaIndex:
    index = TreeSitterJavaIndex()
    index.index(REPO_FIXTURE)
    return index


def _run(provider: object, budget: Budget | None = None):
    parsed = LogParser().parse(LOG_FIXTURE)
    runtime = DiagnosisRuntime(repo_root=REPO_FIXTURE)
    return runtime.run(
        parsed,
        _index(),
        "order-service",
        provider,  # type: ignore[arg-type]
        budget,
    )


def test_happy_path_confirms_hypothesis() -> None:
    result = _run(MockProvider.from_script(MOCK_SCRIPT))

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert result.incident_id.startswith("inc_")
    assert result.run_id.startswith("run_")
    assert result.service == "order-service"

    hypothesis = result.hypotheses[0]
    assert hypothesis.status == "confirmed"
    assert hypothesis.missing_evidence == []
    assert hypothesis.source_matches

    kinds = {item.kind for item in result.evidence}
    assert {"stack_frame", "log_event", "source_code"} <= kinds
    assert any(
        item.kind == "source_code" and "OrderService.java" in item.source_ref
        for item in result.evidence
    )

    assert [record.tool_name for record in result.tool_calls] == [
        "code.find_symbol",
        "logs.search",
    ]
    assert all(record.ok for record in result.tool_calls)
    assert result.budget_usage == {
        "iterations": 1,
        "llm_calls": 1,
        "tool_calls": 2,
    }

    event_types = {event.event_type for event in result.events}
    assert {
        "diagnosis.started",
        "state.changed",
        "hypothesis.created",
        "evidence.created",
        "llm.called",
        "tool.called",
        "agent.stop_triggered",
    } <= event_types


def test_empty_plan_stops_with_no_progress() -> None:
    result = _run(MockProvider([]))

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.budget_usage["llm_calls"] == 3
    assert result.budget_usage["tool_calls"] == 0
    assert result.hypotheses[0].status == "supported"
    assert result.hypotheses[0].missing_evidence == ["source_code"]
    assert sum(
        1 for event in result.events if event.event_type == "agent.repair"
    ) == 2


class AlwaysToolProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="logs.search",
                    arguments={"query": "rows=0"},
                )
            ],
            finish_reason="tool_calls",
        )


def test_budget_exhaustion_stops_with_budget_reason() -> None:
    result = _run(
        AlwaysToolProvider(),
        Budget(max_iterations=1, max_tool_calls=8),
    )

    assert result.state is RuntimeState.STOPPED_BUDGET
    assert result.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert result.budget_usage["iterations"] == 1
    assert result.budget_usage["llm_calls"] == 1
    assert result.budget_usage["tool_calls"] == 1
    assert len(result.tool_calls) == 1


class DuplicateThenEmptyProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            call = ToolCall(
                id="call_1",
                name="logs.search",
                arguments={"query": "rows=0"},
            )
            return LLMResponse(
                content="",
                tool_calls=[
                    call,
                    ToolCall(
                        id="call_2",
                        name="logs.search",
                        arguments={"query": "rows=0"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(finish_reason="stop")


def test_duplicate_tool_call_is_not_executed_twice() -> None:
    result = _run(DuplicateThenEmptyProvider())

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert len(result.tool_calls) == 2
    assert result.tool_calls[1].error_code == "DUPLICATE_CALL"
    log_evidence = [item for item in result.evidence if item.kind == "log_event"]
    assert len(log_evidence) == 2  # one seed event + one tool result


class FailingProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        raise LLMProviderError("upstream failure", code="provider_error")


def test_provider_error_fails_without_crashing() -> None:
    result = _run(FailingProvider())

    assert result.state is RuntimeState.FAILED
    assert result.stop_reason is StopReason.ERROR
    assert result.hypotheses[0].status == "supported"
    assert any(event.event_type == "llm.error" for event in result.events)
