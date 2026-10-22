"""Tests for LLM usage, latency, and provenance propagation."""

from __future__ import annotations

from pathlib import Path

from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.diagnosis.state import RuntimeState, StopReason
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
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


class FailingProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        raise LLMProviderError(
            "upstream failed",
            code="provider_error",
            attempts=2,
            request_id="req-failed",
        )


def test_runtime_records_llm_usage() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    runtime = DiagnosisRuntime(
        repo_root=REPO_FIXTURE,
        provider_name="mock",
        model="script",
    )

    result = runtime.run(
        parsed,
        _index(),
        "order-service",
        MockProvider.from_script(MOCK_SCRIPT),
    )

    assert result.state is RuntimeState.COMPLETED
    assert len(result.llm_calls) == 3
    first, second, third = result.llm_calls
    assert first.llm_call_id == "llm_0001"
    assert first.round == 1
    assert first.provider == "mock"
    assert first.model == "script"
    assert first.request_id is None
    assert first.latency_ms >= 0
    assert first.attempts == 1
    assert first.ok is True
    assert first.finish_reason == "tool_calls"
    assert first.tool_calls == 5
    assert first.input_tokens == 100
    assert first.output_tokens == 30
    assert first.total_tokens == 130
    assert second.llm_call_id == "llm_0002"
    assert second.round == 2
    assert second.tool_calls == 1
    assert second.input_tokens == 120
    assert second.output_tokens == 10
    assert third.llm_call_id == "llm_0003"
    assert third.round == 3
    assert third.tool_calls == 1
    assert third.input_tokens == 140
    assert third.output_tokens == 40
    assert third.total_tokens == 180

    usage = result.llm_usage
    assert usage.calls == 3
    assert usage.failed_calls == 0
    assert usage.retries == 0
    assert usage.input_tokens == 360
    assert usage.output_tokens == 80
    assert usage.total_tokens == 440
    assert usage.latency_ms == (
        first.latency_ms + second.latency_ms + third.latency_ms
    )
    assert result.budget_usage == {
        "iterations": 3,
        "llm_calls": 3,
        "tool_calls": 7,
        "hypotheses": 2,
        "assessments": 3,
        "remediation_actions": 1,
    }

    called = next(
        event for event in result.events if event.event_type == "llm.called"
    )
    assert called.data["input_tokens"] == 100
    assert called.data["attempts"] == 1
    assert called.data["llm_call_id"] == "llm_0001"
    assert called.data["tool_calls"] == 5

    remediation_call = [
        event
        for event in result.events
        if event.event_type == "llm.called"
        and event.data.get("phase") == "remediation"
    ]
    assert len(remediation_call) == 1
    assert remediation_call[0].data["llm_call_id"] == "llm_0003"


def test_failed_llm_call_is_recorded() -> None:
    parsed = LogParser().parse(LOG_FIXTURE)
    runtime = DiagnosisRuntime(
        repo_root=REPO_FIXTURE,
        provider_name="deepseek",
        model="deepseek-flash",
    )

    result = runtime.run(
        parsed,
        _index(),
        "order-service",
        FailingProvider(),
    )

    assert result.state is RuntimeState.FAILED
    assert result.stop_reason is StopReason.ERROR
    assert len(result.llm_calls) == 1
    call = result.llm_calls[0]
    assert call.ok is False
    assert call.error_code == "provider_error"
    assert call.attempts == 2
    assert call.request_id == "req-failed"
    assert call.provider == "deepseek"
    assert call.model == "deepseek-flash"
    assert result.llm_usage.calls == 1
    assert result.llm_usage.failed_calls == 1
    assert result.llm_usage.retries == 1

    error_event = next(
        event for event in result.events if event.event_type == "llm.error"
    )
    assert error_event.data["attempts"] == 2
    assert error_event.data["request_id"] == "req-failed"
