"""Deterministic offline evaluation of the two v0.4 JVM cases."""

from __future__ import annotations

import re
from typing import Any

import pytest
from helpers import (
    JVM_CASE_IDS,
    ROOT,
    expected_ref_is_present,
    hypothesis_evidence_ids,
    hypothesis_sources,
    jvm_case_fixture,
    keyword_matches,
    run_jvm_case,
    satisfied_kinds,
    source_refs_for,
    source_text,
    sources_by_id,
    top_hypothesis,
)

from tracemind.diagnosis.state import RuntimeState, StopReason

_ARTIFACT_REF_RE = re.compile(
    r"^artifact://(?P<artifact_id>[a-z][a-z0-9_-]{0,31})"
    r"#L(?P<start>\d+)(?:-L(?P<end>\d+))?$"
)
_VALIDATION_FLAGS = (
    "citations_valid",
    "artifact_citations_valid",
    "evidence_ids_valid",
    "hypotheses_valid",
    "remediation_grounded",
    "verification_labeled",
    "status_consistent",
    "artifacts_labeled",
)
_READ_ONLY_PREFIXES = ("jvm.", "code.", "logs.")


def _artifact_bounds(source_ref: str) -> tuple[str, int, int] | None:
    match = _ARTIFACT_REF_RE.fullmatch(source_ref)
    if match is None:
        return None
    start = int(match.group("start"))
    return match.group("artifact_id"), start, int(match.group("end") or start)


@pytest.mark.parametrize("case_id", JVM_CASE_IDS, ids=JVM_CASE_IDS)
def test_jvm_case_matches_expected(case_id: str) -> None:
    """Each JVM case must produce a grounded, confirmed schema 0.4 report."""
    run = run_jvm_case(case_id)
    expected = run.expected
    report = run.report

    assert report.schema_version == "0.4", f"{case_id}: expected schema 0.4"
    assert report.status == expected["expected_status"], (
        f"{case_id}: got report status {report.status!r}"
    )
    assert run.result.state is RuntimeState.COMPLETED
    assert run.result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert run.result.evaluation.run_confirmed
    assert not run.result.evaluation.ambiguity

    top = top_hypothesis(report)
    assert top.status == expected["expected_hypothesis_status"], (
        f"{case_id}: Top-1 status was {top.status!r}"
    )
    assert keyword_matches(top.statement, expected["expected_top_cause_keywords"]), (
        f"{case_id}: Top-1 did not match expected cause: {top.statement!r}"
    )
    assert all(requirement.satisfied for requirement in top.requirements), (
        f"{case_id}: unsupported requirements remain: "
        f"{top.missing_requirement_ids}"
    )
    assert any(
        requirement.discriminating and requirement.satisfied
        for requirement in top.requirements
    ), f"{case_id}: no discriminating requirement was satisfied"
    assert not top.refuting_evidence_ids, (
        f"{case_id}: Top-1 carries refuting evidence"
    )

    actual_refs = source_refs_for(report, top)
    missing_refs = [
        ref
        for ref in expected["expected_evidence_refs"]
        if not expected_ref_is_present(ref, actual_refs)
    ]
    assert not missing_refs, (
        f"{case_id}: Top-1 missing expected source refs {missing_refs}; "
        f"got {sorted(actual_refs)}"
    )
    kinds = satisfied_kinds(report, top)
    missing_kinds = set(expected["expected_evidence_kinds"]) - kinds
    assert not missing_kinds, (
        f"{case_id}: satisfied requirements missing evidence kinds "
        f"{sorted(missing_kinds)}; got {sorted(kinds)}"
    )

    context_sources = [
        source
        for source in hypothesis_sources(report, top)
        if source.kind == "log_thread_context"
    ]
    assert context_sources, f"{case_id}: no same-thread context source in report"
    assert all(
        source.thread == expected["expected_thread"] for source in context_sources
    ), [source.thread for source in context_sources]
    context_text = " ".join(source_text(source) for source in context_sources)
    for message in expected["expected_thread_context_messages"]:
        assert message in context_text, (
            f"{case_id}: same-thread context missing {message!r}"
        )
    for marker in expected["forbidden_thread_context_markers"]:
        assert marker not in context_text, (
            f"{case_id}: cross-thread marker {marker!r} leaked into context"
        )

    indexed_sources = sources_by_id(report)
    referenced = hypothesis_evidence_ids(top)
    assert referenced <= set(indexed_sources)
    assert all(source.verified for source in report.sources)
    assert all(
        source.kind in {*kinds, "log_event", "log_thread_context"}
        for source in hypothesis_sources(report, top)
    )

    for hypothesis in report.hypotheses:
        if hypothesis.hypothesis_id == top.hypothesis_id:
            continue
        assert hypothesis.status == "contradicted", (
            f"{case_id}: alternative {hypothesis.hypothesis_id} is "
            f"{hypothesis.status!r}"
        )

    for expected_refutation in expected["expected_refutations"]:
        candidates = [
            hypothesis
            for hypothesis in report.hypotheses
            if keyword_matches(
                hypothesis.statement,
                expected_refutation["hypothesis_keywords"],
            )
        ]
        assert candidates, (
            f"{case_id}: no hypothesis matched "
            f"{expected_refutation['hypothesis_keywords']}"
        )
        hypothesis = candidates[0]
        refuting_ids = set(hypothesis.refuting_evidence_ids)
        for requirement in hypothesis.requirements:
            refuting_ids.update(requirement.refuting_evidence_ids)
        refs = {
            indexed_sources[evidence_id].source_ref
            for evidence_id in refuting_ids
            if evidence_id in indexed_sources
        }
        for ref in expected_refutation["refs"]:
            assert ref in refs, (
                f"{case_id}: refutation for {hypothesis.hypothesis_id} "
                f"missing {ref}; got {sorted(refs)}"
            )


