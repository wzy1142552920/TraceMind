"""Shared fixtures and assertions for the v0.3 case evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from tracemind.artifacts import ArtifactBundle, load_artifacts
from tracemind.diagnosis.evidence import RunResult
from tracemind.diagnosis.report import (
    Report,
    ReportHypothesis,
    ReportSource,
    build_report,
)
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.mock import MockProvider
from tracemind.log_analysis.parser import LogParser
from tracemind.verification import load_verification_data

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
CODE_KINDS = frozenset({"source_code", "call_path", "sql", "annotation", "config"})
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
JVM_CASE_IDS = (
    "v04-j1-cpu-high",
    "v04-j2-memory-oom",
)
JVM_REPO_BY_CASE = {
    "v04-j1-cpu-high": "v04-jvm-hot-loop",
    "v04-j2-memory-oom": "v04-jvm-unbounded-cache",
}
JVM_SERVICE = "order-service"


@dataclass(frozen=True)
class CaseFixture:
    """Filesystem locations for one synthetic incident case."""

    case_id: str
    repo_name: str
    log_path: Path
    repo_path: Path
    verification_path: Path
    mock_path: Path
    expected_path: Path


@dataclass(frozen=True)
class CaseRun:
    """One deterministic offline diagnosis run for a case."""

    fixture: CaseFixture
    expected: dict[str, Any]
    result: RunResult
    report: Report


@dataclass(frozen=True)
class JvmCaseFixture:
    """Filesystem locations for one synthetic JVM incident case."""

    case_id: str
    repo_name: str
    service: str
    log_path: Path
    repo_path: Path
    artifacts_path: Path
    mock_path: Path
    expected_path: Path


@dataclass(frozen=True)
class JvmCaseRun:
    """One deterministic offline JVM diagnosis run."""

    fixture: JvmCaseFixture
    expected: dict[str, Any]
    artifacts: ArtifactBundle
    result: RunResult
    report: Report


def case_fixture(case_id: str) -> CaseFixture:
    """Resolve all fixture paths for a case id."""
    repo_name = REPO_BY_CASE[case_id]
    return CaseFixture(
        case_id=case_id,
        repo_name=repo_name,
        log_path=FIXTURES / "logs" / case_id / "incident.log",
        repo_path=FIXTURES / "repos" / repo_name,
        verification_path=FIXTURES / "verification" / f"{case_id}.json",
        mock_path=FIXTURES / "mock" / f"{case_id}.json",
        expected_path=FIXTURES / "expected" / f"{case_id}.yaml",
    )


@cache
def load_expected(case_id: str) -> dict[str, Any]:
    """Load the expected-answer document for a case."""
    path = case_fixture(case_id).expected_path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_mock_script(case_id: str) -> dict[str, Any]:
    """Load a mock response script as mutable JSON data."""
    return json.loads(
        case_fixture(case_id).mock_path.read_text(encoding="utf-8")
    )


@cache
def run_case(case_id: str) -> CaseRun:
    """Run one case offline through the real runtime and report builder."""
    fixture = case_fixture(case_id)
    parsed = LogParser().parse(fixture.log_path)
    index = TreeSitterJavaIndex()
    index.index(fixture.repo_path)
    backend = load_verification_data(fixture.verification_path)
    provider = MockProvider.from_script(fixture.mock_path)
    runtime = DiagnosisRuntime(
        repo_root=fixture.repo_path,
        provider_name="mock",
        model="v03-case",
        verification_backend=backend,
    )
    result = runtime.run(parsed, index, "order-service", provider)
    report = build_report(result, parsed, fixture.repo_path)
    return CaseRun(
        fixture=fixture,
        expected=load_expected(case_id),
        result=result,
        report=report,
    )


def jvm_case_fixture(case_id: str) -> JvmCaseFixture:
    """Resolve all fixture paths for a JVM case id."""
    repo_name = JVM_REPO_BY_CASE[case_id]
    return JvmCaseFixture(
        case_id=case_id,
        repo_name=repo_name,
        service=JVM_SERVICE,
        log_path=FIXTURES / "logs" / case_id / "incident.log",
        repo_path=FIXTURES / "repos" / repo_name,
        artifacts_path=FIXTURES / "artifacts" / case_id,
        mock_path=FIXTURES / "mock" / f"{case_id}.json",
        expected_path=FIXTURES / "expected" / f"{case_id}.yaml",
    )


@cache
def load_jvm_expected(case_id: str) -> dict[str, Any]:
    """Load the expected-answer document for a JVM case."""
    path = jvm_case_fixture(case_id).expected_path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def run_jvm_case(case_id: str) -> JvmCaseRun:
    """Run one JVM case offline through the real runtime and report builder."""
    fixture = jvm_case_fixture(case_id)
    parsed = LogParser().parse(fixture.log_path)
    index = TreeSitterJavaIndex()
    index.index(fixture.repo_path)
    artifacts = load_artifacts(fixture.artifacts_path, fixture.service)
    provider = MockProvider.from_script(fixture.mock_path)
    runtime = DiagnosisRuntime(
        repo_root=fixture.repo_path,
        provider_name="mock",
        model="v04-case",
        artifacts=artifacts,
    )
    result = runtime.run(
        parsed,
        index,
        fixture.service,
        provider,
    )
    report = build_report(result, parsed, fixture.repo_path)
    return JvmCaseRun(
        fixture=fixture,
        expected=load_jvm_expected(case_id),
        artifacts=artifacts,
        result=result,
        report=report,
    )


def top_hypothesis(report: Report) -> ReportHypothesis:
    """Return the highest-ranked report hypothesis."""
    return report.hypotheses[0]


def hypothesis_evidence_ids(hypothesis: ReportHypothesis) -> set[str]:
    """Collect every evidence id referenced by a report hypothesis."""
    ids = {
        *hypothesis.basis_evidence_ids,
        *hypothesis.supporting_evidence_ids,
        *hypothesis.refuting_evidence_ids,
    }
    for requirement in hypothesis.requirements:
        ids.update(requirement.supporting_evidence_ids)
        ids.update(requirement.refuting_evidence_ids)
    return ids


def sources_by_id(report: Report) -> dict[str, ReportSource]:
    """Index report sources by evidence id."""
    return {source.evidence_id: source for source in report.sources}


def hypothesis_sources(
    report: Report,
    hypothesis: ReportHypothesis,
) -> list[ReportSource]:
    """Return report sources referenced by one hypothesis."""
    indexed = sources_by_id(report)
    return [
        indexed[evidence_id]
        for evidence_id in hypothesis_evidence_ids(hypothesis)
        if evidence_id in indexed
    ]


def source_refs_for(
    report: Report,
    hypothesis: ReportHypothesis,
) -> set[str]:
    """Return source references that back one hypothesis."""
    return {source.source_ref for source in hypothesis_sources(report, hypothesis)}


def satisfied_kinds(
    report: Report,
    hypothesis: ReportHypothesis,
) -> set[str]:
    """Return evidence kinds that satisfy requirements of a hypothesis."""
    indexed = sources_by_id(report)
    kinds: set[str] = set()
    for requirement in hypothesis.requirements:
        if not requirement.satisfied:
            continue
        for evidence_id in requirement.supporting_evidence_ids:
            source = indexed.get(evidence_id)
            if source is not None:
                kinds.add(source.kind)
    return kinds


def expected_ref_is_present(expected_ref: str, actual_refs: set[str]) -> bool:
    """Match exact refs and repo refs with line suffixes."""
    if expected_ref in actual_refs:
        return True
    if expected_ref.startswith("repo://"):
        return any(ref.startswith(expected_ref + "#") for ref in actual_refs)
    return False


def source_text(source: ReportSource) -> str:
    """Flatten a source claim and same-thread messages for marker checks."""
    return " ".join([source.claim, *source.messages])


def keyword_matches(statement: str, keywords: list[str]) -> bool:
    """Return whether any expected keyword occurs in a statement."""
    lowered = statement.lower()
    return any(keyword.lower() in lowered for keyword in keywords)
