"""Opt-in live DeepSeek evaluation of the three v0.3 diagnosis cases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from tracemind.diagnosis.budget import Budget
from tracemind.diagnosis.report import Report, ReportHypothesis, ReportSource, build_report
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.config import require_api_key, resolve_settings
from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.log_analysis.parser import LogParser
from tracemind.verification import load_verification_data

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
CASE_IDS = (
    "v03-c1-missing-row",
    "v03-c2-duplicate-callback",
    "v03-c3-mapper-stub",
)
REPO_BY_CASE = {
    "v03-c1-missing-row": "minimal-order-service-fixed",
    "v03-c2-duplicate-callback": "minimal-order-service-fixed",
    "v03-c3-mapper-stub": "minimal-order-service",
}
EXPECTED_MARKER = {
    "v03-c1-missing-row": "db://orders/id=10086",
    "v03-c2-duplicate-callback": "db://orders/id=10086",
    "v03-c3-mapper-stub": "OrderMapper.java",
}
CODE_KINDS = frozenset({"source_code", "call_path", "sql", "annotation", "config"})
_VALIDATION_FLAGS = (
    "citations_valid",
    "evidence_ids_valid",
    "hypotheses_valid",
    "remediation_grounded",
    "verification_labeled",
    "status_consistent",
)


@dataclass(frozen=True)
class LiveRun:
    """One live case result; ``error`` keeps failures cacheable and non-secret."""

    case_id: str
    expected: dict[str, Any]
    result: Any | None = None
    report: Report | None = None
    error: str | None = None


def _expected(case_id: str) -> dict[str, Any]:
    path = ROOT / "fixtures" / "expected" / f"{case_id}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def _run_live(case_id: str) -> LiveRun:
    expected = _expected(case_id)
    try:
        settings = resolve_settings(
            max_tokens=2000,
            timeout=90.0,
            max_retries=1,
        )
        require_api_key(settings)
        repo = ROOT / "fixtures" / "repos" / REPO_BY_CASE[case_id]
        log_path = ROOT / "fixtures" / "logs" / case_id / "incident.log"
        verification_path = (
            ROOT / "fixtures" / "verification" / f"{case_id}.json"
        )

        parsed = LogParser().parse(log_path)
        index = TreeSitterJavaIndex()
        index.index(repo)
        backend = load_verification_data(verification_path)
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
            verification_backend=backend,
        )
        result = runtime.run(
            parsed,
            index,
            "order-service",
            provider,
            Budget(
                max_iterations=16,
                max_llm_calls=18,
                max_tool_calls=24,
                max_hypotheses=4,
            ),
        )
        report = build_report(result, parsed, repo)
        return LiveRun(
            case_id=case_id,
            expected=expected,
            result=result,
            report=report,
        )
    except Exception as exc:  # keep live failures bounded and observable
        message = f"{type(exc).__name__}: {exc}"
        for env_name in ("DEEPSEEK_API_KEY",):
            secret = os.environ.get(env_name, "")
            if secret:
                message = message.replace(secret, "***")
        return LiveRun(case_id=case_id, expected=expected, error=message)


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
    return [by_id[evidence_id] for evidence_id in ids if evidence_id in by_id]


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


def _source_text(source: ReportSource) -> str:
    return " ".join([source.claim, *source.messages])


def _statement_matches(statement: str, expected: dict[str, Any]) -> bool:
    lowered = statement.lower()
    return any(
        keyword.lower() in lowered
        for keyword in expected["expected_top_cause_keywords"]
    )


def _hypothesis_refs(
    report: Report,
    hypothesis: ReportHypothesis,
) -> set[str]:
    return {
        source.source_ref
        for source in _hypothesis_sources(report, hypothesis)
    }


def _top_matches(run: LiveRun, hypothesis: ReportHypothesis) -> bool:
    assert run.report is not None
    if _statement_matches(hypothesis.statement, run.expected):
        return True
    marker = EXPECTED_MARKER[run.case_id]
    return any(marker in ref for ref in _hypothesis_refs(run.report, hypothesis))


def _require_run(case_id: str) -> LiveRun:
    run = _run_live(case_id)
    assert run.error is None, (
        f"{case_id}: live run failed: {run.error}"
    )
    assert run.result is not None and run.report is not None
    return run


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_live_case_report_is_grounded(case_id: str) -> None:
    """A live run must expose grounded context, code, DB, and remediation."""
    run = _require_run(case_id)
    report = run.report
    result = run.result
    assert report is not None and result is not None
    assert report.schema_version == "0.4"
    assert report.status in {"confirmed", "probable"}, (
        f"{case_id}: live status was {report.status!r}"
    )
    assert report.hypotheses, f"{case_id}: no hypotheses were proposed"
    top = report.hypotheses[0]

    marker = EXPECTED_MARKER[case_id]
    all_refs = {
        source.source_ref for source in report.sources
    }
    assert any(marker in ref for ref in all_refs), (
        f"{case_id}: no hypothesis cited expected evidence {marker!r}; "
        f"refs={sorted(all_refs)}"
    )

    context_sources = [
        source
        for source in _hypothesis_sources(report, top)
        if source.kind == "log_thread_context"
    ]
    assert context_sources, (
        f"{case_id}: Top-1 has no assessed same-thread context"
    )
    assert all(
        source.thread == run.expected["expected_thread"]
        for source in context_sources
    ), (
        f"{case_id}: context threads were "
        f"{[source.thread for source in context_sources]}"
    )
    context_text = " ".join(
        _source_text(source) for source in context_sources
    )
    for message in run.expected["expected_thread_context_messages"]:
        assert message in context_text, (
            f"{case_id}: context missing {message!r}"
        )
    for forbidden in run.expected["forbidden_thread_context_markers"]:
        assert forbidden not in context_text, (
            f"{case_id}: context contains cross-thread marker {forbidden!r}"
        )

    kinds = _satisfied_kinds(report, top)
    assert "log_thread_context" in kinds, (
        f"{case_id}: Top-1 has no satisfied context requirement"
    )
    assert kinds & CODE_KINDS, (
        f"{case_id}: Top-1 has no satisfied code-flow evidence"
    )
    if report.status == "confirmed":
        assert all(
            requirement.satisfied for requirement in top.requirements
        ), f"{case_id}: confirmed without full requirement coverage"
    else:
        assert any(
            requirement.satisfied for requirement in top.requirements
        ), f"{case_id}: probable without any satisfied requirement"

    assert report.remediation_plan, f"{case_id}: no remediation plan"
    source_ids = {source.evidence_id for source in report.sources}
    for action in report.remediation_plan:
        assert action.evidence_ids, (
            f"{case_id}: action {action.action_id} has no evidence binding"
        )
        assert set(action.evidence_ids) <= source_ids, (
            f"{case_id}: action cites an unknown evidence item"
        )

    for flag in _VALIDATION_FLAGS:
        assert getattr(report.validation, flag), (
            f"{case_id}: validation flag {flag} is false: "
            f"{report.validation.errors}"
        )

    assert report.verification.environment == "fixture"
    assert report.verification.backend == "fake"
    assert report.verification.note

    assert result.llm_usage.calls > 0
    assert result.llm_calls
    assert {record.provider for record in result.llm_calls} == {"deepseek"}
    assert {record.model for record in result.llm_calls} == {
        _model_for_live()
    }

    serialized = report.model_dump_json()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    assert api_key
    assert api_key not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized
    assert "sk-" not in serialized

    print(
        "LIVE_CASE "
        f"case={case_id} status={report.status} "
        f"top={top.hypothesis_id}/{top.status} "
        f"llm_calls={result.llm_usage.calls} "
        f"tokens={result.llm_usage.total_tokens} "
        f"latency_ms={result.llm_usage.latency_ms} "
        f"tool_calls={len(result.tool_calls)} "
        f"stop={result.stop_reason.value}"
    )


def _model_for_live() -> str:
    return resolve_settings(max_tokens=2000).model


def test_live_top1_and_top3_metrics() -> None:
    """Record Top-1/Top-3 across all three live runs without fake PASS."""
    runs = [_require_run(case_id) for case_id in CASE_IDS]
    top1 = 0
    top3 = 0
    lines: list[str] = []
    for run in runs:
        report = run.report
        assert report is not None
        hits = [
            _top_matches(run, hypothesis)
            for hypothesis in report.hypotheses[:3]
        ]
        top1 += int(bool(hits and hits[0]))
        top3 += int(any(hits))
        lines.append(
            f"{run.case_id}: status={report.status} "
            f"top1={bool(hits and hits[0])} top3={any(hits)}"
        )
    print("LIVE_METRICS\n" + "\n".join(lines))
    assert top1 >= 2, (
        f"live Top-1 target is >=2/3; got {top1}/3\n" + "\n".join(lines)
    )
    assert top3 == 3, (
        f"live Top-3 target is 3/3; got {top3}/3\n" + "\n".join(lines)
    )