@pytest.mark.parametrize("case_id", JVM_CASE_IDS, ids=JVM_CASE_IDS)
def test_jvm_case_artifacts_are_labeled_and_bounded(case_id: str) -> None:
    """Artifact metadata exposes only basenames, bounds, and provenance."""
    run = run_jvm_case(case_id)
    expected_artifacts = run.expected["expected_artifacts"]
    report = run.report

    assert [artifact.artifact_id for artifact in report.artifacts] == [
        item["artifact_id"] for item in expected_artifacts
    ]
    assert [artifact.kind for artifact in report.artifacts] == [
        item["kind"] for item in expected_artifacts
    ]
    assert [artifact.source_name for artifact in report.artifacts] == [
        item["source_name"] for item in expected_artifacts
    ]
    assert [artifact.line_count for artifact in report.artifacts] == [
        item["line_count"] for item in expected_artifacts
    ]
    for artifact in report.artifacts:
        assert artifact.source_environment == "user_provided"
        assert not artifact.truncated
        assert not artifact.warnings
        assert "/" not in artifact.source_name
        assert "\\" not in artifact.source_name

    records = {record.artifact_id: record for record in run.result.artifacts}
    assert set(records) == {item["artifact_id"] for item in expected_artifacts}
    for record in records.values():
        assert record.source_environment == "user_provided"
        assert record.byte_size > 0
        assert record.line_count >= 1

    bounds = {
        artifact.artifact_id: artifact.line_count
        for artifact in report.artifacts
    }
    artifact_refs = [
        source.source_ref for source in report.sources
        if source.source_ref.startswith("artifact://")
    ]
    assert artifact_refs, f"{case_id}: no artifact citations in report"
    for ref in artifact_refs:
        parsed = _artifact_bounds(ref)
        assert parsed is not None, f"{case_id}: unparsable artifact ref {ref}"
        artifact_id, start, end = parsed
        assert artifact_id in bounds, f"{case_id}: unknown artifact id in {ref}"
        assert 1 <= start <= end <= bounds[artifact_id], (
            f"{case_id}: out-of-range artifact ref {ref}"
        )

    serialized = report.model_dump_json()
    assert str(ROOT) not in serialized
    assert "/Users/" not in serialized
    assert "Full thread dump" not in serialized
    assert "jmap -histo" not in serialized


