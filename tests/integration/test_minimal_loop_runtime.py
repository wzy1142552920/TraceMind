"""Integration tests for the grounded diagnosis runtime happy path."""

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


def test_happy_path_confirms_grounded_hypothesis() -> None:
    result = _run(MockProvider.from_script(MOCK_SCRIPT))

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert result.incident_id.startswith("inc_")
    assert result.run_id.startswith("run_")
    assert result.service == "order-service"
    assert result.evaluation.run_confirmed is True
    assert result.evaluation.ambiguity is False
    assert result.evaluation.top_hypothesis_id == "hyp_001"

    confirmed = next(
        item for item in result.hypotheses if item.hypothesis_id == "hyp_001"
    )
    contradicted = next(
        item for item in result.hypotheses if item.hypothesis_id == "hyp_002"
    )
    assert confirmed.status == "confirmed"
    assert confirmed.missing_requirement_ids == []
    assert contradicted.status == "contradicted"

    kinds = {item.kind for item in result.evidence}
    assert {
        "log_event",
        "log_thread_context",
        "stack_frame",
        "source_code",
        "sql",
    } <= kinds
    assert any(
        item.kind == "source_code" and "OrderService.java" in item.source_ref
        for item in result.evidence
    )
    context = next(
        item
        for item in result.evidence
        if item.kind == "log_thread_context"
    )
    assert context.bound_hypothesis_id == "hyp_001"
    assert context.bound_requirement_id == "hyp_001_req_01"
    assert context.tool_call_id == "call_3"
    assert context.content["thread"] == "http-nio-8080-exec-7"

    assert [record.tool_name for record in result.tool_calls] == [
        "diagnosis.propose_hypothesis",
        "diagnosis.propose_hypothesis",
        "logs.get_thread_context",
        "code.find_symbol",
        "code.find_sql",
        "diagnosis.assess_evidence",
        "diagnosis.propose_remediation",
    ]
    assert all(record.ok for record in result.tool_calls)
    assert result.rejected_hypotheses == []
    assert result.rejected_remediations == []
    assert [action.hypothesis_id for action in result.remediation_actions] == [
        "hyp_001"
    ]
    assert result.remediation_actions[0].type == "code"
    assert result.budget_usage == {
        "iterations": 3,
        "llm_calls": 3,
        "tool_calls": 7,
        "hypotheses": 2,
        "assessments": 3,
        "remediation_actions": 1,
    }

    event_types = {event.event_type for event in result.events}
    assert {
        "diagnosis.started",
        "state.changed",
        "hypothesis.created",
        "hypothesis.updated",
        "assessment.created",
        "evidence.created",
        "evidence.bound",
        "llm.called",
        "tool.called",
        "remediation.created",
        "agent.stop_triggered",
    } <= event_types


def test_empty_plan_repairs_then_stops_with_no_progress() -> None:
    result = _run(MockProvider([]))

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.budget_usage["iterations"] == 3
    assert result.budget_usage["llm_calls"] == 3
    assert result.budget_usage["tool_calls"] == 0
    assert result.hypotheses == []
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
            return LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="logs.search",
                        arguments={"query": "rows=0"},
                    ),
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
    assert len(log_evidence) == 2  # primary seed event + one tool result


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
    assert result.hypotheses == []
    assert any(event.event_type == "llm.error" for event in result.events)
