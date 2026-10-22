"""Runtime-owned hypothesis and assessment protocol for v0.3."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from tracemind.diagnosis.evaluator import evaluate_hypotheses
from tracemind.diagnosis.evidence import (
    AssessmentVerdict,
    EvaluationResult,
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceRequirement,
    Hypothesis,
    HypothesisStatus,
    RejectedRemediation,
    RemediationAction,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.diagnosis.remediation import (
    RemediationError,
    RemediationProposal,
    allowed_evidence_for,
    validate_action,
)

if TYPE_CHECKING:
    from tracemind.verification import ReadOnlyVerificationBackend


class ProtocolError(ValueError):
    """A stable, actionable hypothesis or assessment protocol failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _required_text(
    value: str,
    field: str,
    limit: int,
    code: str,
) -> str:
    stripped = value.strip()
    if not stripped:
        raise ProtocolError(code, f"{field} must not be blank")
    if len(stripped) > limit:
        raise ProtocolError(
            code,
            f"{field} must be at most {limit} characters",
        )
    return stripped


class RequirementProposal(BaseModel):
    """LLM-declared verification requirement before runtime ID assignment."""

    model_config = ConfigDict(extra="forbid")

    description: str
    evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    discriminating: bool
    suggested_tools: list[str] = Field(default_factory=list)


class HypothesisProposal(BaseModel):
    """LLM hypothesis payload; runtime-owned fields are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    cause_chain: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    basis_source_refs: list[str] = Field(default_factory=list)
    requirements: list[RequirementProposal] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)


class AssessmentProposal(BaseModel):
    """One LLM evidence assessment before runtime ID assignment."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    requirement_id: str
    evidence_id: str | None = None
    source_ref: str | None = None
    verdict: AssessmentVerdict
    rationale: str


class AssessmentsProposal(BaseModel):
    """Batch payload for ``diagnosis.assess_evidence``."""

    model_config = ConfigDict(extra="forbid")

    assessments: list[AssessmentProposal] = Field(default_factory=list)


