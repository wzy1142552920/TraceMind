"""Fake live-like tests for bounded repair under the grounded protocol."""

from __future__ import annotations

import json
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


class ScriptedProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.prompts: list[list[Message]] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        self.prompts.append(messages)
        if not self.responses:
            return LLMResponse(content="", tool_calls=[], finish_reason="stop")
        return self.responses.pop(0)


def _fixture_responses() -> list[LLMResponse]:
    data = json.loads(MOCK_SCRIPT.read_text(encoding="utf-8"))
    return [LLMResponse.model_validate(item) for item in data["responses"]]


def _run(provider: ScriptedProvider, budget: Budget | None = None):
    parsed = LogParser().parse(LOG_FIXTURE)
    index = TreeSitterJavaIndex()
    index.index(REPO_FIXTURE)
    runtime = DiagnosisRuntime(
        repo_root=REPO_FIXTURE,
        provider_name="mock",
        model="live-like",
        repair_attempts=2,
    )
    return runtime.run(parsed, index, "order-service", provider, budget)


def _user_prompt(provider: ScriptedProvider, index: int) -> str:
    messages = provider.prompts[index]
    return next(message.content for message in messages if message.role == "user")


def test_text_only_repair_recovers() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="I will inspect the source.",
                tool_calls=[],
                finish_reason="stop",
            ),
            *_fixture_responses(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert result.hypotheses[0].status == "confirmed"
    assert len(result.llm_calls) == 4
    assert any(
        event.event_type == "agent.repair" for event in result.events
    )
    second_prompt = _user_prompt(provider, 1)
    assert "Previous observation" in second_prompt
    assert "I will inspect the source." in second_prompt
    assert "no_hypotheses" in second_prompt


def test_safe_llm_tool_name_maps_to_internal_tool() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="safe_name",
                        name="code_find_symbol",
                        arguments={"query": "OrderService.updateStatus"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            *_fixture_responses(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.tool_calls[0].tool_name == "code.find_symbol"
    assert result.tool_calls[0].ok is True


def test_unknown_tool_repair_recovers() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="bad_call",
                        name="shell.execute",
                        arguments={"command": "rm -rf /"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            *_fixture_responses(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.tool_calls[0].error_code == "TOOL_NOT_FOUND"
    assert len(result.llm_calls) == 4
    assert "TOOL_NOT_FOUND" in _user_prompt(provider, 1)
    assert "unknown_tool" in _user_prompt(provider, 1)


def test_invalid_arguments_repair_recovers() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="bad_args",
                        name="logs.search",
                        arguments={"query": ""},
                    )
                ],
                finish_reason="tool_calls",
            ),
            *_fixture_responses(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.tool_calls[0].error_code == "INVALID_ARGUMENTS"
    assert len(result.llm_calls) == 4
    assert "INVALID_ARGUMENTS" in _user_prompt(provider, 1)
    assert "invalid_arguments" in _user_prompt(provider, 1)


def test_length_finish_reason_does_not_execute_tool_call() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="partial plan",
                tool_calls=[
                    ToolCall(
                        id="partial_call",
                        name="code.find_symbol",
                        arguments={"query": "OrderService.updateStatus"},
                    )
                ],
                finish_reason="length",
            ),
            *_fixture_responses(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert all(
        record.tool_call_id != "partial_call"
        for record in result.tool_calls
    )
    assert result.llm_calls[0].finish_reason == "length"
    assert "length" in _user_prompt(provider, 1)


def test_repair_is_bounded_by_iteration_budget() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(content="text only", tool_calls=[], finish_reason="stop"),
            LLMResponse(
                content="still text",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    result = _run(provider, Budget(max_iterations=2, max_tool_calls=8))

    assert result.state is RuntimeState.STOPPED_BUDGET
    assert result.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert len(result.llm_calls) == 2
    assert result.hypotheses == []


def test_remediation_is_skipped_when_llm_budget_is_exhausted() -> None:
    provider = ScriptedProvider(_fixture_responses())

    result = _run(provider, Budget(max_llm_calls=2))

    assert result.state is RuntimeState.COMPLETED
    assert result.hypotheses[0].status == "confirmed"
    assert len(result.llm_calls) == 2
    assert result.remediation_actions == []
    assert any(
        "Remediation was skipped" in item for item in result.limitations
    )


def test_model_prose_cannot_confirm() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="The root cause is confirmed.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.hypotheses == []
    assert len(result.llm_calls) == 3
    repairs = [
        event for event in result.events if event.event_type == "agent.repair"
    ]
    assert len(repairs) == 2
