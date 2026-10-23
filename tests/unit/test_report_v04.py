"""Unit tests for the v0.4 report schema and JVM artifact metadata."""

from __future__ import annotations

from pathlib import Path

from report_v04_helpers import (
    LOG_EVENT_REF,
    REPO_SOURCE_REF,
    artifact_record,
    evidence,
    run_with,
)

from tracemind.diagnosis.evidence import (
    EvidenceKind,
    EvidenceProvenance,
    HypothesisStatus,
)
from tracemind.diagnosis.report import (
    JVM_BINARY_LIMITATION,
    JVM_ONLY_LIMITATION,
    JVM_SNAPSHOT_LIMITATION,
    SAME_THREAD_OPTIONAL_LIMITATION,
    build_report,
    render_markdown,
    validate_report,
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
CPU_REF = "artifact://thread-cpu#L4"
GC_REF = "artifact://gc-log#L1-L2"


def _parsed():
    return LogParser().parse(LOG_FIXTURE)


def _artifacts():
    return [
        artifact_record("thread-cpu", "thread_cpu", line_count=6),
        artifact_record("gc-log", "gc_log", line_count=2),
        artifact_record("heap-histo", "heap_histogram", line_count=4),
    ]


def _jvm_evidence() -> list:
    return [
        evidence(
            "ev_0001",
            EvidenceKind.THREAD_CPU,
            CPU_REF,
            content={"tid_decimal": 6700, "cpu_percent": 92.3},
        ),
        evidence(
            "ev_0002",
            EvidenceKind.SOURCE_CODE,
            REPO_SOURCE_REF,
            provenance=EvidenceProvenance.TOOL,
        ),
        evidence("ev_0003", EvidenceKind.GC_SUMMARY, GC_REF),
    ]


def test_report_has_schema_artifacts_and_artifact_sources() -> None:
    report = build_report(
        run_with(_jvm_evidence(), artifacts=_artifacts()),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.schema_version == "0.4"
    assert report.status == "confirmed"
    assert [item.artifact_id for item in report.artifacts] == [
        "thread-cpu",
        "gc-log",
        "heap-histo",
    ]
    assert [item.kind for item in report.artifacts] == [
        "thread_cpu",
        "gc_log",
        "heap_histogram",
    ]
    assert all(
        item.source_environment == "user_provided"
        for item in report.artifacts
    )
    assert [item.source_name for item in report.artifacts] == [
        "thread-cpu.txt",
        "gc-log.txt",
        "heap-histo.txt",
    ]
    assert report.validation.citations_valid is True
    assert report.validation.artifact_citations_valid is True
    assert report.validation.artifacts_labeled is True

    artifact_sources = [
        source
        for source in report.sources
        if source.category == "artifact"
    ]
    assert {source.source_ref for source in artifact_sources} == {
        CPU_REF,
        GC_REF,
    }
    assert all(source.verified for source in artifact_sources)


def test_artifact_warnings_are_bounded() -> None:
    warnings = ["x" * 400, *(f"warning {index}" for index in range(12))]
    record = artifact_record(
        "thread-cpu",
        "thread_cpu",
        line_count=6,
        truncated=True,
        warnings=warnings,
    )

    report = build_report(
        run_with([_jvm_evidence()[0]], artifacts=[record]),
        _parsed(),
        REPO_FIXTURE,
    )

    artifact = report.artifacts[0]
    assert artifact.truncated is True
    assert len(artifact.warnings) == 10
    assert all(len(item) <= 256 for item in artifact.warnings)
    assert artifact.warnings[0].endswith("…")
    assert artifact.warnings[1] == "warning 0"


def test_artifact_source_name_is_reduced_to_basename() -> None:
    record = artifact_record(
        "thread-cpu",
        "thread_cpu",
        source_name="/tmp/private/thread-cpu.txt",
        line_count=6,
    )

    report = build_report(
        run_with([_jvm_evidence()[0]], artifacts=[record]),
        _parsed(),
        REPO_FIXTURE,
    )

    assert report.artifacts[0].source_name == "thread-cpu.txt"
    payload = report.model_dump_json()
    markdown = render_markdown(report)
    assert "/tmp/private" not in payload
    assert "/tmp/private" not in markdown
    assert str(Path("/tmp/private")) not in markdown


def test_no_artifacts_keeps_schema_and_omits_jvm_limitations() -> None:
    result = run_with(
        [
            evidence(
                "ev_0001",
                EvidenceKind.LOG_EVENT,
                LOG_EVENT_REF,
                provenance=EvidenceProvenance.LOG_PARSER,
            ),
            evidence(
                "ev_0002",
                EvidenceKind.SOURCE_CODE,
                REPO_SOURCE_REF,
                provenance=EvidenceProvenance.TOOL,
            ),
        ]
    )

    report = build_report(result, _parsed(), REPO_FIXTURE)

    assert report.schema_version == "0.4"
    assert report.artifacts == []
    assert report.validation.artifact_citations_valid is True
    assert report.validation.artifacts_labeled is True
    for limitation in (
        JVM_SNAPSHOT_LIMITATION,
        JVM_BINARY_LIMITATION,
        SAME_THREAD_OPTIONAL_LIMITATION,
        JVM_ONLY_LIMITATION,
    ):
        assert limitation not in report.limitations
    assert "## JVM 快照" not in render_markdown(report)


def test_jvm_limitations_are_added_once() -> None:
    result = run_with(
        _jvm_evidence(),
        artifacts=_artifacts(),
        limitations=[
            JVM_SNAPSHOT_LIMITATION,
            SAME_THREAD_OPTIONAL_LIMITATION,
        ],
    )

    report = build_report(result, _parsed(), REPO_FIXTURE)

    assert report.limitations.count(JVM_SNAPSHOT_LIMITATION) == 1
    assert report.limitations.count(SAME_THREAD_OPTIONAL_LIMITATION) == 1
    assert report.limitations.count(JVM_BINARY_LIMITATION) == 1
    assert JVM_ONLY_LIMITATION not in report.limitations

    markdown = render_markdown(report)
    assert "## JVM 快照" in markdown
    assert "### JVM 快照证据" in markdown
    assert CPU_REF in markdown
    assert "thread-cpu.txt" in markdown
    assert "Full thread dump" not in markdown


def test_jvm_only_candidate_gets_no_mechanism_limitation() -> None:
    result = run_with(
        [evidence("ev_0001", EvidenceKind.THREAD_CPU, CPU_REF)],
        artifacts=[artifact_record("thread-cpu", "thread_cpu", line_count=6)],
        status=HypothesisStatus.SUPPORTED,
    )

    report = build_report(result, _parsed(), REPO_FIXTURE)

    assert report.status == "probable"
    assert JVM_ONLY_LIMITATION in report.limitations
    assert JVM_ONLY_LIMITATION in render_markdown(report)


def test_mechanism_evidence_removes_no_mechanism_limitation() -> None:
    result = run_with(
        [
            evidence("ev_0001", EvidenceKind.THREAD_CPU, CPU_REF),
            evidence(
                "ev_0002",
                EvidenceKind.SOURCE_CODE,
                REPO_SOURCE_REF,
                provenance=EvidenceProvenance.TOOL,
            ),
        ],
        artifacts=[artifact_record("thread-cpu", "thread_cpu", line_count=6)],
        status=HypothesisStatus.CONFIRMED,
    )

    report = build_report(result, _parsed(), REPO_FIXTURE)

    assert JVM_ONLY_LIMITATION not in report.limitations


def test_artifacts_labeled_rejects_a_live_label() -> None:
    result = run_with(_jvm_evidence(), artifacts=_artifacts())
    parsed = _parsed()
    report = build_report(result, parsed, REPO_FIXTURE)
    report.artifacts[0].source_environment = "live"

    validate_report(report, result, parsed, REPO_FIXTURE)

    assert report.validation.artifacts_labeled is False
    assert report.validation.artifact_citations_valid is True
    assert report.validation.citations_valid is True
    assert report.status == "confirmed"
    assert any(
        "not labeled as user_provided" in error
        for error in report.validation.errors
    )
