"""Grounded differential diagnosis runtime for v0.3."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from tracemind.artifacts import ArtifactBundle
from tracemind.core.models import LogEvent, ParsedLog
from tracemind.diagnosis.budget import Budget, BudgetUsage
from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    Hypothesis,
    HypothesisStatus,
    LLMCallRecord,
    RejectedHypothesis,
    RunResult,
    ToolCallRecord,
    summarize_llm_usage,
)
from tracemind.diagnosis.evidence_mapping import (
    EvidenceDraft,
    map_tool_result,
)
from tracemind.diagnosis.ledger import EvidenceLedger, InvalidBindingError
from tracemind.diagnosis.prompts import (
    REMEDIATION_SYSTEM_PROMPT,
    build_remediation_prompt,
    build_system_prompt,
    build_user_prompt,
)
from tracemind.diagnosis.state import (
    RuntimeEvent,
    RuntimeState,
    StopReason,
    validate_transition,
)
from tracemind.diagnosis.workspace import DiagnosisWorkspace
from tracemind.indexing.java_index import JavaIndex, SourceMatch
from tracemind.llm.messages import Message, ToolCall, ToolDefinition
from tracemind.llm.provider import LLMProvider, LLMProviderError
from tracemind.log_analysis.thread_context import (
    ThreadContext,
    ThreadContextError,
    collect_thread_context,
)
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolRequest, ToolResult
from tracemind.tools.executor import ToolExecutor
from tracemind.tools.registry import ToolRegistry
from tracemind.verification import ReadOnlyVerificationBackend

LIMITATIONS = (
    "v0.3 reads one user-provided local log and one local repository.",
    "Source/deployed version consistency is not verified.",
    "Only local read-only tools are available; no remote runtime evidence is collected.",
    "Call edges are AST heuristics, not runtime traces.",
)

_LOGGING_CONTROL_TOOLS = frozenset(
    {
        "diagnosis.propose_hypothesis",
        "diagnosis.assess_evidence",
        "diagnosis.propose_remediation",
    }
)
_REPORTING_TOOL = "diagnosis.propose_remediation"
_DIAGNOSIS_CONTROL_TOOLS = frozenset(
    {"diagnosis.propose_hypothesis", "diagnosis.assess_evidence"}
)


class _EvidenceRecordError(RuntimeError):
    """Raised when a tool-derived evidence item cannot be recorded."""


class DiagnosisRuntime:
    """Run a bounded, evidence-grounded differential diagnosis loop."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        repo_root: Path | None = None,
        provider_name: str = "unknown",
        model: str = "unknown",
        repair_attempts: int = 2,
        verification_backend: ReadOnlyVerificationBackend | None = None,
        artifacts: ArtifactBundle | None = None,
    ) -> None:
        self._tool_registry = tool_registry or build_default_registry(
            verification_backend=verification_backend,
            artifacts=artifacts,
        )
        self._verification_backend = verification_backend
        self._artifacts = artifacts
        self._repo_root = repo_root
        self._provider_name = provider_name
        self._model = model
        self._repair_attempts = repair_attempts

    def run(
        self,
        parsed_log: ParsedLog,
        java_index: JavaIndex,
        service: str,
        provider: LLMProvider,
        budget: Budget | None = None,
    ) -> RunResult:
        budget = budget or Budget()
        usage = BudgetUsage()
        incident_id = _new_id("inc_")
        run_id = _new_id("run_")
        ledger = EvidenceLedger(max_content_bytes=budget.max_output_bytes)
        workspace = DiagnosisWorkspace(
            ledger,
            max_hypotheses=budget.max_hypotheses,
            max_requirements_per_hypothesis=budget.max_requirements_per_hypothesis,
            max_remediation_actions=budget.max_remediation_actions,
        )
        tool_records: list[ToolCallRecord] = []
        llm_calls: list[LLMCallRecord] = []
        rejected_hypotheses: list[RejectedHypothesis] = []
        extra_limitations: list[str] = []
        events: list[RuntimeEvent] = []
        current_state = RuntimeState.INGESTING
        evidence_counter = 0
        repair_attempts_used = 0
        last_round_observed = False
        last_assistant_text = ""
        last_tool_observations: list[str] = []
        last_new_evidence = 0
        last_new_bindings = 0
        last_repair_reason = ""
        last_evaluation = EvaluationResult()
        verification_environment = (
            self._verification_backend.environment
            if self._verification_backend is not None
            else None
        )

        def emit(
            event_type: str,
            data: dict[str, Any] | None = None,
        ) -> None:
            events.append(
                RuntimeEvent(
                    event_type=event_type,
                    timestamp=_now(),
                    data=data or {},
                )
            )

        def transition(new_state: RuntimeState) -> None:
            nonlocal current_state
            validate_transition(current_state, new_state)
            current_state = new_state
            emit("state.changed", {"state": new_state.value})

        def ensure_state(new_state: RuntimeState) -> None:
            if current_state is not new_state:
                transition(new_state)

        def try_repair(reason: str) -> bool:
            nonlocal repair_attempts_used, last_round_observed, last_repair_reason
            if repair_attempts_used >= self._repair_attempts:
                return False
            repair_attempts_used += 1
            last_round_observed = True
            last_repair_reason = reason
            emit(
                "agent.repair",
                {
                    "reason": reason,
                    "attempt": repair_attempts_used,
                    "remaining": self._repair_attempts - repair_attempts_used,
                },
            )
            return True

        def add_limitation(message: str) -> None:
            if message not in extra_limitations:
                extra_limitations.append(message)

        def sync_usage() -> None:
            usage.hypotheses = len(workspace.hypotheses)
            usage.assessments = len(workspace.assessments)
            usage.remediation_actions = len(workspace.remediation_actions)

        def finish(state: RuntimeState, stop: StopReason) -> RunResult:
            sync_usage()
            if current_state is not state:
                transition(state)
            emit(
                "agent.stop_triggered",
                {"state": state.value, "reason": stop.value},
            )
            return RunResult(
                incident_id=incident_id,
                run_id=run_id,
                service=service,
                state=state,
                stop_reason=stop,
                hypotheses=workspace.hypotheses,
                evidence=ledger.all(),
                assessments=workspace.assessments,
                rejected_hypotheses=rejected_hypotheses,
                evaluation=last_evaluation,
                remediation_actions=workspace.remediation_actions,
                rejected_remediations=workspace.rejected_remediations,
                verification_environment=verification_environment,
                artifacts=(
                    list(self._artifacts.records)
                    if self._artifacts is not None
                    else []
                ),
                tool_calls=tool_records,
                llm_calls=llm_calls,
                llm_usage=summarize_llm_usage(llm_calls),
                budget_usage=usage.as_dict(),
                limitations=[*LIMITATIONS, *extra_limitations],
                events=events,
            )

        def add_initial(
            kind: EvidenceKind,
            claim: str,
            source_ref: str,
            strength: Literal["strong", "medium", "weak"],
            provenance: EvidenceProvenance,
            content: dict[str, Any] | None = None,
        ) -> Evidence:
            nonlocal evidence_counter
            evidence_counter += 1
            item = Evidence(
                evidence_id=f"ev_{evidence_counter:04d}",
                kind=kind,
                claim=claim,
                source_ref=source_ref,
                strength=strength,
                provenance=provenance,
                observed_at=_now(),
                content=content or {},
            )
            stored = ledger.add(item)
            emit(
                "evidence.created",
                {
                    "evidence_id": stored.evidence_id,
                    "kind": stored.kind.value,
                    "source_ref": stored.source_ref,
                    "provenance": stored.provenance.value,
                    "bound_hypothesis_id": stored.bound_hypothesis_id,
                    "bound_requirement_id": stored.bound_requirement_id,
                },
            )
            return stored

        def add_tool_draft(
            draft: EvidenceDraft,
            tool_call_id: str,
            bound_hypothesis_id: str | None,
            bound_requirement_id: str | None,
        ) -> tuple[Evidence, bool, bool]:
            nonlocal evidence_counter
            existing = next(
                (
                    item
                    for item in ledger.all()
                    if item.kind is draft.kind
                    and item.source_ref == draft.source_ref
                ),
                None,
            )
            if existing is not None:
                before_bindings = {
                    (binding.hypothesis_id, binding.requirement_id)
                    for binding in existing.bindings
                }
                if bound_hypothesis_id is not None:
                    try:
                        workspace.bind_tool_evidence(
                            existing,
                            tool_call_id,
                            bound_hypothesis_id,
                            bound_requirement_id,
                        )
                    except InvalidBindingError as exc:
                        raise _EvidenceRecordError(str(exc)) from exc
                if existing.tool_call_id is None:
                    existing.tool_call_id = tool_call_id
                after_bindings = {
                    (binding.hypothesis_id, binding.requirement_id)
                    for binding in existing.bindings
                }
                upgraded = before_bindings != after_bindings
                if upgraded:
                    emit(
                        "evidence.bound",
                        {
                            "evidence_id": existing.evidence_id,
                            "bound_hypothesis_id": bound_hypothesis_id,
                            "bound_requirement_id": bound_requirement_id,
                            "bindings": [
                                {
                                    "hypothesis_id": binding.hypothesis_id,
                                    "requirement_id": binding.requirement_id,
                                }
                                for binding in existing.bindings
                            ],
                        },
                    )
                return existing, False, upgraded

            if len(ledger) >= budget.max_evidence_items:
                raise _EvidenceRecordError(
                    f"evidence limit reached: {budget.max_evidence_items}"
                )
            evidence_counter += 1
            item = Evidence(
                evidence_id=f"ev_{evidence_counter:04d}",
                kind=draft.kind,
                claim=draft.claim,
                source_ref=draft.source_ref,
                strength=draft.strength,
                provenance=draft.provenance,
                tool_call_id=tool_call_id,
                observed_at=_now(),
                bound_hypothesis_id=bound_hypothesis_id,
                bound_requirement_id=bound_requirement_id,
                content=draft.content,
            )
            stored = ledger.add(item)
            emit(
                "evidence.created",
                {
                    "evidence_id": stored.evidence_id,
                    "kind": stored.kind.value,
                    "source_ref": stored.source_ref,
                    "provenance": stored.provenance.value,
                    "bound_hypothesis_id": stored.bound_hypothesis_id,
                    "bound_requirement_id": stored.bound_requirement_id,
                    "tool_call_id": tool_call_id,
                },
            )
            return stored, True, False

        if self._artifacts is not None:
            add_limitation(
                "JVM snapshots are user-provided point-in-time text files; "
                "no live attach or collection was performed."
            )
            add_limitation(
                "A same-thread log context is not required when JVM artifacts "
                "are provided."
            )

        emit(
            "diagnosis.started",
            {
                "incident_id": incident_id,
                "run_id": run_id,
                "service": service,
                "provider": type(provider).__name__,
            },
        )
        emit(
            "logs.ingested",
            {
                "events": len(parsed_log.events),
                "primary_event_id": parsed_log.primary_event_id,
            },
        )

        primary = _primary_event(parsed_log)
        if primary is not None:
            add_initial(
                EvidenceKind.LOG_EVENT,
                f"Primary log event {primary.event_id}: {primary.message}",
                f"log://{primary.event_id}",
                "strong",
                EvidenceProvenance.LOG_PARSER,
                {
                    "event_id": primary.event_id,
                    "thread": primary.thread,
                    "logger": primary.logger,
                    "level": primary.level,
                },
            )

        transition(RuntimeState.SEEDING)
        thread_context: ThreadContext | None = None
        if primary is not None:
            try:
                thread_context = collect_thread_context(parsed_log, primary.event_id)
            except ThreadContextError:
                thread_context = None
            if thread_context is not None:
                messages = "; ".join(
                    item.message for item in thread_context.items[:3]
                )
                add_initial(
                    EvidenceKind.LOG_THREAD_CONTEXT,
                    (
                        f"Thread {thread_context.thread} around "
                        f"{thread_context.anchor_event_id}: {messages}"
                    ),
                    thread_context.source_ref,
                    "strong",
                    EvidenceProvenance.LOG_PARSER,
                    {
                        "thread": thread_context.thread,
                        "anchor_event_id": thread_context.anchor_event_id,
                        "line_start": thread_context.line_start,
                        "line_end": thread_context.line_end,
                        "items": [
                            item.model_dump() for item in thread_context.items
                        ],
                        "count": thread_context.count,
                    },
                )

        source_matches = (
            _find_seed_matches(primary, java_index)
            if primary is not None
            else []
        )
        if primary is not None and source_matches:
            first_match = source_matches[0]
            matched_line = first_match.matched_line or first_match.start_line
            method_name = first_match.symbol.method_name or ""
            add_initial(
                EvidenceKind.STACK_FRAME,
                (
                    f"{first_match.symbol.fqn}.{method_name} at "
                    f"{first_match.file_path}:{matched_line}"
                ),
                f"log://{primary.event_id}",
                "strong",
                EvidenceProvenance.LOG_PARSER,
                {
                    "fqn": first_match.symbol.fqn,
                    "method_name": method_name,
                    "file_path": first_match.file_path,
                    "line": matched_line,
                },
            )
            add_initial(
                EvidenceKind.SOURCE_CODE,
                (
                    f"Source {first_match.file_path}:"
                    f"{first_match.start_line}-{first_match.end_line}"
                ),
                _repo_ref(
                    first_match.file_path,
                    first_match.start_line,
                    first_match.end_line,
                ),
                "strong",
                EvidenceProvenance.AST_INDEX,
                {
                    "file_path": first_match.file_path,
                    "start_line": first_match.start_line,
                    "end_line": first_match.end_line,
                    "symbol_id": first_match.symbol.symbol_id,
                },
            )

        transition(RuntimeState.PLANNING)

        repo_root = self._repo_root
        if repo_root is None:
            candidate = getattr(java_index, "repo_root", None)
            if isinstance(candidate, Path):
                repo_root = candidate
        context = ToolContext(
            parsed_log=parsed_log,
            java_index=java_index,
            repo_root=repo_root,
            log_root=Path(parsed_log.source_file).parent,
            workspace=workspace,
            verification_backend=self._verification_backend,
            artifacts=self._artifacts,
        )
        executor = ToolExecutor(
            self._tool_registry,
            context,
            default_max_output_bytes=budget.max_output_bytes,
        )
        tool_specs = self._tool_registry.list_tools()
        tool_name_map: dict[str, str] = {}
        for spec in tool_specs:
            tool_name_map[_llm_tool_name(spec.name)] = spec.name
            tool_name_map[spec.name] = spec.name

        def definitions_for(names: set[str] | frozenset[str]) -> list[ToolDefinition]:
            return [
                ToolDefinition(
                    name=_llm_tool_name(spec.name),
                    description=spec.description,
                    parameters=spec.input_model.model_json_schema(),
                )
                for spec in tool_specs
                if spec.name in names
            ]

        diagnosis_tool_names = frozenset(
            spec.name for spec in tool_specs
        ) - frozenset({_REPORTING_TOOL})
        remediation_tool_definitions = definitions_for({_REPORTING_TOOL})

        def unassessed_bound_evidence() -> list[Evidence]:
            assessed = {
                (
                    assessment.hypothesis_id,
                    assessment.requirement_id,
                    assessment.evidence_id,
                )
                for assessment in workspace.assessments
            }
            return [
                item
                for item in ledger.all()
                if any(
                    (
                        binding.hypothesis_id,
                        binding.requirement_id,
                        item.evidence_id,
                    )
                    not in assessed
                    for binding in item.bindings
                )
            ]

        def active_tool_definitions() -> list[ToolDefinition]:
            # Enforce the protocol order generically: candidates first, then
            # assess bound evidence before opening more investigation.
            if len(workspace.hypotheses) < 2:
                active_names = frozenset({"diagnosis.propose_hypothesis"})
            elif unassessed_bound_evidence():
                active_names = frozenset({"diagnosis.assess_evidence"})
            else:
                active_names = diagnosis_tool_names
            return definitions_for(active_names)

        def requires_same_thread_context() -> bool:
            return (
                primary is not None
                and primary.thread is not None
                and self._artifacts is None
            )

        def required_thread() -> str | None:
            if not requires_same_thread_context():
                return None
            assert primary is not None
            return primary.thread

        def evaluate_current() -> EvaluationResult:
            nonlocal last_evaluation
            last_evaluation = workspace.evaluate(
                require_log_thread_context=requires_same_thread_context(),
                required_log_thread=required_thread(),
            )
            sync_usage()
            for hypothesis in workspace.hypotheses:
                item = last_evaluation.for_hypothesis(hypothesis.hypothesis_id)
                emit(
                    "hypothesis.updated",
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "status": hypothesis.status.value,
                        "missing_requirement_ids": list(
                            hypothesis.missing_requirement_ids
                        ),
                        "ranking_score": hypothesis.ranking_score,
                        "reasons": item.reasons if item is not None else [],
                    },
                )
            return last_evaluation

        def thread_context_assessed() -> bool:
            if not requires_same_thread_context():
                return True
            target_thread = required_thread()
            if target_thread is None:
                return True
            assessed_ids = {
                assessment.evidence_id
                for assessment in workspace.assessments
            }
            for item in ledger.all():
                if item.kind is not EvidenceKind.LOG_THREAD_CONTEXT:
                    continue
                if not _evidence_matches_thread(item, target_thread):
                    continue
                if item.evidence_id in assessed_ids:
                    return True
            return False

        def stop_repair_reason(
            evaluation: EvaluationResult,
            error_reason: str | None,
            *,
            no_tool_calls: bool,
        ) -> str:
            if not workspace.hypotheses:
                return error_reason or "no_hypotheses"
            if requires_same_thread_context() and not thread_context_assessed():
                return "missing_thread_context"
            if len(workspace.hypotheses) < 2:
                return "insufficient_hypotheses"
            if error_reason is not None:
                return error_reason
            return "no_tool_calls" if no_tool_calls else "no_new_evidence"

        def previous_observation() -> str | None:
            if not last_round_observed:
                return None
            lines = [
                f"- assistant text: {last_assistant_text[:500] or '(empty)'}",
                "- tool calls:",
                *(last_tool_observations[:8] or ["  - (none)"]),
                f"- new evidence: {last_new_evidence}",
                f"- new bindings: {last_new_bindings}",
                f"- repair reason: {last_repair_reason or 'none'}",
                (
                    "- repair remaining: "
                    f"{self._repair_attempts - repair_attempts_used}"
                ),
            ]
            return "\n".join(lines)

        def build_messages() -> list[Message]:
            user_content = build_user_prompt(
                service=service,
                primary=primary,
                thread_context=thread_context,
                evidence=ledger.all(),
                hypotheses=workspace.hypotheses,
                assessments=workspace.assessments,
                evaluation=last_evaluation,
                tools=active_tool_definitions(),
                verification_environment=verification_environment,
                budget=budget,
                usage=usage,
                previous_observation=previous_observation(),
                artifacts=(
                    list(self._artifacts.records)
                    if self._artifacts is not None
                    else None
                ),
            )
            return [
                Message(
                    role="system",
                    content=build_system_prompt(
                        has_artifacts=self._artifacts is not None
                    ),
                ),
                Message(role="user", content=user_content),
            ]

        def complete_if_confirmed(evaluation: EvaluationResult) -> RunResult | None:
            if not evaluation.run_confirmed:
                return None
            if requires_same_thread_context() and not thread_context_assessed():
                return None
            return finalize(RuntimeState.COMPLETED, StopReason.EVIDENCE_SUFFICIENT)

        def tool_observation(
            call: ToolCall,
            result: ToolResult,
            created_count: int,
        ) -> str:
            args = json.dumps(
                call.arguments,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )[:180]
            status = "ok" if result.ok else f"error:{result.error_code}"
            if not result.ok and result.error_message:
                detail = " ".join(result.error_message.split())[:240]
                status = f"{status} ({detail})"
            excerpt = _tool_excerpt(result.data)
            return (
                f"  - {call.name}({args}) -> {status}; "
                f"new_evidence={created_count}; excerpt={excerpt}"
            )

        def remediable_hypotheses() -> list[Hypothesis]:
            return [
                hypothesis
                for hypothesis in workspace.hypotheses
                if hypothesis.status
                in {HypothesisStatus.SUPPORTED, HypothesisStatus.CONFIRMED}
            ]

        def run_remediation() -> None:
            if not remediable_hypotheses():
                return
            if (
                usage.llm_calls >= budget.max_llm_calls
                or usage.iterations >= budget.max_iterations
            ):
                add_limitation(
                    "Remediation was skipped because the LLM/iteration budget "
                    "was exhausted."
                )
                return

            ensure_state(RuntimeState.REPORTING)
            usage.iterations += 1
            usage.llm_calls += 1
            call_started_at = _now()
            call_started_clock = perf_counter()
            messages = [
                Message(role="system", content=REMEDIATION_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=build_remediation_prompt(
                        service=service,
                        primary=primary,
                        evidence=ledger.all(),
                        hypotheses=workspace.hypotheses,
                        assessments=workspace.assessments,
                        evaluation=last_evaluation,
                        tools=remediation_tool_definitions,
                        verification_environment=verification_environment,
                        budget=budget,
                    ),
                ),
            ]
            try:
                response = provider.complete(
                    messages,
                    remediation_tool_definitions,
                )
            except LLMProviderError as exc:
                latency_ms = int((perf_counter() - call_started_clock) * 1000)
                call_record = LLMCallRecord(
                    llm_call_id=f"llm_{len(llm_calls) + 1:04d}",
                    round=usage.iterations,
                    provider=self._provider_name,
                    model=self._model,
                    request_id=exc.request_id,
                    started_at=call_started_at,
                    latency_ms=latency_ms,
                    attempts=exc.attempts,
                    ok=False,
                    error_code=exc.code,
                )
                llm_calls.append(call_record)
                emit(
                    "llm.error",
                    {
                        "llm_call_id": call_record.llm_call_id,
                        "phase": "remediation",
                        "code": exc.code,
                        "message": exc.message,
                        "attempts": exc.attempts,
                        "status_code": exc.status_code,
                        "request_id": exc.request_id,
                        "latency_ms": latency_ms,
                    },
                )
                add_limitation(
                    f"Remediation LLM call failed: {exc.code}."
                )
                return

            latency_ms = int((perf_counter() - call_started_clock) * 1000)
            llm_usage = response.usage
            input_tokens = llm_usage.input_tokens if llm_usage else None
            output_tokens = llm_usage.output_tokens if llm_usage else None
            total_tokens = _usage_total(llm_usage)
            call_record = LLMCallRecord(
                llm_call_id=f"llm_{len(llm_calls) + 1:04d}",
                round=usage.iterations,
                provider=self._provider_name,
                model=self._model,
                request_id=response.raw_provider_id,
                started_at=call_started_at,
                latency_ms=latency_ms,
                attempts=response.attempts,
                ok=True,
                finish_reason=response.finish_reason,
                tool_calls=len(response.tool_calls),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
            llm_calls.append(call_record)
            emit(
                "llm.called",
                {
                    "llm_call_id": call_record.llm_call_id,
                    "round": usage.iterations,
                    "phase": "remediation",
                    "provider": self._provider_name,
                    "model": self._model,
                    "request_id": response.raw_provider_id,
                    "attempts": response.attempts,
                    "tool_calls": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                },
            )

            if response.finish_reason == "length":
                add_limitation(
                    "Remediation output was truncated; no remediation plan "
                    "was recorded."
                )
                return
            if not response.tool_calls:
                add_limitation(
                    "No remediation tool call was produced; the report has no "
                    "remediation plan."
                )
                return

            for call in response.tool_calls:
                if usage.tool_calls >= budget.max_tool_calls:
                    add_limitation(
                        "Remediation stopped because the tool-call budget was "
                        "exhausted."
                    )
                    break
                internal_tool_name = tool_name_map.get(call.name, call.name)
                actions_before = len(workspace.remediation_actions)
                rejected_before = len(workspace.rejected_remediations)
                if internal_tool_name != _REPORTING_TOOL:
                    result = ToolResult(
                        ok=False,
                        tool_name=internal_tool_name,
                        error_code="INVALID_REMEDIATION",
                        error_message=(
                            "only diagnosis.propose_remediation is allowed in "
                            "REPORTING"
                        ),
                        duration_ms=0,
                    )
                else:
                    result = executor.execute(
                        ToolRequest(
                            tool_call_id=call.id,
                            tool_name=internal_tool_name,
                            arguments=call.arguments,
                            run_id=run_id,
                        )
                    )
                usage.tool_calls += 1

                new_rejections = workspace.rejected_remediations[rejected_before:]
                for rejection in new_rejections:
                    rejection.tool_call_id = call.id
                    emit(
                        "remediation.rejected",
                        {
                            "tool_call_id": call.id,
                            "hypothesis_id": rejection.hypothesis_id,
                            "reason": rejection.reason,
                        },
                    )
                new_actions = workspace.remediation_actions[actions_before:]
                for action in new_actions:
                    emit(
                        "remediation.created",
                        {
                            "action_id": action.action_id,
                            "hypothesis_id": action.hypothesis_id,
                            "type": action.type,
                            "target": action.target,
                            "evidence_ids": action.evidence_ids,
                        },
                    )
                if not result.ok:
                    emit(
                        "remediation.rejected",
                        {
                            "tool_call_id": call.id,
                            "error_code": result.error_code,
                            "reason": result.error_message,
                        },
                    )
                    add_limitation(
                        "Remediation tool call was rejected: "
                        f"{result.error_message or result.error_code}."
                    )
                else:
                    data = result.data if isinstance(result.data, dict) else {}
                    if int(data.get("accepted", 0) or 0) == 0:
                        add_limitation(
                            "No valid remediation action was accepted; the "
                            "report has no remediation plan."
                        )

                tool_records.append(
                    ToolCallRecord(
                        tool_call_id=call.id,
                        tool_name=internal_tool_name,
                        arguments=call.arguments,
                        ok=result.ok,
                        error_code=result.error_code,
                        duration_ms=result.duration_ms,
                    )
                )
                emit(
                    "tool.called",
                    {
                        "tool_call_id": call.id,
                        "tool_name": internal_tool_name,
                        "ok": result.ok,
                        "error_code": result.error_code,
                        "evidence_ids": [],
                    },
                )

            sync_usage()
            if not workspace.remediation_actions:
                add_limitation(
                    "No valid remediation action was accepted; the report has "
                    "no remediation plan."
                )
            elif workspace.rejected_remediations:
                add_limitation(
                    f"{len(workspace.rejected_remediations)} remediation "
                    "action(s) were rejected by deterministic validation."
                )

        def finalize(state: RuntimeState, stop: StopReason) -> RunResult:
            if (
                state in {RuntimeState.COMPLETED, RuntimeState.INSUFFICIENT_DATA}
                and remediable_hypotheses()
                and current_state
                in {RuntimeState.PLANNING, RuntimeState.EVALUATING}
            ):
                ensure_state(RuntimeState.REPORTING)
                run_remediation()
            return finish(state, stop)

        while True:
            if (
                usage.iterations >= budget.max_iterations
                or usage.llm_calls >= budget.max_llm_calls
            ):
                return finish(RuntimeState.STOPPED_BUDGET, StopReason.BUDGET_EXHAUSTED)

            ensure_state(RuntimeState.PLANNING)
            usage.iterations += 1
            usage.llm_calls += 1
            call_started_at = _now()
            call_started_clock = perf_counter()
            try:
                response = provider.complete(
                    build_messages(),
                    active_tool_definitions(),
                )
            except LLMProviderError as exc:
                latency_ms = int((perf_counter() - call_started_clock) * 1000)
                call_record = LLMCallRecord(
                    llm_call_id=f"llm_{len(llm_calls) + 1:04d}",
                    round=usage.iterations,
                    provider=self._provider_name,
                    model=self._model,
                    request_id=exc.request_id,
                    started_at=call_started_at,
                    latency_ms=latency_ms,
                    attempts=exc.attempts,
                    ok=False,
                    error_code=exc.code,
                )
                llm_calls.append(call_record)
                emit(
                    "llm.error",
                    {
                        "llm_call_id": call_record.llm_call_id,
                        "code": exc.code,
                        "message": exc.message,
                        "attempts": exc.attempts,
                        "status_code": exc.status_code,
                        "request_id": exc.request_id,
                        "latency_ms": latency_ms,
                    },
                )
                return finish(RuntimeState.FAILED, StopReason.ERROR)

            latency_ms = int((perf_counter() - call_started_clock) * 1000)
            llm_usage = response.usage
            input_tokens = llm_usage.input_tokens if llm_usage else None
            output_tokens = llm_usage.output_tokens if llm_usage else None
            total_tokens = _usage_total(llm_usage)
            call_record = LLMCallRecord(
                llm_call_id=f"llm_{len(llm_calls) + 1:04d}",
                round=usage.iterations,
                provider=self._provider_name,
                model=self._model,
                request_id=response.raw_provider_id,
                started_at=call_started_at,
                latency_ms=latency_ms,
                attempts=response.attempts,
                ok=True,
                finish_reason=response.finish_reason,
                tool_calls=len(response.tool_calls),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
            llm_calls.append(call_record)
            emit(
                "llm.called",
                {
                    "llm_call_id": call_record.llm_call_id,
                    "round": usage.iterations,
                    "provider": self._provider_name,
                    "model": self._model,
                    "request_id": response.raw_provider_id,
                    "attempts": response.attempts,
                    "tool_calls": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                },
            )

            last_assistant_text = response.content[:500]
            last_round_observed = True

            if response.finish_reason == "length":
                last_tool_observations = []
                last_new_evidence = 0
                last_new_bindings = 0
                transition(RuntimeState.EVALUATING)
                evaluation = evaluate_current()
                completed = complete_if_confirmed(evaluation)
                if completed is not None:
                    return completed
                if try_repair("length"):
                    continue
                return finish(RuntimeState.FAILED, StopReason.ERROR)

            if not response.tool_calls:
                last_tool_observations = []
                last_new_evidence = 0
                last_new_bindings = 0
                transition(RuntimeState.EVALUATING)
                evaluation = evaluate_current()
                completed = complete_if_confirmed(evaluation)
                if completed is not None:
                    return completed
                reason = stop_repair_reason(
                    evaluation,
                    None,
                    no_tool_calls=True,
                )
                if try_repair(reason):
                    continue
                return finalize(
                    RuntimeState.INSUFFICIENT_DATA,
                    StopReason.NO_PROGRESS,
                )

            transition(RuntimeState.EXECUTING)
            new_evidence = 0
            new_bindings = 0
            new_hypotheses = 0
            new_assessments = 0
            observations: list[str] = []
            error_reason: str | None = None
            for call in response.tool_calls:
                if usage.tool_calls >= budget.max_tool_calls:
                    return finish(
                        RuntimeState.STOPPED_BUDGET,
                        StopReason.BUDGET_EXHAUSTED,
                    )
                internal_tool_name = tool_name_map.get(call.name, call.name)
                hypotheses_before = len(workspace.hypotheses)
                assessments_before = len(workspace.assessments)
                if internal_tool_name == _REPORTING_TOOL:
                    result = ToolResult(
                        ok=False,
                        tool_name=internal_tool_name,
                        error_code="INVALID_REMEDIATION",
                        error_message=(
                            "diagnosis.propose_remediation is only allowed "
                            "in REPORTING"
                        ),
                        duration_ms=0,
                    )
                else:
                    request = ToolRequest(
                        tool_call_id=call.id,
                        tool_name=internal_tool_name,
                        arguments=call.arguments,
                        run_id=run_id,
                    )
                    result = executor.execute(request)
                usage.tool_calls += 1
                mapped_ids: list[str] = []
                created_count = 0
                revised_assessment_ids: list[str] = []

                if result.ok and internal_tool_name not in _LOGGING_CONTROL_TOOLS:
                    outcome = map_tool_result(result, artifacts=self._artifacts)
                    if outcome.failure_reason is not None:
                        emit(
                            "evidence.mapping_failed",
                            {
                                "tool_call_id": call.id,
                                "reason": outcome.failure_reason,
                            },
                        )
                    for warning in outcome.warnings:
                        emit(
                            "evidence.mapping_warning",
                            {
                                "tool_call_id": call.id,
                                "reason": warning,
                            },
                        )
                    for draft in outcome.drafts:
                        try:
                            item, created, upgraded = add_tool_draft(
                                draft,
                                call.id,
                                result.bound_hypothesis_id,
                                result.bound_requirement_id,
                            )
                        except _EvidenceRecordError as exc:
                            emit(
                                "evidence.mapping_failed",
                                {
                                    "tool_call_id": call.id,
                                    "reason": str(exc),
                                },
                            )
                            continue
                        mapped_ids.append(item.evidence_id)
                        created_count += int(created)
                        new_evidence += int(created)
                        new_bindings += int(upgraded)

                if (
                    result.ok
                    and internal_tool_name == "diagnosis.propose_hypothesis"
                ):
                    data = result.data if isinstance(result.data, dict) else {}
                    emit(
                        "hypothesis.created",
                        {
                            "hypothesis_id": data.get("hypothesis_id"),
                            "requirement_ids": data.get("requirement_ids", []),
                            "status": data.get("status"),
                        },
                    )
                if (
                    result.ok
                    and internal_tool_name == "diagnosis.assess_evidence"
                ):
                    data = result.data if isinstance(result.data, dict) else {}
                    raw_revised = data.get("revised_assessment_ids")
                    if isinstance(raw_revised, list):
                        revised_assessment_ids = [
                            str(assessment_id)
                            for assessment_id in raw_revised
                        ]
                    by_assessment_id = {
                        assessment.assessment_id: assessment
                        for assessment in workspace.assessments
                    }
                    for assessment in workspace.assessments[assessments_before:]:
                        emit(
                            "assessment.created",
                            {
                                "assessment_id": assessment.assessment_id,
                                "hypothesis_id": assessment.hypothesis_id,
                                "requirement_id": assessment.requirement_id,
                                "evidence_id": assessment.evidence_id,
                                "verdict": assessment.verdict.value,
                            },
                        )
                    for assessment_id in revised_assessment_ids:
                        revised_assessment = by_assessment_id.get(assessment_id)
                        if revised_assessment is None:
                            continue
                        emit(
                            "assessment.revised",
                            {
                                "assessment_id": revised_assessment.assessment_id,
                                "hypothesis_id": revised_assessment.hypothesis_id,
                                "requirement_id": revised_assessment.requirement_id,
                                "evidence_id": revised_assessment.evidence_id,
                                "verdict": revised_assessment.verdict.value,
                            },
                        )

                if not result.ok:
                    error_reason = error_reason or _repair_reason_for_error(
                        result.error_code
                    )
                    if internal_tool_name == "diagnosis.propose_hypothesis":
                        statement = str(call.arguments.get("statement", ""))[:300]
                        rejected_hypotheses.append(
                            RejectedHypothesis(
                                statement=statement,
                                reason=result.error_message or "proposal rejected",
                                error_code=result.error_code,
                                tool_call_id=call.id,
                                observed_at=_now(),
                            )
                        )
                        emit(
                            "hypothesis.rejected",
                            {
                                "tool_call_id": call.id,
                                "error_code": result.error_code,
                                "reason": result.error_message,
                            },
                        )
                    elif internal_tool_name == "diagnosis.assess_evidence":
                        emit(
                            "assessment.rejected",
                            {
                                "tool_call_id": call.id,
                                "error_code": result.error_code,
                                "reason": result.error_message,
                            },
                        )
                    elif internal_tool_name == _REPORTING_TOOL:
                        emit(
                            "remediation.rejected",
                            {
                                "tool_call_id": call.id,
                                "error_code": result.error_code,
                                "reason": result.error_message,
                            },
                        )

                new_hypotheses += len(workspace.hypotheses) - hypotheses_before
                new_assessments += (
                    len(workspace.assessments) - assessments_before
                    + len(revised_assessment_ids)
                )
                record = ToolCallRecord(
                    tool_call_id=call.id,
                    tool_name=internal_tool_name,
                    arguments=call.arguments,
                    ok=result.ok,
                    error_code=result.error_code,
                    duration_ms=result.duration_ms,
                    evidence_ids=mapped_ids,
                )
                tool_records.append(record)
                emit(
                    "tool.called",
                    {
                        "tool_call_id": call.id,
                        "tool_name": internal_tool_name,
                        "ok": result.ok,
                        "error_code": result.error_code,
                        "evidence_ids": record.evidence_ids,
                    },
                )
                observations.append(
                    tool_observation(call, result, created_count)
                )

            last_tool_observations = observations
            last_new_evidence = new_evidence
            last_new_bindings = new_bindings
            transition(RuntimeState.EVALUATING)
            evaluation = evaluate_current()
            completed = complete_if_confirmed(evaluation)
            if completed is not None:
                return completed

            if usage.tool_calls >= budget.max_tool_calls:
                return finish(RuntimeState.STOPPED_BUDGET, StopReason.BUDGET_EXHAUSTED)

            progress = (
                new_evidence
                + new_bindings
                + new_hypotheses
                + new_assessments
            )
            if progress == 0:
                reason = stop_repair_reason(
                    evaluation,
                    error_reason,
                    no_tool_calls=False,
                )
                if try_repair(reason):
                    continue
                return finalize(
                    RuntimeState.INSUFFICIENT_DATA,
                    StopReason.NO_PROGRESS,
                )


def _primary_event(parsed_log: ParsedLog) -> LogEvent | None:
    if parsed_log.primary_event_id is None:
        return None
    return next(
        (
            event
            for event in parsed_log.events
            if event.event_id == parsed_log.primary_event_id
        ),
        None,
    )


def _find_seed_matches(
    primary: LogEvent,
    java_index: JavaIndex,
) -> list[SourceMatch]:
    frames = list(primary.stack_frames[:50])
    for cause in primary.cause_chain:
        frames.extend(cause.stack_frames[:50])
        if len(frames) >= 100:
            break
    for frame in frames[:100]:
        matches = java_index.resolve_frame(frame)
        if matches:
            return matches
    return []


def _evidence_matches_thread(evidence: Evidence, thread: str) -> bool:
    content_thread = evidence.content.get("thread")
    source_thread = _thread_from_source_ref(evidence.source_ref)
    if (
        isinstance(content_thread, str)
        and source_thread is not None
        and content_thread != source_thread
    ):
        return False
    actual = content_thread if isinstance(content_thread, str) else source_thread
    return actual == thread


def _thread_from_source_ref(source_ref: str) -> str | None:
    if "thread=" not in source_ref:
        return None
    from urllib.parse import unquote

    fragment = source_ref.split("thread=", 1)[1]
    value = fragment.split("&", 1)[0]
    return unquote(value) or None


def _repair_reason_for_error(error_code: str | None) -> str | None:
    return {
        "TOOL_NOT_FOUND": "unknown_tool",
        "INVALID_ARGUMENTS": "invalid_arguments",
        "DUPLICATE_CALL": "duplicate_call",
        "INVALID_BINDING": "invalid_binding",
        "HYPOTHESIS_NOT_GROUNDED": "ungrounded_hypothesis",
        "INVALID_ASSESSMENT": "invalid_assessment",
        "INVALID_REMEDIATION": "invalid_remediation",
    }.get(error_code or "")


def _repo_ref(file_path: str, start_line: int, end_line: int) -> str:
    return f"repo://{file_path}#L{start_line}-L{end_line}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _llm_tool_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


def _tool_excerpt(data: Any, limit: int = 300) -> str:
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        text = data["text"]
    else:
        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(data)
    return " ".join(text.split())[:limit]


def _usage_total(usage: Any) -> int | None:
    if usage is None:
        return None
    if usage.total_tokens is not None:
        return usage.total_tokens
    if usage.input_tokens is not None and usage.output_tokens is not None:
        return usage.input_tokens + usage.output_tokens
    return None


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:12]}"


__all__ = ["DiagnosisRuntime"]
