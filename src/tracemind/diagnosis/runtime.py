"""Deterministic minimal diagnosis runtime for v0.1."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from tracemind.core.models import LogEvent, ParsedLog
from tracemind.diagnosis.budget import Budget, BudgetUsage
from tracemind.diagnosis.evaluator import evaluate
from tracemind.diagnosis.evidence import (
    Evidence,
    Hypothesis,
    LLMCallRecord,
    RunResult,
    ToolCallRecord,
    summarize_llm_usage,
)
from tracemind.diagnosis.state import (
    RuntimeEvent,
    RuntimeState,
    StopReason,
    validate_transition,
)
from tracemind.indexing.java_index import JavaIndex, SourceMatch
from tracemind.llm.messages import Message, ToolDefinition
from tracemind.llm.provider import LLMProvider, LLMProviderError
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolRequest, ToolResult
from tracemind.tools.executor import ToolExecutor
from tracemind.tools.registry import ToolRegistry

SYSTEM_PROMPT = (
    "You are TraceMind, a Java incident diagnosis agent. "
    "You may only call the provided read-only tools. "
    "Plan the next evidence-gathering step. "
    "Do not claim that a root cause is confirmed; a deterministic evaluator decides. "
    "Do not fabricate source locations or log events."
)

LIMITATIONS = (
    "v0.1 uses one local log and one local repository.",
    "Source/deployed version consistency is not verified.",
    "Only local read-only tools are available; no remote runtime evidence is collected.",
)


class DiagnosisRuntime:
    """Run a bounded, deterministic, tool-using diagnosis loop."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        repo_root: Path | None = None,
        provider_name: str = "unknown",
        model: str = "unknown",
    ) -> None:
        self._tool_registry = tool_registry or build_default_registry()
        self._repo_root = repo_root
        self._provider_name = provider_name
        self._model = model

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
        evidence: list[Evidence] = []
        hypotheses: list[Hypothesis] = []
        tool_records: list[ToolCallRecord] = []
        llm_calls: list[LLMCallRecord] = []
        events: list[RuntimeEvent] = []
        current_state = RuntimeState.INGESTING
        evidence_counter = 0
        hypothesis_id = "hyp_001"

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

        def finish(state: RuntimeState, stop: StopReason) -> RunResult:
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
                hypotheses=hypotheses,
                evidence=evidence,
                tool_calls=tool_records,
                llm_calls=llm_calls,
                llm_usage=summarize_llm_usage(llm_calls),
                budget_usage=usage.as_dict(),
                limitations=list(LIMITATIONS),
                events=events,
            )

        def add_evidence(
            kind: str,
            claim: str,
            source_ref: str,
            strength: str,
            tool_call_id: str | None = None,
        ) -> Evidence:
            nonlocal evidence_counter
            evidence_counter += 1
            item = Evidence(
                evidence_id=f"ev_{evidence_counter:04d}",
                kind=kind,
                claim=claim,
                source_ref=source_ref,
                supports=[hypothesis_id],
                strength=strength,
                tool_call_id=tool_call_id,
                created_at=_now(),
            )
            evidence.append(item)
            emit(
                "evidence.created",
                {
                    "evidence_id": item.evidence_id,
                    "kind": item.kind,
                    "source_ref": item.source_ref,
                },
            )
            return item

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
        if primary is None:
            hypothesis = Hypothesis(
                hypothesis_id=hypothesis_id,
                statement="No parsed log events were available.",
                status="insufficient_data",
                missing_evidence=["log_event", "source_code"],
            )
            hypotheses.append(hypothesis)
            emit(
                "hypothesis.created",
                {"hypothesis_id": hypothesis_id, "status": hypothesis.status},
            )
            return finish(RuntimeState.INSUFFICIENT_DATA, StopReason.NO_PROGRESS)

        transition(RuntimeState.SEEDING)
        source_matches = _find_seed_matches(primary, java_index)

        if not source_matches:
            hypothesis = Hypothesis(
                hypothesis_id=hypothesis_id,
                statement=(
                    "No in-project source frame was found for "
                    f"{primary.exception_type or primary.event_id}."
                ),
                status="insufficient_data",
                missing_evidence=["source_code"],
            )
            hypotheses.append(hypothesis)
            log_evidence = add_evidence(
                "log_event",
                f"Primary log event {primary.event_id}: {primary.message}",
                f"log://{primary.event_id}",
                "strong",
            )
            hypothesis.evidence_ids = [log_evidence.evidence_id]
            emit(
                "hypothesis.created",
                {"hypothesis_id": hypothesis_id, "status": hypothesis.status},
            )
            return finish(RuntimeState.INSUFFICIENT_DATA, StopReason.NO_PROGRESS)

        first_match = source_matches[0]
        matched_line = first_match.matched_line or first_match.start_line
        method_name = first_match.symbol.method_name or ""
        statement = (
            f"Exception originates at {first_match.symbol.fqn}.{method_name} "
            f"({first_match.file_path}:{matched_line})"
        )
        hypothesis = Hypothesis(
            hypothesis_id=hypothesis_id,
            statement=statement,
            status="supported",
            missing_evidence=["source_code"],
            source_matches=source_matches,
        )
        hypotheses.append(hypothesis)

        stack_evidence = add_evidence(
            "stack_frame",
            (
                f"Stack frame {first_match.symbol.fqn}.{method_name} "
                f"at {first_match.file_path}:{matched_line}"
            ),
            f"log://{primary.event_id}",
            "strong",
        )
        log_evidence = add_evidence(
            "log_event",
            f"Primary log event {primary.event_id}: {primary.message}",
            f"log://{primary.event_id}",
            "strong",
        )
        hypothesis.evidence_ids = [
            stack_evidence.evidence_id,
            log_evidence.evidence_id,
        ]
        emit(
            "hypothesis.created",
            {
                "hypothesis_id": hypothesis_id,
                "status": hypothesis.status,
                "source_matches": len(source_matches),
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
        )
        executor = ToolExecutor(
            self._tool_registry,
            context,
            default_max_output_bytes=budget.max_output_bytes,
        )
        tool_definitions = [
            ToolDefinition(
                name=spec.name,
                description=spec.description,
                parameters=spec.input_model.model_json_schema(),
            )
            for spec in self._tool_registry.list_tools()
        ]

        def build_messages() -> list[Message]:
            source_lines = [
                f"- {match.file_path}:{match.start_line}-{match.end_line} "
                f"{match.symbol.fqn}.{match.symbol.method_name or ''}"
                for match in hypothesis.source_matches[:5]
            ]
            evidence_lines = [
                f"- {item.evidence_id} [{item.kind}] {item.source_ref}"
                for item in evidence[-10:]
            ]
            frame_lines = [
                f"- {frame.class_name}.{frame.method_name} "
                f"({frame.file_name}:{frame.line_number})"
                for frame in primary.stack_frames[:5]
            ]
            user_content = "\n".join(
                [
                    f"Service: {service}",
                    f"Primary event: {primary.event_id} {primary.level or ''} "
                    f"{primary.message}",
                    f"Exception: {primary.exception_type or 'unknown'}: "
                    f"{primary.exception_message or ''}",
                    "Stack frames:",
                    *(frame_lines or ["- (none)"]),
                    f"Hypothesis: {hypothesis.statement}",
                    f"Missing evidence: {', '.join(hypothesis.missing_evidence) or 'none'}",
                    "Source candidates:",
                    *(source_lines or ["- (none)"]),
                    "Evidence:",
                    *(evidence_lines or ["- (none)"]),
                    (
                        "Remaining budget: "
                        f"iterations={budget.max_iterations - usage.iterations}, "
                        f"llm_calls={budget.max_llm_calls - usage.llm_calls}, "
                        f"tool_calls={budget.max_tool_calls - usage.tool_calls}"
                    ),
                    "Use the registered read-only tools to gather missing evidence.",
                    "Do not claim that the root cause is confirmed.",
                ]
            )
            return [
                Message(role="system", content=SYSTEM_PROMPT),
                Message(role="user", content=user_content),
            ]

        def evidence_from_tool(
            result: ToolResult,
            tool_call_id: str,
        ) -> list[Evidence]:
            created: list[Evidence] = []
            data = result.data
            if result.tool_name == "code.get_source_range" and isinstance(data, dict):
                file_path = data.get("file_path")
                start = data.get("start_line")
                end = data.get("end_line")
                if (
                    isinstance(file_path, str)
                    and isinstance(start, int)
                    and isinstance(end, int)
                ):
                    ref = result.source_ref or f"repo://{file_path}#L{start}-L{end}"
                    created.append(
                        add_evidence(
                            "source_code",
                            f"Source range {file_path}:{start}-{end}",
                            ref,
                            "strong",
                            tool_call_id,
                        )
                    )
                return created

            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                return created

            for item in items:
                if not isinstance(item, dict):
                    continue
                if result.tool_name in {"logs.search", "logs.get_event_context"}:
                    log_ref = item.get("source_ref")
                    if isinstance(log_ref, str):
                        created.append(
                            add_evidence(
                                "log_event",
                                f"Log event {item.get('event_id')}: "
                                f"{item.get('message', '')}",
                                log_ref,
                                "strong",
                                tool_call_id,
                            )
                        )
                elif result.tool_name == "code.find_symbol":
                    file_path = item.get("file_path")
                    start = item.get("start_line")
                    end = item.get("end_line")
                    if (
                        not isinstance(file_path, str)
                        or not isinstance(start, int)
                        or not isinstance(end, int)
                    ):
                        continue
                    symbol = item.get("symbol")
                    fqn = ""
                    method = ""
                    if isinstance(symbol, dict):
                        fqn = str(symbol.get("fqn") or "")
                        method = str(symbol.get("method_name") or "")
                    ref = f"repo://{file_path}#L{start}-L{end}"
                    created.append(
                        add_evidence(
                            "source_code",
                            f"Source symbol {fqn}.{method} at {file_path}:{start}",
                            ref,
                            "medium",
                            tool_call_id,
                        )
                    )
            return created

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
                response = provider.complete(build_messages(), tool_definitions)
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

            if not response.tool_calls:
                transition(RuntimeState.EVALUATING)
                evaluate(hypothesis, evidence)
                emit(
                    "hypothesis.updated",
                    {
                        "hypothesis_id": hypothesis_id,
                        "status": hypothesis.status,
                        "missing_evidence": hypothesis.missing_evidence,
                    },
                )
                if hypothesis.status == "confirmed":
                    transition(RuntimeState.REPORTING)
                    return finish(
                        RuntimeState.COMPLETED,
                        StopReason.EVIDENCE_SUFFICIENT,
                    )
                return finish(RuntimeState.INSUFFICIENT_DATA, StopReason.NO_PROGRESS)

            transition(RuntimeState.EXECUTING)
            new_evidence = 0
            for call in response.tool_calls:
                if usage.tool_calls >= budget.max_tool_calls:
                    return finish(
                        RuntimeState.STOPPED_BUDGET,
                        StopReason.BUDGET_EXHAUSTED,
                    )
                request = ToolRequest(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    run_id=run_id,
                )
                result = executor.execute(request)
                usage.tool_calls += 1
                created = (
                    evidence_from_tool(result, call.id) if result.ok else []
                )
                record = ToolCallRecord(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    arguments=call.arguments,
                    ok=result.ok,
                    error_code=result.error_code,
                    duration_ms=result.duration_ms,
                    evidence_ids=[item.evidence_id for item in created],
                )
                tool_records.append(record)
                emit(
                    "tool.called",
                    {
                        "tool_call_id": call.id,
                        "tool_name": call.name,
                        "ok": result.ok,
                        "error_code": result.error_code,
                        "evidence_ids": record.evidence_ids,
                    },
                )
                new_evidence += len(created)

            transition(RuntimeState.EVALUATING)
            evaluate(hypothesis, evidence)
            emit(
                "hypothesis.updated",
                {
                    "hypothesis_id": hypothesis_id,
                    "status": hypothesis.status,
                    "missing_evidence": hypothesis.missing_evidence,
                },
            )
            if hypothesis.status == "confirmed":
                transition(RuntimeState.REPORTING)
                return finish(RuntimeState.COMPLETED, StopReason.EVIDENCE_SUFFICIENT)
            if new_evidence == 0:
                return finish(RuntimeState.INSUFFICIENT_DATA, StopReason.NO_PROGRESS)
            if usage.tool_calls >= budget.max_tool_calls:
                return finish(RuntimeState.STOPPED_BUDGET, StopReason.BUDGET_EXHAUSTED)


def _primary_event(parsed_log: ParsedLog) -> LogEvent | None:
    if parsed_log.primary_event_id is not None:
        for event in parsed_log.events:
            if event.event_id == parsed_log.primary_event_id:
                return event
    return parsed_log.events[0] if parsed_log.events else None


def _find_seed_matches(
    primary: LogEvent,
    java_index: JavaIndex,
) -> list[SourceMatch]:
    for frame in primary.stack_frames:
        matches = java_index.resolve_frame(frame)
        if matches:
            return matches
    return []


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
