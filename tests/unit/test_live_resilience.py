"""Fake live-like tests for bounded plan repair and observation feedback."""

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
    Usage,
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


def _source_response(call_id: str = "source_call") -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name="code.find_symbol",
                arguments={"query": "OrderService.updateStatus"},
            )
        ],
        finish_reason="tool_calls",
        usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


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
            _source_response(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert result.hypotheses[0].status == "confirmed"
    assert len(result.llm_calls) == 2
    assert any(
        event.event_type == "agent.repair" for event in result.events
    )
    second_prompt = _user_prompt(provider, 1)
    assert "Previous observation" in second_prompt
    assert "I will inspect the source." in second_prompt
    assert "no_tool_calls" in second_prompt


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
            )
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
            _source_response(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.tool_calls[0].error_code == "TOOL_NOT_FOUND"
    assert len(result.llm_calls) == 2
    assert "TOOL_NOT_FOUND" in _user_prompt(provider, 1)


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
            _source_response(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.tool_calls[0].error_code == "INVALID_ARGUMENTS"
    assert len(result.llm_calls) == 2
    assert "INVALID_ARGUMENTS" in _user_prompt(provider, 1)


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
            _source_response("source_after_length"),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert [record.tool_call_id for record in result.tool_calls] == [
        "source_after_length"
    ]
    assert result.llm_calls[0].finish_reason == "length"
    assert "length" in _user_prompt(provider, 1)


def test_repair_is_bounded_by_iteration_budget() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(content="text only", tool_calls=[], finish_reason="stop"),
            LLMResponse(content="still text", tool_calls=[], finish_reason="stop"),
        ]
    )

    result = _run(provider, Budget(max_iterations=2, max_tool_calls=8))

    assert result.state is RuntimeState.STOPPED_BUDGET
    assert result.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert len(result.llm_calls) == 2
    assert result.hypotheses[0].status != "confirmed"


def test_repair_exhaustion_stops_without_confirmation() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="The root cause is confirmed.",
                tool_calls=[],
                finish_reason="stop",
            ),
            LLMResponse(
                content="Still no tools.",
                tool_calls=[],
                finish_reason="stop",
            ),
            LLMResponse(
                content="No more ideas.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.hypotheses[0].status != "confirmed"
    assert len(result.llm_calls) == 3
    repairs = [
        event for event in result.events if event.event_type == "agent.repair"
    ]
    assert len(repairs) == 2
