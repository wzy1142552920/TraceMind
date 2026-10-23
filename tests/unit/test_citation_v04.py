"""Unit tests for artifact citation validation in report 0.4."""

from __future__ import annotations

from pathlib import Path

import pytest
from report_v04_helpers import (
    REPO_SOURCE_REF,
    artifact_record,
    evidence,
    run_with,
)

from tracemind.artifacts import ArtifactRecord
from tracemind.diagnosis.evidence import EvidenceKind
from tracemind.diagnosis.report import build_report, validate_report
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


def _artifact() -> ArtifactRecord:
    return artifact_record(
        "thread-cpu",
        "thread_cpu",
        line_count=5,
    )


def _report(source_ref: str, artifacts: list[ArtifactRecord] | None = None):
    records = [_artifact()] if artifacts is None else artifacts
    result = run_with(
        [evidence("ev_0001", EvidenceKind.THREAD_CPU, source_ref)],
        artifacts=records,
    )
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(result, parsed, REPO_FIXTURE)
    return report, result, parsed


@pytest.mark.parametrize(
    "source_ref",
    [
        "artifact://thread-cpu#L2-L3",
        "artifact://thread-cpu#L3",
        "artifact://thread-cpu#L5-L5",
    ],
)
def test_valid_artifact_references(source_ref: str) -> None:
    report, _, _ = _report(source_ref)

    assert report.validation.citations_valid is True
    assert report.validation.artifact_citations_valid is True
    assert report.sources[0].verified is True
    assert report.status == "confirmed"


@pytest.mark.parametrize(
    ("source_ref", "error_fragment"),
    [
        ("artifact://missing#L1-L2", "artifact id does not exist"),
        ("artifact://thread-cpu#L2-L9", "line range exceeds file length"),
        ("artifact://thread-cpu#L4-L2", "invalid line range"),
        ("artifact://thread-cpu#L0", "invalid line range"),
        ("artifact://thread-cpu", "malformed artifact reference"),
    ],
)
def test_invalid_artifact_references(
    source_ref: str,
    error_fragment: str,
) -> None:
    report, _, _ = _report(source_ref)

    assert report.validation.citations_valid is False
    assert report.validation.artifact_citations_valid is False
    assert report.sources[0].verified is False
    assert report.status == "insufficient_data"
    assert any(
        error_fragment in error for error in report.validation.errors
    )


def test_artifact_reference_requires_loaded_artifacts() -> None:
    report, _, _ = _report(
        "artifact://thread-cpu#L1-L2",
        artifacts=[],
    )

    assert report.validation.citations_valid is False
    assert report.validation.artifact_citations_valid is False
    assert any(
        "artifact id does not exist" in error
        for error in report.validation.errors
    )


def test_other_schemes_still_validate_with_artifacts_present() -> None:
    result = run_with(
        [
            evidence(
                "ev_0001",
                EvidenceKind.SOURCE_CODE,
                REPO_SOURCE_REF,
            )
        ],
        artifacts=[_artifact()],
    )
    parsed = LogParser().parse(LOG_FIXTURE)
    report = build_report(result, parsed, REPO_FIXTURE)

    assert report.validation.citations_valid is True
    assert report.validation.artifact_citations_valid is True
    assert report.sources[0].verified is True

    report.sources[0].source_ref = (
        "repo://src/main/java/com/example/order/OrderService.java#L1-L9999"
    )
    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.citations_valid is False
    assert report.validation.artifact_citations_valid is True
    assert any(
        "line range exceeds file length" in error
        for error in report.validation.errors
    )


def test_artifact_error_reference_is_truncated() -> None:
    report, result, parsed = _report("artifact://thread-cpu#L1-L2")
    report.sources[0].source_ref = "artifact://" + ("x" * 300) + "#L1"

    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.artifact_citations_valid is False
    assert any(
        "malformed artifact reference" in error
        for error in report.validation.errors
    )
    assert all(
        ("x" * 201) not in error for error in report.validation.errors
    )
