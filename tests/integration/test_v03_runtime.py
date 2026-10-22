"""Integration tests for the v0.3 grounded differential runtime."""

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

ROOT = Path(__file__).resolve().parents[2]
LOG_FIXTURE = ROOT / "fixtures" / "logs" / "basic" / "incident.log"
REPO_FIXTURE = ROOT / "fixtures" / "repos" / "minimal-order-service"
MOCK_SCRIPT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "mock_responses.json"
)
THREAD_REF = "log://incident.log#thread=http-nio-8080-exec-7&L1-L3"
SOURCE_REF = "repo://src/main/java/com/example/order/OrderService.java#L17-L27"
SQL_REF = "repo://src/main/java/com/example/order/OrderMapper.java#L16"


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


def _fixture() -> list[LLMResponse]:
    data = json.loads(MOCK_SCRIPT.read_text(encoding="utf-8"))
    return [LLMResponse.model_validate(item) for item in data["responses"]]


def _calls(response: LLMResponse) -> list[ToolCall]:
    return [call.model_copy(deep=True) for call in response.tool_calls]


def _response(
    calls: list[ToolCall],
    *,
    content: str = "",
    finish_reason: str = "tool_calls",
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=calls,
        finish_reason=finish_reason,
    )


def _proposals() -> list[ToolCall]:
    fixture = _fixture()
    return _calls(fixture[0])[:2]


def _bound_context_call(
    call_id: str,
    event_id: str,
    *,
    hypothesis_id: str = "hyp_001",
    requirement_id: str = "hyp_001_req_01",
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="logs_get_thread_context",
        arguments={
            "event_id": event_id,
            "before": 3,
            "after": 3,
            "hypothesis_id": hypothesis_id,
            "requirement_id": requirement_id,
        },
    )


def _bound_source_call(call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="code_find_symbol",
        arguments={
            "query": "OrderService.updateStatus",
            "hypothesis_id": "hyp_001",
            "requirement_id": "hyp_001_req_02",
        },
    )


def _bound_sql_call(call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="code_find_sql",
        arguments={
            "query": "orders",
            "hypothesis_id": "hyp_002",
            "requirement_id": "hyp_002_req_01",
        },
    )


def _assess_call(call_id: str, assessments: list[dict[str, object]]) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="diagnosis_assess_evidence",
        arguments={"assessments": assessments},
    )


def _thread_assessment(source_ref: str = THREAD_REF) -> dict[str, object]:
    return {
        "hypothesis_id": "hyp_001",
        "requirement_id": "hyp_001_req_01",
        "source_ref": source_ref,
        "verdict": "supports",
        "rationale": "The same-thread sequence shows the failed update.",
    }


def _source_assessment() -> dict[str, object]:
    return {
        "hypothesis_id": "hyp_001",
        "requirement_id": "hyp_001_req_02",
        "source_ref": SOURCE_REF,
        "verdict": "supports",
        "rationale": "The source checks the affected-row count.",
    }


def _sql_assessment(verdict: str = "refutes") -> dict[str, object]:
    return {
        "hypothesis_id": "hyp_002",
        "requirement_id": "hyp_002_req_01",
        "source_ref": SQL_REF,
        "verdict": verdict,
        "rationale": "The UPDATE has an order-id predicate.",
    }


def _empty_round() -> LLMResponse:
    return LLMResponse(content="", tool_calls=[], finish_reason="stop")


def _index() -> TreeSitterJavaIndex:
    index = TreeSitterJavaIndex()
    index.index(REPO_FIXTURE)
    return index


def _run(
    provider: ScriptedProvider,
    *,
    log_path: Path = LOG_FIXTURE,
    budget: Budget | None = None,
):
    parsed = LogParser().parse(log_path)
    runtime = DiagnosisRuntime(
        repo_root=REPO_FIXTURE,
        provider_name="mock",
        model="v03",
        repair_attempts=2,
    )
    return runtime.run(parsed, _index(), "order-service", provider, budget)


def _prompt(provider: ScriptedProvider, index: int) -> str:
    messages = provider.prompts[index]
    return next(message.content for message in messages if message.role == "user")


def test_single_hypothesis_is_not_confirmed() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals()[:1],
                    _bound_context_call("ctx_1", "evt_0003"),
                    _bound_source_call("source_1"),
                    _assess_call(
                        "assess_1",
                        [_thread_assessment(), _source_assessment()],
                    ),
                ]
            ),
            _empty_round(),
            _empty_round(),
            _empty_round(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.evaluation.run_confirmed is False
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].status == "supported"
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "insufficient_hypotheses"
        for event in result.events
    )


