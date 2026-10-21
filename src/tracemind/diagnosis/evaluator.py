"""Deterministic evidence-coverage evaluation for v0.1."""

from __future__ import annotations

from tracemind.diagnosis.evidence import Evidence, Hypothesis

REQUIRED_EVIDENCE = frozenset({"stack_frame", "log_event", "source_code"})


def evaluate(hypothesis: Hypothesis, evidence: list[Evidence]) -> Hypothesis:
    """Update a hypothesis status from supporting evidence kinds."""
    relevant = [
        item for item in evidence if hypothesis.hypothesis_id in item.supports
    ]
    hypothesis.evidence_ids = [item.evidence_id for item in relevant]
    present = {item.kind for item in relevant}
    hypothesis.missing_evidence = sorted(REQUIRED_EVIDENCE - present)

    if REQUIRED_EVIDENCE <= present:
        hypothesis.status = "confirmed"
    elif relevant:
        hypothesis.status = "supported"
    else:
        hypothesis.status = "candidate"
    return hypothesis