@pytest.mark.parametrize("case_id", JVM_CASE_IDS, ids=JVM_CASE_IDS)
def test_jvm_case_remediation_is_grounded(case_id: str) -> None:
    """Every remediation action cites evidence from the confirmed hypothesis."""
    run = run_jvm_case(case_id)
    report = run.report
    expected = run.expected
    top = top_hypothesis(report)
    indexed_sources = sources_by_id(report)
    referenced = hypothesis_evidence_ids(top)

    actions = report.remediation_plan
    assert actions, f"{case_id}: expected a non-empty remediation plan"
    action_types = {action.type for action in actions}
    missing_types = set(expected["expected_remediation_types"]) - action_types
    assert not missing_types, (
        f"{case_id}: remediation missing types {sorted(missing_types)}; "
        f"got {sorted(action_types)}"
    )
    target_keywords = expected["expected_remediation_target_keywords"]
    assert any(
        keyword.lower() in action.target.lower()
        for action in actions
        for keyword in target_keywords
    ), [action.target for action in actions]

    action_refs = set()
    for action in actions:
        assert action.hypothesis_id == top.hypothesis_id
        assert action.evidence_ids, (
            f"{case_id}: action {action.action_id} has no evidence binding"
        )
        assert set(action.evidence_ids) <= referenced, (
            f"{case_id}: action {action.action_id} cites evidence outside "
            "the confirmed hypothesis"
        )
        action_refs.update(
            indexed_sources[evidence_id].source_ref
            for evidence_id in action.evidence_ids
            if evidence_id in indexed_sources
        )
    for ref in expected["expected_remediation_evidence_refs"]:
        assert ref in action_refs, (
            f"{case_id}: remediation missing grounded ref {ref}; "
            f"got {sorted(action_refs)}"
        )

    assert not run.result.rejected_remediations


@pytest.mark.parametrize("case_id", JVM_CASE_IDS, ids=JVM_CASE_IDS)
def test_jvm_case_tools_and_validation(case_id: str) -> None:
    """Only read-only JVM/code/log tools ran, and validation passed."""
    run = run_jvm_case(case_id)
    expected = run.expected
    report = run.report

    called = [call.tool_name for call in run.result.tool_calls]
    for tool in expected["expected_jvm_tools"]:
        assert tool in called, f"{case_id}: expected tool {tool} was not called"
    for tool in expected["forbidden_tool_calls"]:
        assert tool not in called, f"{case_id}: forbidden tool ran: {tool}"
    assert all(
        name.startswith(_READ_ONLY_PREFIXES)
        or name in {
            "diagnosis.propose_hypothesis",
            "diagnosis.assess_evidence",
            "diagnosis.propose_remediation",
        }
        for name in called
    ), called
    assert all(call.ok for call in run.result.tool_calls), [
        (call.tool_name, call.error_code)
        for call in run.result.tool_calls
        if not call.ok
    ]

    for flag in _VALIDATION_FLAGS:
        assert getattr(report.validation, flag), (
            f"{case_id}: validation flag {flag} is false: "
            f"{report.validation.errors}"
        )
    assert not report.validation.errors, report.validation.errors

    assert all(
        "user-provided" in limitation
        or "same-thread" in limitation
        or "Heap dump" in limitation
        or "v0.3" in limitation
        or "Source/deployed" in limitation
        or "local read-only" in limitation
        or "Call edges" in limitation
        for limitation in report.limitations
    ), report.limitations
    assert any(
        "user-provided point-in-time text files" in limitation
        for limitation in report.limitations
    ), report.limitations
    assert any(
        "same-thread log context is not required" in limitation
        for limitation in report.limitations
    ), report.limitations
    assert any(
        "Heap dump/JFR was not parsed" in limitation
        for limitation in report.limitations
    ), report.limitations


@pytest.mark.parametrize("case_id", JVM_CASE_IDS, ids=JVM_CASE_IDS)
def test_jvm_case_expected_yaml_matches_fixture(case_id: str) -> None:
    """Fixture paths, manifest metadata, and expected answers must agree."""
    fixture = jvm_case_fixture(case_id)
    run = run_jvm_case(case_id)
    expected = run.expected
    manifest = run.artifacts.manifest

    assert expected["case_id"] == case_id
    assert manifest.service == fixture.service
    assert fixture.log_path.is_file()
    assert fixture.repo_path.is_dir()
    assert fixture.artifacts_path.is_dir()
    assert fixture.mock_path.is_file()
    assert fixture.expected_path.is_file()
    assert [spec.id for spec in manifest.artifacts] == [
        item["artifact_id"] for item in expected["expected_artifacts"]
    ]
    assert [spec.kind.value for spec in manifest.artifacts] == [
        item["kind"] for item in expected["expected_artifacts"]
    ]


