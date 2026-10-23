"""Opt-in live DeepSeek evaluation of the two v0.4 JVM cases."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from tracemind.artifacts import ArtifactBundle, load_artifacts
from tracemind.diagnosis.budget import Budget
from tracemind.diagnosis.report import (
    Report,
    ReportHypothesis,
    ReportSource,
    build_report,
)
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.config import require_api_key, resolve_settings
from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.log_analysis.parser import LogParser

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
CASE_IDS = (
    "v04-j1-cpu-high",
    "v04-j2-memory-oom",
)
REPO_BY_CASE = {
    "v04-j1-cpu-high": "v04-jvm-hot-loop",
    "v04-j2-memory-oom": "v04-jvm-unbounded-cache",
}
SERVICE = "order-service"
LIVE_MAX_TOKENS = 2200
LIVE_TIMEOUT_SECONDS = 90.0
LIVE_MAX_RETRIES = 1
LIVE_BUDGET = Budget(
    max_iterations=18,
    max_llm_calls=20,
    max_tool_calls=28,
    max_hypotheses=4,
)
JVM_SYMPTOM_KINDS = frozenset(
    {
        "thread_dump",
        "thread_cpu",
        "gc_event",
        "gc_summary",
        "heap_summary",
    }
)
MECHANISM_KINDS = frozenset(
    {"source_code", "call_path", "sql", "annotation", "config", "db_schema"}
)
READ_ONLY_PREFIXES = ("jvm.", "code.", "logs.")
DIAGNOSIS_CONTROLS = frozenset(
    {
        "diagnosis.propose_hypothesis",
        "diagnosis.assess_evidence",
        "diagnosis.propose_remediation",
    }
)
VALIDATION_FLAGS = (
    "citations_valid",
    "artifact_citations_valid",
    "evidence_ids_valid",
    "hypotheses_valid",
    "remediation_grounded",
    "verification_labeled",
    "status_consistent",
    "artifacts_labeled",
)
ARTIFACT_REF_RE = re.compile(
    r"^artifact://(?P<artifact_id>[a-z][a-z0-9_-]{0,31})"
    r"#L(?P<start>\d+)(?:-L(?P<end>\d+))?$"
)


@dataclass(frozen=True)
class LiveJvmRun:
    """One live JVM case result; ``error`` stays cacheable and non-secret."""

    case_id: str
    expected: dict[str, Any]
    artifacts: ArtifactBundle | None = None
    result: Any | None = None
    report: Report | None = None
    error: str | None = None


def _expected(case_id: str) -> dict[str, Any]:
    path = ROOT / "fixtures" / "expected" / f"{case_id}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def _run_live(case_id: str) -> LiveJvmRun:
    expected = _expected(case_id)
    try:
        settings = resolve_settings(
            max_tokens=LIVE_MAX_TOKENS,
            timeout=LIVE_TIMEOUT_SECONDS,
            max_retries=LIVE_MAX_RETRIES,
        )
        require_api_key(settings)
        repo = ROOT / "fixtures" / "repos" / REPO_BY_CASE[case_id]
        log_path = ROOT / "fixtures" / "logs" / case_id / "incident.log"
        artifacts_path = ROOT / "fixtures" / "artifacts" / case_id

        parsed = LogParser().parse(log_path)
        index = TreeSitterJavaIndex()
        index.index(repo)
        artifacts = load_artifacts(artifacts_path, SERVICE)
        provider = DeepSeekProvider(
            model=settings.model,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )
        runtime = DiagnosisRuntime(
            repo_root=repo,
            provider_name="deepseek",
            model=settings.model,
            repair_attempts=settings.repair_attempts,
            artifacts=artifacts,
        )
        result = runtime.run(
            parsed,
            index,
            SERVICE,
            provider,
            LIVE_BUDGET,
        )
        report = build_report(result, parsed, repo)
        return LiveJvmRun(
            case_id=case_id,
            expected=expected,
            artifacts=artifacts,
            result=result,
            report=report,
        )
    except Exception as exc:  # keep live failures bounded and observable
        message = f"{type(exc).__name__}: {exc}"
        for env_name in ("DEEPSEEK_API_KEY",):
            secret = os.environ.get(env_name, "")
            if secret:
                message = message.replace(secret, "***")
        return LiveJvmRun(
            case_id=case_id,
            expected=expected,
            error=message,
        )


def _require_run(case_id: str) -> LiveJvmRun:
    run = _run_live(case_id)
    assert run.error is None, f"{case_id}: live run failed: {run.error}"
    assert run.result is not None and run.report is not None
    return run


def _hypothesis_sources(
    report: Report,
    hypothesis: ReportHypothesis,
) -> list[ReportSource]:
    ids = {
        *hypothesis.basis_evidence_ids,
        *hypothesis.supporting_evidence_ids,
        *hypothesis.refuting_evidence_ids,
    }
    for requirement in hypothesis.requirements:
        ids.update(requirement.supporting_evidence_ids)
        ids.update(requirement.refuting_evidence_ids)
    by_id = {source.evidence_id: source for source in report.sources}
    return [
        by_id[evidence_id]
        for evidence_id in ids
        if evidence_id in by_id
    ]


def _satisfied_kinds(
    report: Report,
    hypothesis: ReportHypothesis,
) -> set[str]:
    by_id = {source.evidence_id: source for source in report.sources}
    kinds: set[str] = set()
    for requirement in hypothesis.requirements:
        if not requirement.satisfied:
            continue
        for evidence_id in requirement.supporting_evidence_ids:
            source = by_id.get(evidence_id)
            if source is not None:
                kinds.add(source.kind)
    return kinds


def _keyword_matches(statement: str, expected: dict[str, Any]) -> bool:
    lowered = statement.lower()
    return any(
        keyword.lower() in lowered
        for keyword in expected["expected_top_cause_keywords"]
    )


def _artifact_bounds(source_ref: str) -> tuple[str, int, int] | None:
    match = ARTIFACT_REF_RE.fullmatch(source_ref)
    if match is None:
        return None
    start = int(match.group("start"))
    return (
        match.group("artifact_id"),
        start,
        int(match.group("end") or start),
    )


def _assert_artifact_citations(run: LiveJvmRun) -> None:
    assert run.report is not None
    report = run.report
    bounds = {
        artifact.artifact_id: artifact.line_count
        for artifact in report.artifacts
    }
    artifact_refs = [
        source.source_ref
        for source in report.sources
        if source.source_ref.startswith("artifact://")
    ]
    assert artifact_refs, f"{run.case_id}: live report cites no artifact"
    for ref in artifact_refs:
        parsed = _artifact_bounds(ref)
        assert parsed is not None, f"{run.case_id}: bad artifact ref {ref}"
        artifact_id, start, end = parsed
        assert artifact_id in bounds, (
            f"{run.case_id}: unknown artifact id in {ref}"
        )
        assert 1 <= start <= end <= bounds[artifact_id], (
            f"{run.case_id}: out-of-range artifact ref {ref}"
        )


def _assert_no_secret(run: LiveJvmRun) -> None:
    assert run.report is not None
    serialized = run.report.model_dump_json()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    assert api_key
    assert api_key not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized
    assert "sk-" not in serialized
    assert "/Users/" not in serialized


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_live_jvm_case_is_grounded(case_id: str) -> None:
    """A live JVM run must produce a bounded, grounded schema 0.4 report."""
    run = _require_run(case_id)
    report = run.report
    result = run.result
    assert report is not None and result is not None
    assert run.artifacts is not None
    top = report.hypotheses[0] if report.hypotheses else None
    assert top is not None, f"{case_id}: no hypotheses were proposed"

    assert report.schema_version == "0.4"
    assert report.status in {"confirmed", "probable"}, (
        f"{case_id}: live status was {report.status!r}"
    )
    assert top.status in {"confirmed", "probable"}, (
        f"{case_id}: live Top-1 status was {top.status!r}"
    )
    assert _keyword_matches(top.statement, run.expected), (
        f"{case_id}: Top-1 did not match the expected cause: "
        f"{top.statement!r}"
    )
    if top.status == "confirmed":
        assert report.status == "confirmed"
        assert result.evaluation.run_confirmed
        assert not result.evaluation.ambiguity
        assert all(
            requirement.satisfied for requirement in top.requirements
        ), f"{case_id}: confirmed without full coverage"
        assert not top.refuting_evidence_ids, (
            f"{case_id}: confirmed Top-1 carries refuting evidence"
        )
        assert all(
            hypothesis.status == "contradicted"
            for hypothesis in report.hypotheses[1:]
        ), f"{case_id}: confirmed run left alternative hypotheses open"
    else:
        assert report.status != "confirmed"
        assert not result.evaluation.run_confirmed
        assert top.missing_requirement_ids, (
            f"{case_id}: probable Top-1 has no missing requirement"
        )

    kinds = _satisfied_kinds(report, top)
    assert kinds & JVM_SYMPTOM_KINDS, (
        f"{case_id}: Top-1 has no satisfied JVM symptom requirement; "
        f"got {sorted(kinds)}"
    )
    assert kinds & MECHANISM_KINDS, (
        f"{case_id}: Top-1 has no satisfied mechanism requirement; "
        f"got {sorted(kinds)}"
    )
    top_sources = _hypothesis_sources(report, top)
    assert any(
        source.kind in JVM_SYMPTOM_KINDS for source in top_sources
    ), f"{case_id}: Top-1 has no JVM artifact source"

    expected_artifacts = run.expected["expected_artifacts"]
    assert [artifact.artifact_id for artifact in report.artifacts] == [
        item["artifact_id"] for item in expected_artifacts
    ]
    assert [artifact.kind for artifact in report.artifacts] == [
        item["kind"] for item in expected_artifacts
    ]
    for artifact in report.artifacts:
        assert artifact.source_environment == "user_provided"
        assert "/" not in artifact.source_name
        assert "\\" not in artifact.source_name
    _assert_artifact_citations(run)

    assert all(source.verified for source in report.sources), [
        source.source_ref for source in report.sources if not source.verified
    ]
    for flag in VALIDATION_FLAGS:
        assert getattr(report.validation, flag), (
            f"{case_id}: validation flag {flag} is false: "
            f"{report.validation.errors}"
        )
    assert not report.validation.errors, report.validation.errors

    actions = report.remediation_plan
    if top.status == "confirmed":
        assert actions, f"{case_id}: confirmed run has no remediation plan"
    source_ids = {source.evidence_id for source in report.sources}
    for action in actions:
        assert action.evidence_ids, (
            f"{case_id}: action {action.action_id} has no evidence binding"
        )
        assert set(action.evidence_ids) <= source_ids, (
            f"{case_id}: action {action.action_id} cites unknown evidence"
        )

    called = [call.tool_name for call in result.tool_calls]
    assert any(name.startswith("jvm.") for name in called), (
        f"{case_id}: no JVM tool was used; tools={called}"
    )
    for tool in run.expected["forbidden_tool_calls"]:
        assert tool not in called, f"{case_id}: forbidden tool ran: {tool}"
    assert all(
        name.startswith(READ_ONLY_PREFIXES)
        or name in DIAGNOSIS_CONTROLS
        for name in called
    ), called
    failed_tools = [
        (call.tool_name, call.error_code)
        for call in result.tool_calls
        if not call.ok
        and call.tool_name.startswith(READ_ONLY_PREFIXES)
        and call.error_code != "DUPLICATE_CALL"
    ]
    assert not failed_tools, f"{case_id}: read-only tool failed: {failed_tools}"
    duplicate_tools = [
        call.tool_name
        for call in result.tool_calls
        if not call.ok
        and call.tool_name.startswith(READ_ONLY_PREFIXES)
        and call.error_code == "DUPLICATE_CALL"
    ]
    if duplicate_tools:
        print(
            f"LIVE_JVM_DEDUPE case={case_id} duplicates={duplicate_tools}"
        )
    rejected_controls = [
        (call.tool_name, call.error_code)
        for call in result.tool_calls
        if not call.ok and call.tool_name in DIAGNOSIS_CONTROLS
    ]
    if rejected_controls:
        print(
            f"LIVE_JVM_REPAIR case={case_id} rejected={rejected_controls}"
        )

    assert report.verification.environment == "none"
    assert result.llm_usage.calls > 0
    assert result.llm_calls
    assert {record.provider for record in result.llm_calls} == {"deepseek"}
    model = resolve_settings(max_tokens=LIVE_MAX_TOKENS).model
    assert {record.model for record in result.llm_calls} == {model}
    assert result.budget_usage["iterations"] <= LIVE_BUDGET.max_iterations
    assert result.budget_usage["llm_calls"] <= LIVE_BUDGET.max_llm_calls
    assert result.budget_usage["tool_calls"] <= LIVE_BUDGET.max_tool_calls
    _assert_no_secret(run)

    print(
        "LIVE_JVM_CASE "
        f"case={case_id} status={report.status} "
        f"top={top.hypothesis_id}/{top.status} "
        f"model={model} "
        f"llm_calls={result.llm_usage.calls} "
        f"tokens={result.llm_usage.total_tokens} "
        f"latency_ms={result.llm_usage.latency_ms} "
        f"tool_calls={len(result.tool_calls)} "
        f"stop={result.stop_reason.value}"
    )


def test_live_jvm_top1_and_top3_metrics() -> None:
    """Record Top-1/Top-3 across both live runs without faking a PASS."""
    runs = [_require_run(case_id) for case_id in CASE_IDS]
    top1 = 0
    top3 = 0
    lines: list[str] = []
    for run in runs:
        report = run.report
        assert report is not None
        hits = [
            _keyword_matches(hypothesis.statement, run.expected)
            and hypothesis.status != "contradicted"
            for hypothesis in report.hypotheses[:3]
        ]
        top1 += int(bool(hits and hits[0]))
        top3 += int(any(hits))
        lines.append(
            f"{run.case_id}: status={report.status} "
            f"top1={bool(hits and hits[0])} top3={any(hits)}"
        )
    print("LIVE_JVM_METRICS\n" + "\n".join(lines))
    assert top1 >= 1, (
        f"live Top-1 target is >=1/2; got {top1}/2\n" + "\n".join(lines)
    )
    assert top3 == 2, (
        f"live Top-3 target is 2/2; got {top3}/2\n" + "\n".join(lines)
    )
