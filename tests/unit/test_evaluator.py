"""Unit tests for deterministic evidence coverage evaluation."""

from __future__ import annotations

from tracemind.diagnosis.evaluator import evaluate
from tracemind.diagnosis.evidence import Evidence, Hypothesis


def _evidence(
    evidence_id: str,
    kind: str,
    supports: list[str] | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind} evidence",
        source_ref=f"log://{evidence_id}",
        supports=supports or ["hyp_001"],
        strength="strong",
        created_at="2026-10-21T00:00:00+00:00",
    )


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis_id="hyp_001",
        statement="Exception originates in OrderService.updateStatus",
        status="candidate",
    )


def test_candidate_without_evidence() -> None:
    hypothesis = evaluate(_hypothesis(), [])

    assert hypothesis.status == "candidate"
    assert hypothesis.evidence_ids == []
    assert hypothesis.missing_evidence == ["log_event", "source_code", "stack_frame"]


def test_supported_when_source_code_missing() -> None:
    evidence = [
        _evidence("ev_0001", "stack_frame"),
        _evidence("ev_0002", "log_event"),
    ]

    hypothesis = evaluate(_hypothesis(), evidence)

    assert hypothesis.status == "supported"
    assert hypothesis.evidence_ids == ["ev_0001", "ev_0002"]
    assert hypothesis.missing_evidence == ["source_code"]


def test_confirmed_when_all_required_kinds_present() -> None:
    evidence = [
        _evidence("ev_0001", "stack_frame"),
        _evidence("ev_0002", "log_event"),
        _evidence("ev_0003", "source_code"),
    ]

    hypothesis = evaluate(_hypothesis(), evidence)

    assert hypothesis.status == "confirmed"
    assert hypothesis.missing_evidence == []
    assert hypothesis.evidence_ids == ["ev_0001", "ev_0002", "ev_0003"]


def test_evidence_for_other_hypothesis_is_ignored() -> None:
    evidence = [
        _evidence("ev_0001", "source_code", supports=["hyp_999"]),
    ]

    hypothesis = evaluate(_hypothesis(), evidence)

    assert hypothesis.status == "candidate"
    assert hypothesis.evidence_ids == []