def test_jvm_cases_are_offline() -> None:
    """Both JVM case runs use only the local mock provider."""
    for case_id in JVM_CASE_IDS:
        run = run_jvm_case(case_id)
        assert run.result.llm_calls
        assert {record.provider for record in run.result.llm_calls} == {"mock"}
        assert {record.model for record in run.result.llm_calls} == {"v04-case"}
        assert run.report.verification.environment == "none"


def test_cpu_artifacts_relax_same_thread_requirement() -> None:
    """The hot thread differs from the log thread, yet the run confirms."""
    run = run_jvm_case("v04-j1-cpu-high")
    expected = run.expected
    top = top_hypothesis(run.report)
    indexed = sources_by_id(run.report)

    hot_sources = [
        source
        for source in hypothesis_sources(run.report, top)
        if source.kind == "thread_cpu"
    ]
    assert hot_sources
    assert any("pricing-exec-1" in source.claim for source in hot_sources)
    context_sources = [
        source
        for source in hypothesis_sources(run.report, top)
        if source.kind == "log_thread_context"
    ]
    assert context_sources
    assert all(
        source.thread == expected["expected_thread"] for source in context_sources
    )
    assert expected["expected_thread"] not in {
        indexed[source.evidence_id].thread or "" for source in hot_sources
    }
    assert any(
        "same-thread log context is not required" in limitation
        for limitation in run.report.limitations
    )


def test_jvm_case_metrics_meet_thresholds() -> None:
    """Aggregate Top-1/Top-3, coverage, citations, and grounding metrics."""
    top1 = top3 = coverage = 0
    total_sources = valid_sources = artifact_sources = 0
    total_actions = grounded_actions = 0
    unauthorized = 0
    details: dict[str, Any] = {}

    for case_id in JVM_CASE_IDS:
        run = run_jvm_case(case_id)
        expected = run.expected
        report = run.report
        top = top_hypothesis(report)
        matched = keyword_matches(
            top.statement,
            expected["expected_top_cause_keywords"],
        )
        top1 += int(top.status == "confirmed" and matched)
        top3 += int(
            any(
                hypothesis.status == "confirmed"
                and keyword_matches(
                    hypothesis.statement,
                    expected["expected_top_cause_keywords"],
                )
                for hypothesis in report.hypotheses[:3]
            )
        )
        complete = all(
            requirement.satisfied for requirement in top.requirements
        )
        coverage += int(complete)
        total_sources += len(report.sources)
        valid_sources += sum(1 for source in report.sources if source.verified)
        artifact_sources += sum(
            1
            for source in report.sources
            if source.source_ref.startswith("artifact://")
        )
        total_actions += len(report.remediation_plan)
        grounded_actions += sum(
            1
            for action in report.remediation_plan
            if action.evidence_ids
            and set(action.evidence_ids) <= set(sources_by_id(report))
        )
        unauthorized += sum(
            1
            for call in run.result.tool_calls
            if call.tool_name.startswith(("db.", "shell."))
        )
        details[case_id] = {
            "top1": matched and top.status == "confirmed",
            "coverage": complete,
            "artifact_sources": artifact_sources,
        }

    case_count = len(JVM_CASE_IDS)
    metrics = {
        "details": details,
        "top1": f"{top1}/{case_count}",
        "top3": f"{top3}/{case_count}",
        "coverage": f"{coverage}/{case_count}",
        "citations": f"{valid_sources}/{total_sources}",
        "grounding": f"{grounded_actions}/{total_actions}",
        "unauthorized": unauthorized,
    }
    assert top1 == case_count, metrics
    assert top3 == case_count, metrics
    assert coverage == case_count, metrics
    assert total_sources > 0 and valid_sources == total_sources, metrics
    assert artifact_sources > 0, metrics
    assert total_actions > 0 and grounded_actions == total_actions, metrics
    assert unauthorized == 0, metrics