class DiagnosisWorkspace:
    """Owns runtime IDs, grounding checks, and deterministic evaluation."""

    def __init__(
        self,
        ledger: EvidenceLedger | None = None,
        *,
        max_hypotheses: int = 6,
        max_requirements_per_hypothesis: int = 5,
        max_remediation_actions: int = 8,
        max_actions_per_hypothesis: int = 3,
        now: str | None = None,
    ) -> None:
        self.ledger = ledger if ledger is not None else EvidenceLedger()
        self.max_hypotheses = max_hypotheses
        self.max_requirements_per_hypothesis = max_requirements_per_hypothesis
        self.max_remediation_actions = max_remediation_actions
        self.max_actions_per_hypothesis = max_actions_per_hypothesis
        self.hypotheses: list[Hypothesis] = []
        self.assessments: list[EvidenceAssessment] = []
        self.remediation_actions: list[RemediationAction] = []
        self.rejected_remediations: list[RejectedRemediation] = []
        self._hypothesis_counter = 0
        self._assessment_counter = 0
        self._remediation_counter = 0
        self._now = now

    def propose_hypothesis(self, proposal: HypothesisProposal) -> dict[str, object]:
        """Validate and persist one LLM hypothesis with runtime-owned IDs."""
        if len(self.hypotheses) >= self.max_hypotheses:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                f"hypothesis limit reached: {self.max_hypotheses}",
            )
        statement = _required_text(
            proposal.statement,
            "statement",
            300,
            "HYPOTHESIS_NOT_GROUNDED",
        )
        if not 1 <= len(proposal.cause_chain) <= 5:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "cause_chain must contain 1-5 items",
            )
        cause_chain = [
            _required_text(
                item,
                "cause_chain item",
                200,
                "HYPOTHESIS_NOT_GROUNDED",
            )
            for item in proposal.cause_chain
        ]
        if not 1 <= len(proposal.falsifiers) <= 3:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "falsifiers must contain 1-3 items",
            )
        falsifiers = [
            _required_text(
                item,
                "falsifier",
                300,
                "HYPOTHESIS_NOT_GROUNDED",
            )
            for item in proposal.falsifiers
        ]
        if len(proposal.requirements) > self.max_requirements_per_hypothesis:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "requirements exceed per-hypothesis limit: "
                f"{self.max_requirements_per_hypothesis}",
            )
        if not proposal.requirements:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "at least one requirement is required",
            )
        for requirement in proposal.requirements:
            _required_text(
                requirement.description,
                "requirement description",
                300,
                "HYPOTHESIS_NOT_GROUNDED",
            )
            if not requirement.evidence_kinds:
                raise ProtocolError(
                    "HYPOTHESIS_NOT_GROUNDED",
                    "each requirement must declare at least one evidence kind",
                )
        if not any(
            requirement.discriminating
            for requirement in proposal.requirements
        ):
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "at least one requirement must be discriminating",
            )
        basis_total = (
            len(proposal.basis_evidence_ids)
            + len(proposal.basis_source_refs)
        )
        if not 1 <= basis_total <= 5:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                "basis_evidence_ids plus basis_source_refs must contain "
                "1-5 items",
            )

        basis_ids = self._resolve_basis(proposal)
        self._hypothesis_counter += 1
        hypothesis_id = f"hyp_{self._hypothesis_counter:03d}"
        requirements = [
            EvidenceRequirement(
                requirement_id=f"{hypothesis_id}_req_{index:02d}",
                description=requirement.description.strip(),
                evidence_kinds=list(requirement.evidence_kinds),
                discriminating=requirement.discriminating,
                suggested_tools=list(requirement.suggested_tools),
            )
            for index, requirement in enumerate(proposal.requirements, start=1)
        ]
        hypothesis = Hypothesis(
            hypothesis_id=hypothesis_id,
            statement=statement,
            cause_chain=cause_chain,
            basis_evidence_ids=basis_ids,
            requirements=requirements,
            falsifiers=falsifiers,
            status=HypothesisStatus.CANDIDATE,
        )
        self.hypotheses.append(hypothesis)
        return {
            "hypothesis_id": hypothesis_id,
            "requirement_ids": [
                requirement.requirement_id for requirement in requirements
            ],
            "status": hypothesis.status.value,
        }

    def assess_evidence(
        self,
        proposal: AssessmentsProposal,
    ) -> dict[str, object]:
        """Validate and persist a batch of evidence assessments."""
        if not 1 <= len(proposal.assessments) <= 4:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "assess_evidence accepts 1-4 assessments per call",
            )
        accepted: list[EvidenceAssessment] = []
        revised: list[EvidenceAssessment] = []
        rejected: list[dict[str, object]] = []
        seen_in_batch: set[tuple[str, str, str]] = set()
        existing_by_key = {
            (
                assessment.hypothesis_id,
                assessment.requirement_id,
                assessment.evidence_id,
            ): assessment
            for assessment in self.assessments
        }

        for index, item in enumerate(proposal.assessments, start=1):
            try:
                assessment = self._assess_one(
                    item,
                    existing_by_key,
                    seen_in_batch,
                )
            except ProtocolError as exc:
                rejected.append(
                    {
                        "index": index,
                        "reason": f"{exc.code}: {exc.message}",
                    }
                )
                continue
            accepted.append(assessment)
            if assessment.revised_at is not None:
                revised.append(assessment)

        if not accepted:
            reasons = "; ".join(str(entry["reason"]) for entry in rejected)
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"all assessments were rejected: {reasons}",
            )

        for assessment in accepted:
            target_hypothesis = self.get_hypothesis(assessment.hypothesis_id)
            assert target_hypothesis is not None
            if assessment.assessment_id not in target_hypothesis.assessment_ids:
                target_hypothesis.assessment_ids.append(
                    assessment.assessment_id
                )
            if assessment.evidence_id not in target_hypothesis.evidence_ids:
                target_hypothesis.evidence_ids.append(assessment.evidence_id)

        return {
            "assessment_ids": [
                assessment.assessment_id for assessment in accepted
            ],
            "revised_assessment_ids": [
                assessment.assessment_id for assessment in revised
            ],
            "rejected": rejected,
        }

    def _assess_one(
        self,
        item: AssessmentProposal,
        existing_by_key: dict[tuple[str, str, str], EvidenceAssessment],
        seen_in_batch: set[tuple[str, str, str]],
    ) -> EvidenceAssessment:
        if not item.hypothesis_id.strip() or not item.requirement_id.strip():
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "hypothesis_id and requirement_id must not be blank",
            )
        if (item.evidence_id is None) == (item.source_ref is None):
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "exactly one of evidence_id or source_ref must be provided",
            )
        if item.evidence_id is not None and not item.evidence_id.strip():
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "evidence_id must not be blank",
            )
        if item.source_ref is not None and not item.source_ref.strip():
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "source_ref must not be blank",
            )
        rationale = _required_text(
            item.rationale,
            "rationale",
            500,
            "INVALID_ASSESSMENT",
        )
        hypothesis, requirement = self._require_requirement(
            item.hypothesis_id,
            item.requirement_id,
        )
        evidence = self._resolve_assessment_evidence(
            item,
            hypothesis,
            requirement,
        )
        key = (
            item.hypothesis_id,
            item.requirement_id,
            evidence.evidence_id,
        )
        if key in seen_in_batch:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                "duplicate assessment within this batch for "
                f"{item.hypothesis_id}/{item.requirement_id}/"
                f"{evidence.evidence_id}",
            )
        if evidence.kind not in requirement.evidence_kinds:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"evidence kind {evidence.kind.value} does not satisfy "
                f"requirement {item.requirement_id}",
            )

        existing = existing_by_key.get(key)
        if existing is not None:
            existing.verdict = item.verdict
            existing.rationale = rationale
            existing.revised_at = self._timestamp()
            assessment = existing
        else:
            self._assessment_counter += 1
            assessment = EvidenceAssessment(
                assessment_id=f"asm_{self._assessment_counter:04d}",
                hypothesis_id=item.hypothesis_id,
                requirement_id=item.requirement_id,
                evidence_id=evidence.evidence_id,
                verdict=item.verdict,
                rationale=rationale,
                created_at=self._timestamp(),
            )
            self.assessments.append(assessment)
            existing_by_key[key] = assessment
        seen_in_batch.add(key)
        return assessment

    def propose_remediation(
        self,
        proposal: RemediationProposal,
        *,
        repo_root: Path | None,
        verification_backend: ReadOnlyVerificationBackend | None,
    ) -> dict[str, object]:
        """Validate and persist grounded remediation actions, dropping invalid ones."""
        if not proposal.actions:
            raise ProtocolError(
                "INVALID_REMEDIATION",
                "at least one remediation action is required",
            )

        accepted: list[RemediationAction] = []
        rejected: list[RejectedRemediation] = []
        per_hypothesis = Counter(
            action.hypothesis_id for action in self.remediation_actions
        )
        seen = {
            (action.hypothesis_id, action.type, action.target)
            for action in self.remediation_actions
        }

        def reject(
            item: object,
            reason: str,
        ) -> None:
            hypothesis_id = getattr(item, "hypothesis_id", None)
            title = getattr(item, "title", None)
            rejected.append(
                RejectedRemediation(
                    hypothesis_id=(
                        hypothesis_id.strip()
                        if isinstance(hypothesis_id, str)
                        else None
                    ),
                    title=(
                        title.strip()[:120] if isinstance(title, str) else None
                    ),
                    reason=reason,
                    observed_at=self._timestamp(),
                )
            )

        for item in proposal.actions:
            if (
                len(self.remediation_actions) + len(accepted)
                >= self.max_remediation_actions
            ):
                reject(
                    item,
                    f"remediation action limit reached: "
                    f"{self.max_remediation_actions}",
                )
                continue

            hypothesis = self.get_hypothesis(item.hypothesis_id.strip())
            if (
                hypothesis is not None
                and per_hypothesis[hypothesis.hypothesis_id]
                >= self.max_actions_per_hypothesis
            ):
                reject(
                    item,
                    f"per-hypothesis action limit reached: "
                    f"{self.max_actions_per_hypothesis}",
                )
                continue

            allowed = (
                allowed_evidence_for(
                    hypothesis,
                    self.assessments,
                    self.ledger.all(),
                )
                if hypothesis is not None
                else set()
            )
            action_id = (
                f"act_{self._remediation_counter + len(accepted) + 1:03d}"
            )
            try:
                action = validate_action(
                    item,
                    action_id=action_id,
                    hypothesis=hypothesis,
                    ledger=self.ledger,
                    allowed_evidence_ids=allowed,
                    repo_root=repo_root,
                    verification_backend=verification_backend,
                )
            except RemediationError as exc:
                reject(item, str(exc))
                continue

            key = (action.hypothesis_id, action.type, action.target)
            if key in seen:
                reject(
                    item,
                    "duplicate remediation action for "
                    f"({action.hypothesis_id}, {action.type}, {action.target})",
                )
                continue

            accepted.append(action)
            per_hypothesis[action.hypothesis_id] += 1
            seen.add(key)

        self._remediation_counter += len(accepted)
        self.remediation_actions.extend(accepted)
        self.rejected_remediations.extend(rejected)
        return {
            "action_ids": [action.action_id for action in accepted],
            "accepted": len(accepted),
            "rejected": [
                item.model_dump() for item in rejected
            ],
        }

    def evaluate(
        self,
        *,
        require_log_thread_context: bool = False,
        required_log_thread: str | None = None,
    ) -> EvaluationResult:
        """Evaluate the current protocol state and apply statuses to hypotheses."""
        result = evaluate_hypotheses(
            self.hypotheses,
            self.ledger.all(),
            self.assessments,
            require_log_thread_context=require_log_thread_context,
            required_log_thread=required_log_thread,
        )
        for hypothesis in self.hypotheses:
            evaluation = result.for_hypothesis(hypothesis.hypothesis_id)
            if evaluation is None:
                continue
            hypothesis.status = evaluation.status
            hypothesis.missing_requirement_ids = list(
                evaluation.missing_requirement_ids
            )
            hypothesis.ranking_score = evaluation.ranking_score
            hypothesis.evidence_ids = _dedupe(
                [
                    *hypothesis.basis_evidence_ids,
                    *evaluation.supporting_evidence_ids,
                    *evaluation.refuting_evidence_ids,
                ]
            )
        return result

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        """Return one hypothesis by runtime ID."""
        return next(
            (
                hypothesis
                for hypothesis in self.hypotheses
                if hypothesis.hypothesis_id == hypothesis_id
            ),
            None,
        )

    def get_requirement(
        self,
        hypothesis_id: str,
        requirement_id: str,
    ) -> EvidenceRequirement | None:
        """Return one requirement belonging to a hypothesis."""
        hypothesis = self.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            return None
        return next(
            (
                requirement
                for requirement in hypothesis.requirements
                if requirement.requirement_id == requirement_id
            ),
            None,
        )

    def validate_binding(
        self,
        hypothesis_id: str | None,
        requirement_id: str | None,
    ) -> tuple[str | None, str | None]:
        """Validate optional tool-call binding metadata."""
        if (hypothesis_id is None) != (requirement_id is None):
            raise ProtocolError(
                "INVALID_BINDING",
                "hypothesis_id and requirement_id must be provided together",
            )
        if hypothesis_id is None:
            return None, None
        if self.get_hypothesis(hypothesis_id) is None:
            raise ProtocolError(
                "INVALID_BINDING",
                f"hypothesis does not exist: {hypothesis_id}",
            )
        if self.get_requirement(hypothesis_id, requirement_id or "") is None:
            raise ProtocolError(
                "INVALID_BINDING",
                f"requirement does not exist: {hypothesis_id}/"
                f"{requirement_id}",
            )
        return hypothesis_id, requirement_id

    def bind_tool_evidence(
        self,
        evidence: Evidence,
        tool_call_id: str,
        hypothesis_id: str | None,
        requirement_id: str | None,
    ) -> Evidence:
        """Bind newly mapped tool evidence when metadata was supplied."""
        if hypothesis_id is None or requirement_id is None:
            return evidence
        return self.ledger.bind(
            evidence.evidence_id,
            hypothesis_id,
            requirement_id,
            tool_call_id=tool_call_id,
        )

    def _resolve_basis(self, proposal: HypothesisProposal) -> list[str]:
        resolved: list[str] = []
        for evidence_id in proposal.basis_evidence_ids:
            if self.ledger.get(evidence_id) is None:
                raise ProtocolError(
                    "HYPOTHESIS_NOT_GROUNDED",
                    f"basis evidence does not exist: {evidence_id}",
                )
            resolved.append(evidence_id)
        for source_ref in proposal.basis_source_refs:
            matches = self.ledger.by_source_ref(source_ref)
            if not matches:
                raise ProtocolError(
                    "HYPOTHESIS_NOT_GROUNDED",
                    f"basis source_ref does not resolve: {source_ref}",
                )
            resolved.extend(item.evidence_id for item in matches)
        deduped = _dedupe(resolved)
        if len(deduped) > 10:
            raise ProtocolError(
                "HYPOTHESIS_NOT_GROUNDED",
                f"basis resolves to too many evidence items: {len(deduped)}",
            )
        return deduped

    def _require_requirement(
        self,
        hypothesis_id: str,
        requirement_id: str,
    ) -> tuple[Hypothesis, EvidenceRequirement]:
        hypothesis = self.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"hypothesis does not exist: {hypothesis_id}",
            )
        requirement = self.get_requirement(hypothesis_id, requirement_id)
        if requirement is None:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"requirement does not exist: {requirement_id}",
            )
        return hypothesis, requirement

    def _resolve_assessment_evidence(
        self,
        item: AssessmentProposal,
        hypothesis: Hypothesis,
        requirement: EvidenceRequirement,
    ) -> Evidence:
        if item.evidence_id is not None:
            evidence = self.ledger.get(item.evidence_id)
            if evidence is None:
                raise ProtocolError(
                    "INVALID_ASSESSMENT",
                    f"evidence does not exist: {item.evidence_id}",
                )
            if not evidence.has_binding(
                hypothesis.hypothesis_id,
                requirement.requirement_id,
            ):
                self._reuse_tool_evidence(evidence, hypothesis, requirement)
            return evidence

        matches = [
            evidence
            for evidence in self.ledger.by_requirement(
                hypothesis.hypothesis_id,
                requirement.requirement_id,
            )
            if evidence.source_ref == item.source_ref
        ]
        if len(matches) != 1:
            reusable = [
                evidence
                for evidence in self.ledger.all()
                if evidence.source_ref == item.source_ref
                and evidence.tool_call_id is not None
                and evidence.kind in requirement.evidence_kinds
                and not evidence.has_binding(
                    hypothesis.hypothesis_id,
                    requirement.requirement_id,
                )
            ]
            if len(reusable) == 1:
                self._reuse_tool_evidence(
                    reusable[0],
                    hypothesis,
                    requirement,
                )
                return reusable[0]
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"source_ref must resolve to exactly one bound evidence item: "
                f"{item.source_ref} matched {len(matches)}",
            )
        return matches[0]

    def _reuse_tool_evidence(
        self,
        evidence: Evidence,
        hypothesis: Hypothesis,
        requirement: EvidenceRequirement,
    ) -> None:
        """Bind an existing tool-derived fact to another requirement."""
        if evidence.tool_call_id is None:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"evidence {evidence.evidence_id} is not bound to "
                f"{hypothesis.hypothesis_id}/{requirement.requirement_id}",
            )
        if evidence.kind not in requirement.evidence_kinds:
            raise ProtocolError(
                "INVALID_ASSESSMENT",
                f"evidence kind {evidence.kind.value} does not satisfy "
                f"requirement {requirement.requirement_id}",
            )
        self.ledger.bind(
            evidence.evidence_id,
            hypothesis.hypothesis_id,
            requirement.requirement_id,
            tool_call_id=evidence.tool_call_id,
        )

    def _timestamp(self) -> str:
        return self._now or datetime.now(UTC).isoformat()


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)
