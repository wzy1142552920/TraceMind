"""Unit tests for the v0.3 evidence ledger."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
)
from tracemind.diagnosis.ledger import EvidenceLedger, InvalidBindingError


def _evidence(
    evidence_id: str = "ev_0001",
    *,
    kind: EvidenceKind = EvidenceKind.LOG_EVENT,
    source_ref: str = "log://evt_0001",
    content: dict[str, object] | None = None,
    tool_call_id: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        kind=kind,
        claim=f"{kind.value} evidence",
        source_ref=source_ref,
        provenance=EvidenceProvenance.LOG_PARSER,
        tool_call_id=tool_call_id,
        observed_at="2026-10-22T00:00:00+00:00",
        content=content or {},
    )


def test_add_get_all_and_source_ref_lookup() -> None:
    ledger = EvidenceLedger()
    first = ledger.add(_evidence())
    second = ledger.add(
        _evidence(
            "ev_0002",
            kind=EvidenceKind.SOURCE_CODE,
            source_ref="repo://OrderService.java#L17-L27",
        )
    )

    assert ledger.get("ev_0001") is first
    assert ledger.get("ev_0002") is second
    assert ledger.get("ev_9999") is None
    assert ledger.all() == [first, second]
    assert ledger.by_source_ref("log://evt_0001") == [first]
    assert ledger.by_source_ref("repo://OrderService.java#L17-L27") == [second]
    assert ledger.by_source_ref("repo://missing.java#L1-L2") == []


def test_same_kind_and_source_ref_is_deduplicated() -> None:
    ledger = EvidenceLedger()
    first = ledger.add(_evidence())
    duplicate = ledger.add(_evidence("ev_0002"))

    assert duplicate is first
    assert len(ledger) == 1
    assert [item.evidence_id for item in ledger.all()] == ["ev_0001"]


def test_different_kinds_with_same_source_ref_are_kept() -> None:
    ledger = EvidenceLedger()
    ledger.add(_evidence())
    ledger.add(
        _evidence(
            "ev_0002",
            kind=EvidenceKind.STACK_FRAME,
        )
    )

    assert len(ledger) == 2
    assert len(ledger.by_source_ref("log://evt_0001")) == 2


def test_bind_upgrades_unbound_evidence_and_records_tool_call() -> None:
    ledger = EvidenceLedger()
    ledger.add(_evidence())

    bound = ledger.bind(
        "ev_0001",
        "hyp_001",
        "hyp_001_req_01",
        tool_call_id="call_1",
    )

    assert bound.bound_hypothesis_id == "hyp_001"
    assert bound.bound_requirement_id == "hyp_001_req_01"
    assert bound.tool_call_id == "call_1"
    assert ledger.by_requirement("hyp_001", "hyp_001_req_01") == [bound]


def test_rebind_same_target_is_idempotent_and_keeps_first_tool_call() -> None:
    ledger = EvidenceLedger()
    ledger.add(_evidence())

    ledger.bind("ev_0001", "hyp_001", "hyp_001_req_01", "call_1")
    rebound = ledger.bind(
        "ev_0001",
        "hyp_001",
        "hyp_001_req_01",
        "call_2",
    )

    assert rebound.tool_call_id == "call_1"
    assert len(ledger) == 1


def test_same_fact_can_be_bound_to_multiple_requirements() -> None:
    ledger = EvidenceLedger()
    ledger.add(_evidence())
    ledger.bind("ev_0001", "hyp_001", "hyp_001_req_01", "call_1")
    rebound = ledger.bind(
        "ev_0001",
        "hyp_002",
        "hyp_002_req_01",
        "call_2",
    )

    assert rebound.has_binding("hyp_001", "hyp_001_req_01")
    assert rebound.has_binding("hyp_002", "hyp_002_req_01")
    assert rebound.bound_hypothesis_id == "hyp_001"
    assert rebound.bound_requirement_id == "hyp_001_req_01"
    assert rebound.tool_call_id == "call_1"
    assert ledger.by_requirement("hyp_001", "hyp_001_req_01") == [rebound]
    assert ledger.by_requirement("hyp_002", "hyp_002_req_01") == [rebound]
    assert len(ledger) == 1


def test_bind_missing_evidence_is_rejected() -> None:
    with pytest.raises(InvalidBindingError):
        EvidenceLedger().bind("ev_9999", "hyp_001", "hyp_001_req_01")


def test_bind_requires_both_hypothesis_and_requirement() -> None:
    ledger = EvidenceLedger()
    ledger.add(_evidence())

    with pytest.raises(InvalidBindingError):
        ledger.bind("ev_0001", "hyp_001", "")


def test_bound_requirement_requires_hypothesis() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev_0001",
            kind=EvidenceKind.LOG_EVENT,
            claim="bad binding",
            source_ref="log://evt_0001",
            provenance=EvidenceProvenance.LOG_PARSER,
            observed_at="2026-10-22T00:00:00+00:00",
            bound_requirement_id="hyp_001_req_01",
        )


def test_independence_group_defaults_to_kind_and_source_ref() -> None:
    evidence = _evidence()

    assert evidence.independence_group == "log_event:log://evt_0001"


def test_large_content_is_truncated_with_marker() -> None:
    ledger = EvidenceLedger(max_content_bytes=64)
    evidence = ledger.add(
        _evidence(content={"text": "x" * 500, "nested": {"a": 1}})
    )

    assert evidence.content["truncated"] is True
    assert evidence.content["original_bytes"] > 64
    assert isinstance(evidence.content["preview"], str)
    assert len(evidence.content["preview"].encode("utf-8")) <= 64
