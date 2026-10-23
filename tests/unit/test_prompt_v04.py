"""Unit tests for v0.4 artifact-aware prompt rendering."""

from __future__ import annotations

from tracemind.artifacts import ArtifactKind, ArtifactRecord
from tracemind.core.models import ExceptionCause, LogEvent, StackFrame
from tracemind.diagnosis.budget import Budget, BudgetUsage
from tracemind.diagnosis.evidence import EvaluationResult
from tracemind.diagnosis.prompts import (
    JVM_ANALYSIS_GUIDANCE,
    SYSTEM_PROMPT,
    build_system_prompt,
    build_user_prompt,
)


def _record(
    artifact_id: str,
    kind: ArtifactKind = ArtifactKind.THREAD_DUMP,
    *,
    warnings: list[str] | None = None,
    truncated: bool = False,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=kind,
        source_name=f"{artifact_id}.txt",
        line_count=42,
        byte_size=2048,
        truncated=truncated,
        warnings=warnings or [],
    )


def _prompt(
    *,
    primary: LogEvent | None = None,
    artifacts: list[ArtifactRecord] | None = None,
) -> str:
    return build_user_prompt(
        service="order-service",
        primary=primary,
        thread_context=None,
        evidence=[],
        hypotheses=[],
        assessments=[],
        evaluation=EvaluationResult(),
        tools=[],
        verification_environment=None,
        budget=Budget(),
        usage=BudgetUsage(),
        previous_observation=None,
        artifacts=artifacts,
    )


def test_artifact_summary_is_bounded_metadata_only() -> None:
    records = [
        _record(
            f"artifact-{index}",
            ArtifactKind.GC_LOG if index == 0 else ArtifactKind.THREAD_DUMP,
            warnings=["heap histogram may include unreachable objects"]
            if index == 0
            else [],
            truncated=index == 0,
        )
        for index in range(10)
    ]

    prompt = _prompt(artifacts=records)

    assert "JVM artifacts (user-provided point-in-time snapshots, not live):" in prompt
    assert "id=artifact-0 kind=gc_log source=artifact-0.txt lines=42" in prompt
    assert "truncated=true" in prompt
    assert "warnings=heap histogram may include unreachable objects" in prompt
    assert "id=artifact-7" in prompt
    assert "id=artifact-8" not in prompt
    assert "id=artifact-9" not in prompt
    assert "raw snapshot payload" not in prompt


def test_artifact_summary_bounds_warning_count_and_length() -> None:
    warnings = [f"warning-{index}-" + "x" * 300 for index in range(5)]

    prompt = _prompt(artifacts=[_record("thread-dump", warnings=warnings)])

    assert "warning-0-" in prompt
    assert "warning-2-" in prompt
    assert "warning-3-" not in prompt
    assert "warning-4-" not in prompt
    assert "…" in prompt


def test_artifact_section_is_absent_without_artifacts() -> None:
    prompt = _prompt()

    assert "JVM artifacts" not in prompt
    assert "artifact://" not in prompt


def test_system_prompt_adds_jvm_guidance_only_with_artifacts() -> None:
    base = build_system_prompt()
    jvm = build_system_prompt(has_artifacts=True)

    assert base == SYSTEM_PROMPT
    assert JVM_ANALYSIS_GUIDANCE not in base
    assert JVM_ANALYSIS_GUIDANCE in jvm
    assert "same-thread log context is optional" in jvm
    assert "snapshot cannot replace a code mechanism" in jvm
    assert (
        "must include a requirement whose evidence_kinds contain\n"
        "   log_thread_context"
    ) in base
    assert (
        "must include a requirement whose evidence_kinds contain\n"
        "   log_thread_context"
    ) not in jvm
    for forbidden in (
        "v04-j1-cpu-high",
        "v04-j2-memory-oom",
        "PricingService",
        "ReportCache",
        "expected answer",
    ):
        assert forbidden not in base
        assert forbidden not in jvm


def test_jvm_guidance_requires_artifact_aware_candidates() -> None:
    jvm = build_system_prompt(has_artifacts=True)

    assert "include a CPU-bound application-code candidate" in jvm
    assert "live-heap growth candidate" in jvm
    assert "Never join these mechanisms with \"or\"" in jvm
    assert "logs.get_thread_context" in jvm
    assert (
        "request thread that logged the timeout is not necessarily the CPU-hot"
        in jvm
    )
    assert "do not require the\n  logged thread itself to be hot" in jvm
    for forbidden in ("PricingService", "ReportCache", "recalculate", "hot loop"):
        assert forbidden not in jvm


def test_cause_chain_is_rendered_with_bounded_depth_and_frames() -> None:
    causes = [
        ExceptionCause(
            kind="suppressed" if index == 5 else "caused_by",
            exception_type=f"Cause{index}",
            exception_message=f"cause {index}",
            stack_frames=[
                StackFrame(
                    class_name=f"com.example.Cause{index}",
                    method_name=f"frame{frame_index}",
                    file_name=f"Cause{index}.java",
                    line_number=frame_index + 1,
                    raw="frame",
                )
                for frame_index in range(4)
            ],
        )
        for index in range(6)
    ]
    primary = LogEvent(
        event_id="evt_0001",
        source_file="incident.log",
        line_start=1,
        line_end=2,
        thread="http-a",
        logger="com.example.Service",
        message="failed to update order status",
        exception_type="IllegalStateException",
        exception_message="update failed",
        stack_frames=[],
        cause_chain=causes,
    )

    prompt = _prompt(primary=primary)

    assert "- cause chain:" in prompt
    assert "caused by [1] Cause0: cause 0" in prompt
    assert "com.example.Cause0.frame0" in prompt
    assert "com.example.Cause0.frame2" in prompt
    assert "com.example.Cause0.frame3" not in prompt
    assert "and 1 more cause(s)" in prompt
    assert "Cause5" not in prompt
