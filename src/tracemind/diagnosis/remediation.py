"""Grounded structured remediation validation for v0.3 reports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceAssessment,
    Hypothesis,
    HypothesisStatus,
    RemediationAction,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.verification import VerificationTargetError
from tracemind.workspace.paths import resolve_under_root

if TYPE_CHECKING:
    from tracemind.verification import ReadOnlyVerificationBackend

ActionType = Literal["code", "config", "data", "ops", "test"]

ALLOWED_TYPES = frozenset({"code", "config", "data", "ops", "test"})
MAX_ACTIONS = 8
MAX_ACTIONS_PER_HYPOTHESIS = 3
MAX_EVIDENCE_PER_ACTION = 8
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RemediationActionProposal(BaseModel):
    """An LLM-authored remediation action before runtime validation."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    type: str
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_source_refs: list[str] = Field(default_factory=list)
    target: str
    risk: str
    prerequisites: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)


class RemediationProposal(BaseModel):
    """Batch payload for ``diagnosis.propose_remediation``."""

    model_config = ConfigDict(extra="forbid")

    actions: list[RemediationActionProposal] = Field(default_factory=list)


class RemediationError(ValueError):
    """One remediation action failed deterministic validation."""


def validate_action(
    proposal: RemediationActionProposal,
    *,
    action_id: str,
    hypothesis: Hypothesis | None,
    ledger: EvidenceLedger,
    allowed_evidence_ids: set[str],
    repo_root: Path | None,
    verification_backend: ReadOnlyVerificationBackend | None,
) -> RemediationAction:
    """Validate one action or raise ``RemediationError`` with a safe reason."""
    if hypothesis is None:
        raise RemediationError(
            f"hypothesis does not exist: {proposal.hypothesis_id.strip()}"
        )
    if hypothesis.status not in {
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.CONFIRMED,
    }:
        raise RemediationError(
            f"hypothesis {hypothesis.hypothesis_id} is "
            f"{hypothesis.status.value}; remediation requires supported/confirmed"
        )

    action_type = _normalize_type(proposal.type)
    title = _required_text(proposal.title, "title", 120)
    description = _required_text(proposal.description, "description", 1000)
    risk = _required_text(proposal.risk, "risk", 300)
    target = _validate_target(
        action_type,
        _required_text(proposal.target, "target", 300),
        repo_root,
        verification_backend,
    )
    prerequisites = _text_list(
        proposal.prerequisites,
        "prerequisites",
        limit=300,
    )
    verification_steps = _text_list(
        proposal.verification_steps,
        "verification_steps",
        limit=300,
    )
    evidence_ids = _resolve_evidence(
        proposal,
        ledger=ledger,
        allowed_evidence_ids=allowed_evidence_ids,
    )

    return RemediationAction(
        action_id=action_id,
        hypothesis_id=hypothesis.hypothesis_id,
        type=action_type,
        title=title,
        description=description,
        evidence_ids=evidence_ids,
        target=target,
        risk=risk,
        prerequisites=prerequisites,
        verification_steps=verification_steps,
    )


def allowed_evidence_for(
    hypothesis: Hypothesis,
    assessments: list[EvidenceAssessment],
    ledger_evidence: list[Evidence] | None = None,
) -> set[str]:
    """Return facts grounded in this hypothesis's basis, bindings, or assessments."""
    allowed = set(hypothesis.basis_evidence_ids)
    allowed.update(hypothesis.evidence_ids)
    for assessment in assessments:
        if assessment.hypothesis_id == hypothesis.hypothesis_id:
            allowed.add(assessment.evidence_id)
    for item in ledger_evidence or []:
        if item.is_bound_to(hypothesis.hypothesis_id):
            allowed.add(item.evidence_id)
    return allowed


def _normalize_type(value: str) -> ActionType:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_TYPES:
        raise RemediationError(
            f"type must be one of {sorted(ALLOWED_TYPES)}"
        )
    return cast(ActionType, normalized)


def _required_text(value: str, field: str, limit: int) -> str:
    stripped = value.strip()
    if not stripped:
        raise RemediationError(f"{field} must not be blank")
    if len(stripped) > limit:
        raise RemediationError(
            f"{field} must be at most {limit} characters"
        )
    return stripped


def _text_list(values: list[str], field: str, *, limit: int) -> list[str]:
    if len(values) > 5:
        raise RemediationError(f"{field} must contain at most 5 items")
    return [_required_text(value, field, limit) for value in values]


def _validate_target(
    action_type: ActionType,
    target: str,
    repo_root: Path | None,
    verification_backend: ReadOnlyVerificationBackend | None,
) -> str:
    if action_type == "code":
        file_path = target.split("#", 1)[0].strip()
        if not file_path:
            raise RemediationError("code target must name a repository file")
        if repo_root is None:
            raise RemediationError("code target cannot be verified without a repo")
        try:
            resolved = resolve_under_root(repo_root, file_path)
        except ValueError as exc:
            raise RemediationError(f"code target is outside the repo: {exc}") from exc
        if not resolved.is_file():
            raise RemediationError(
                f"code target does not exist: {file_path}"
            )
        return target

    if action_type == "data":
        if verification_backend is None:
            raise RemediationError(
                "data target requires a read-only verification backend"
            )
        table = target.removeprefix("db://").split("#", 1)[0].split("/", 1)[0]
        if _TABLE_RE.fullmatch(table) is None:
            raise RemediationError(
                "data target must be a whitelisted table identifier"
            )
        try:
            verification_backend.describe_table(table)
        except VerificationTargetError as exc:
            raise RemediationError(f"data target is not whitelisted: {exc}") from exc
        return target

    return target


def _resolve_evidence(
    proposal: RemediationActionProposal,
    *,
    ledger: EvidenceLedger,
    allowed_evidence_ids: set[str],
) -> list[str]:
    resolved: list[str] = []
    for evidence_id in proposal.evidence_ids:
        evidence = _require_evidence(
            evidence_id,
            ledger=ledger,
            allowed_evidence_ids=allowed_evidence_ids,
        )
        resolved.append(evidence.evidence_id)

    for source_ref in proposal.evidence_source_refs:
        reference = source_ref.strip()
        if not reference:
            raise RemediationError("evidence_source_refs must not contain blanks")
        matches = [
            evidence
            for evidence in ledger.by_source_ref(reference)
            if evidence.evidence_id in allowed_evidence_ids
        ]
        if not matches:
            known = ledger.by_source_ref(reference)
            if known:
                raise RemediationError(
                    f"source_ref is not associated with the hypothesis: {reference}"
                )
            raise RemediationError(
                f"source_ref does not resolve: {reference}"
            )
        resolved.extend(evidence.evidence_id for evidence in matches)

    deduped = list(dict.fromkeys(resolved))
    if not deduped:
        raise RemediationError(
            "each action needs at least one grounded evidence ID or source_ref"
        )
    if len(deduped) > MAX_EVIDENCE_PER_ACTION:
        raise RemediationError(
            f"an action may cite at most {MAX_EVIDENCE_PER_ACTION} evidence items"
        )
    return deduped


def _require_evidence(
    evidence_id: str,
    *,
    ledger: EvidenceLedger,
    allowed_evidence_ids: set[str],
) -> Evidence:
    normalized = evidence_id.strip()
    if not normalized:
        raise RemediationError("evidence_ids must not contain blanks")
    evidence = ledger.get(normalized)
    if evidence is None:
        raise RemediationError(f"evidence does not exist: {normalized}")
    if evidence.evidence_id not in allowed_evidence_ids:
        raise RemediationError(
            f"evidence is not associated with the hypothesis: {normalized}"
        )
    return evidence