def test_open_alternative_prevents_confirmation() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_context_call("ctx_1", "evt_0003"),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [
                            _thread_assessment(),
                            _source_assessment(),
                            _sql_assessment("supports"),
                        ],
                    ),
                ]
            ),
            _empty_round(),
            _empty_round(),
            _empty_round(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.evaluation.run_confirmed is False
    statuses = {item.hypothesis_id: item.status for item in result.hypotheses}
    assert statuses == {
        "hyp_001": "supported",
        "hyp_002": "supported",
    }
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "no_tool_calls"
        for event in result.events
    )


def test_missing_thread_context_is_repaired_before_confirmation() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [_source_assessment(), _sql_assessment()],
                    ),
                ]
            ),
            _empty_round(),
            _response(
                [
                    _bound_context_call("ctx_1", "evt_0003"),
                    _assess_call("assess_2", [_thread_assessment()]),
                ]
            ),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    repair = next(
        event for event in result.events if event.event_type == "agent.repair"
    )
    assert repair.data["reason"] == "missing_thread_context"
    context = next(
        item
        for item in result.evidence
        if item.kind == "log_thread_context"
    )
    assert context.bound_hypothesis_id == "hyp_001"
    assert context.tool_call_id == "ctx_1"
    assert result.hypotheses[0].status == "confirmed"


def test_wrong_thread_context_is_rejected_then_repaired(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "threads.log"
    log_path.write_text(
        "2026-10-18 10:21:03.412 INFO  [http-a] c.e.order.OrderController - "
        "paid callback orderId=10086\n"
        "2026-10-18 10:21:03.413 INFO  [http-b] c.e.order.OrderController - "
        "other request\n"
        "2026-10-18 10:21:03.416 ERROR [http-a] c.e.order.OrderService - "
        "failed to update order status\n"
        "java.lang.IllegalStateException: update failed for orderId=10086\n"
        "    at com.example.order.OrderService.updateStatus(OrderService.java:24)\n"
        "    at com.example.order.OrderController.handlePaid(OrderController.java:41)\n",
        encoding="utf-8",
    )
    wrong_ref = "log://threads.log#thread=http-b&L2-L2"
    right_ref = "log://threads.log#thread=http-a&L1-L3"
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_context_call("ctx_wrong", "evt_0002"),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [
                            _thread_assessment(wrong_ref),
                            _source_assessment(),
                            _sql_assessment(),
                        ],
                    ),
                ]
            ),
            _empty_round(),
            _response(
                [
                    _bound_context_call("ctx_right", "evt_0003"),
                    _assess_call(
                        "assess_2",
                        [_thread_assessment(right_ref)],
                    ),
                ]
            ),
        ]
    )

    result = _run(provider, log_path=log_path)

    assert result.state is RuntimeState.COMPLETED
    wrong = next(
        item
        for item in result.evidence
        if item.source_ref == wrong_ref
    )
    right = next(
        item
        for item in result.evidence
        if item.source_ref == right_ref
    )
    assert wrong.bound_requirement_id == "hyp_001_req_01"
    assert right.bound_requirement_id == "hyp_001_req_01"
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "missing_thread_context"
        for event in result.events
    )
    assert result.hypotheses[0].status == "confirmed"


def test_primary_without_thread_does_not_require_context(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "no-thread.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR c.e.order.OrderService - "
        "failed to update order status\n"
        "java.lang.IllegalStateException: update failed for orderId=10086\n"
        "    at com.example.order.OrderService.updateStatus(OrderService.java:24)\n"
        "    at com.example.order.OrderController.handlePaid(OrderController.java:41)\n",
        encoding="utf-8",
    )
    source_ref = SOURCE_REF
    proposal = _proposals()[0]
    proposal.arguments = {
        **proposal.arguments,
        "basis_evidence_ids": ["ev_0001", "ev_0002"],
        "requirements": [
            {
                "description": "The primary log event reports the failed update.",
                "evidence_kinds": ["log_event"],
                "discriminating": True,
                "suggested_tools": ["logs.get_event_context"],
            },
            {
                "description": "The service source checks the affected-row count.",
                "evidence_kinds": ["source_code"],
                "discriminating": False,
                "suggested_tools": ["code.find_symbol"],
            },
        ],
    }
    provider = ScriptedProvider(
        [
            _response(
                [
                    proposal,
                    _proposals()[1],
                    ToolCall(
                        id="log_1",
                        name="logs_get_event_context",
                        arguments={
                            "event_id": "evt_0001",
                            "before": 1,
                            "after": 1,
                            "hypothesis_id": "hyp_001",
                            "requirement_id": "hyp_001_req_01",
                        },
                    ),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_01",
                                "evidence_id": "ev_0001",
                                "verdict": "supports",
                                "rationale": "The primary event reports the failure.",
                            },
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_02",
                                "source_ref": source_ref,
                                "verdict": "supports",
                                "rationale": "The source checks the row count.",
                            },
                            _sql_assessment(),
                        ],
                    ),
                ]
            ),
        ]
    )

    result = _run(provider, log_path=log_path)

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert all(
        item.kind != "log_thread_context" for item in result.evidence
    )
    assert result.hypotheses[0].status == "confirmed"


def test_ungrounded_hypothesis_is_repaired() -> None:
    proposal = _proposals()[0]
    proposal.arguments = {
        **proposal.arguments,
        "basis_evidence_ids": ["ev_9999"],
    }
    provider = ScriptedProvider(
        [
            _response([proposal]),
            *_fixture(),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert len(result.rejected_hypotheses) == 1
    assert result.rejected_hypotheses[0].error_code == "HYPOTHESIS_NOT_GROUNDED"
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "ungrounded_hypothesis"
        for event in result.events
    )
    assert "TOOL_NOT_FOUND" not in _prompt(provider, 1)
    assert "HYPOTHESIS_NOT_GROUNDED" in _prompt(provider, 1)


def test_invalid_assessment_is_repaired() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_context_call("ctx_1", "evt_0003"),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [_thread_assessment(), _sql_assessment()],
                    ),
                ]
            ),
            _response(
                [
                    _assess_call(
                        "assess_bad",
                        [
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_02",
                                "evidence_id": "ev_missing",
                                "verdict": "supports",
                                "rationale": "Invalid evidence ID.",
                            }
                        ],
                    )
                ]
            ),
            _response(
                [
                    _assess_call(
                        "assess_good",
                        [_source_assessment()],
                    )
                ]
            ),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert result.hypotheses[0].status == "confirmed"
    assert any(
        record.tool_call_id == "assess_bad"
        and record.error_code == "INVALID_ASSESSMENT"
        for record in result.tool_calls
    )
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "invalid_assessment"
        for event in result.events
    )
    assert any(
        event.event_type == "assessment.rejected" for event in result.events
    )


def test_no_new_evidence_repair() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_context_call("ctx_1", "evt_0003"),
                    _bound_source_call("source_1"),
                    _bound_sql_call("sql_1"),
                    _assess_call(
                        "assess_1",
                        [_thread_assessment(), _sql_assessment()],
                    ),
                ]
            ),
            _response(
                [
                    ToolCall(
                        id="reuse_primary",
                        name="logs.get_event_context",
                        arguments={"event_id": "evt_0003", "before": 0, "after": 0},
                    )
                ]
            ),
            _response(
                [
                    _assess_call(
                        "assess_good",
                        [_source_assessment()],
                    )
                ]
            ),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.COMPLETED
    assert any(
        event.event_type == "agent.repair"
        and event.data["reason"] == "no_new_evidence"
        for event in result.events
    )
    assert result.hypotheses[0].status == "confirmed"


def test_prompt_contains_protocol_and_no_expected_data() -> None:
    provider = ScriptedProvider([_empty_round()])

    _run(provider)

    prompt = _prompt(provider, 0)
    assert "Thread context (same thread, ordered):" in prompt
    assert "Evidence ledger:" in prompt
    assert "Hypotheses:" in prompt
    assert "Available tools:" in prompt
    assert "Remaining budget:" in prompt
    assert "ev_0001" in prompt
    assert "ev_0002" in prompt
    assert "expected" not in prompt.lower()
    assert str(LOG_FIXTURE) not in prompt
    assert str(REPO_FIXTURE) not in prompt


def test_text_only_round_repairs_and_never_confirms() -> None:
    provider = ScriptedProvider(
        [
            _response([], content="The root cause is confirmed."),
        ]
    )

    result = _run(provider)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.evaluation.run_confirmed is False
    assert result.hypotheses == []
    assert len(result.llm_calls) == 3


def test_tool_budget_exhaustion() -> None:
    provider = ScriptedProvider(
        [
            _response(
                [
                    *_proposals(),
                    _bound_context_call("ctx_1", "evt_0003"),
                    _bound_source_call("source_1"),
                ]
            ),
        ]
    )

    result = _run(
        provider,
        budget=Budget(max_tool_calls=2, max_iterations=5),
    )

    assert result.state is RuntimeState.STOPPED_BUDGET
    assert result.stop_reason is StopReason.BUDGET_EXHAUSTED
    assert result.budget_usage["tool_calls"] == 2
    assert len(result.tool_calls) == 2
    assert result.hypotheses[0].status != "confirmed"
