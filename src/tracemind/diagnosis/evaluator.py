"""Deterministic, side-effect-free hypothesis evaluation for v0.3."""

from __future__ import annotations

from urllib.parse import unquote

from tracemind.diagnosis.evidence import (
    EvaluationResult,
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceRequirement,
    Hypothesis,
    HypothesisEvaluation,
    HypothesisStatus,
    RequirementEvaluation,
)

LOG_KINDS = frozenset(
    {
        EvidenceKind.LOG_EVENT,
        EvidenceKind.LOG_THREAD_CONTEXT,
        EvidenceKind.STACK_FRAME,
    }
)
CODE_KINDS = frozenset(
    {
        EvidenceKind.SOURCE_CODE,
        EvidenceKind.CALL_PATH,
        EvidenceKind.SQL,
        EvidenceKind.ANNOTATION,
        EvidenceKind.CONFIG,
    }
)


def evaluate_hypotheses(
    hypotheses: list[Hypothesis],
    evidence: list[Evidence],
    assessments: list[EvidenceAssessment],
    require_log_thread_context: bool = False,
    required_log_thread: str | None = None,
) -> EvaluationResult:
    """Compute requirement coverage, qualification, and run-level confirmation."""
    evidence_by_id = {item.evidence_id: item for item in evidence}
    evaluations: list[HypothesisEvaluation] = []

    for hypothesis in hypotheses:
        evaluations.append(
            _evaluate_hypothesis(
                hypothesis,
                evidence_by_id,
                assessments,
                require_log_thread_context=require_log_thread_context,
                required_log_thread=required_log_thread,
            )
        )

    qualifying = [item for item in evaluations if item.qualifies]
    ambiguity = len(qualifying) > 1
    run_confirmed = False

    if len(qualifying) == 1 and len(hypotheses) >= 2:
        target = qualifying[0]
        alternatives = [
            item
            for item in evaluations
            if item.hypothesis_id != target.hypothesis_id
        ]
        if alternatives and all(
            item.status is HypothesisStatus.CONTRADICTED
            for item in alternatives
        ):
            target.status = HypothesisStatus.CONFIRMED
            target.reasons.append("all alternative hypotheses were contradicted")
            run_confirmed = True
        else:
            target.status = HypothesisStatus.SUPPORTED
            target.reasons.append(
                "an alternative hypothesis remains open; confirmation is withheld"
            )
    elif len(qualifying) > 1:
        for item in qualifying:
            item.status = HypothesisStatus.SUPPORTED
            item.reasons.append(
                "another hypothesis also qualifies; the run is ambiguous"
            )

    for item in evaluations:
        item.ranking_score = _ranking_score(item)
        if (
            item.status is HypothesisStatus.CANDIDATE
            and not item.supporting_evidence_ids
        ):
            item.reasons.append("no supporting evidence was assessed")

    non_contradicted = [
        item
        for item in evaluations
        if item.status is not HypothesisStatus.CONTRADICTED
    ]
    top = min(
        non_contradicted,
        key=lambda item: (-item.ranking_score, item.hypothesis_id),
        default=None,
    )

    return EvaluationResult(
        hypotheses=evaluations,
        top_hypothesis_id=top.hypothesis_id if top is not None else None,
        run_confirmed=run_confirmed,
        ambiguity=ambiguity,
    )


def _evaluate_hypothesis(
    hypothesis: Hypothesis,
    evidence_by_id: dict[str, Evidence],
    assessments: list[EvidenceAssessment],
    *,
    require_log_thread_context: bool,
    required_log_thread: str | None,
) -> HypothesisEvaluation:
    supporting_ids: dict[str, None] = {}
    refuting_ids: dict[str, None] = {}
    requirement_results: list[RequirementEvaluation] = []
    missing: list[str] = []
    satisfied_discriminating = 0
    satisfied_other = 0

    for requirement in hypothesis.requirements:
        supports: dict[str, None] = {}
        refutes: dict[str, None] = {}
        for assessment in assessments:
            if assessment.hypothesis_id != hypothesis.hypothesis_id:
                continue
            if assessment.requirement_id != requirement.requirement_id:
                continue
            item = evidence_by_id.get(assessment.evidence_id)
            if not _valid_assessment(item, hypothesis, requirement):
                continue
            target = (
                supports
                if assessment.verdict.value == "supports"
                else refutes
                if assessment.verdict.value == "refutes"
                else None
            )
            if target is not None:
                target[assessment.evidence_id] = None

        satisfied = bool(supports)
        if satisfied:
            if requirement.discriminating:
                satisfied_discriminating += 1
            else:
                satisfied_other += 1
            supporting_ids.update(supports)
        else:
            missing.append(requirement.requirement_id)
        refuting_ids.update(refutes)
        requirement_results.append(
            RequirementEvaluation(
                requirement_id=requirement.requirement_id,
                satisfied=satisfied,
                discriminating=requirement.discriminating,
                supporting_evidence_ids=list(supports),
                refuting_evidence_ids=list(refutes),
            )
        )

    all_satisfied = bool(hypothesis.requirements) and not missing
    tool_ids = [
        evidence_id
        for evidence_id in supporting_ids
        if evidence_by_id[evidence_id].tool_call_id is not None
    ]
    supported_evidence = [evidence_by_id[item] for item in supporting_ids]
    log_coverage = any(item.kind in LOG_KINDS for item in supported_evidence)
    code_coverage = any(item.kind in CODE_KINDS for item in supported_evidence)
    tool_coverage = bool(tool_ids)
    context_ok = _context_gate(
        supported_evidence,
        require_log_thread_context=require_log_thread_context,
        required_log_thread=required_log_thread,
    )
    basis_ok = bool(hypothesis.basis_evidence_ids) and all(
        evidence_id in evidence_by_id
        for evidence_id in hypothesis.basis_evidence_ids
    )

    reasons: list[str] = []
    if not basis_ok:
        reasons.append("basis evidence is missing")
    if not hypothesis.requirements:
        reasons.append("hypothesis declares no requirements")
    if missing:
        reasons.append(f"missing requirements: {', '.join(missing)}")
    if hypothesis.requirements and not satisfied_discriminating:
        reasons.append("no discriminating requirement is satisfied")
    if refuting_ids:
        reasons.append("at least one requirement was refuted")
    if not tool_coverage:
        reasons.append("no assessed evidence was read through a tool")
    if not log_coverage:
        reasons.append("no log evidence was assessed as supporting")
    if not code_coverage:
        reasons.append("no code evidence was assessed as supporting")
    if require_log_thread_context and not context_ok:
        reasons.append("same-thread log context is missing or mismatched")

    qualifies = (
        basis_ok
        and all_satisfied
        and satisfied_discriminating > 0
        and not refuting_ids
        and tool_coverage
        and log_coverage
        and code_coverage
        and context_ok
    )

    if refuting_ids:
        status = HypothesisStatus.CONTRADICTED
    elif supporting_ids:
        status = HypothesisStatus.SUPPORTED
    else:
        status = HypothesisStatus.CANDIDATE

    return HypothesisEvaluation(
        hypothesis_id=hypothesis.hypothesis_id,
        status=status,
        qualifies=qualifies,
        requirements=requirement_results,
        supporting_evidence_ids=list(supporting_ids),
        refuting_evidence_ids=list(refuting_ids),
        missing_requirement_ids=missing,
        ranking_score=0,
        reasons=reasons,
    )


def _valid_assessment(
    evidence: Evidence | None,
    hypothesis: Hypothesis,
    requirement: EvidenceRequirement,
) -> bool:
    if evidence is None:
        return False
    if not evidence.has_binding(
        hypothesis.hypothesis_id,
        requirement.requirement_id,
    ):
        return False
    return evidence.kind in requirement.evidence_kinds


def _context_gate(
    supported_evidence: list[Evidence],
    *,
    require_log_thread_context: bool,
    required_log_thread: str | None,
) -> bool:
    if not require_log_thread_context:
        return True
    for item in supported_evidence:
        if item.kind is not EvidenceKind.LOG_THREAD_CONTEXT:
            continue
        content_thread = item.content.get("thread")
        source_thread = _thread_from_source_ref(item.source_ref)
        if (
            isinstance(content_thread, str)
            and source_thread is not None
            and content_thread != source_thread
        ):
            continue
        actual_thread = (
            content_thread
            if isinstance(content_thread, str)
            else source_thread
        )
        if required_log_thread is not None and actual_thread != required_log_thread:
            continue
        return True
    return False


def _thread_from_source_ref(source_ref: str) -> str | None:
    if "thread=" not in source_ref:
        return None
    fragment = source_ref.split("thread=", 1)[1]
    value = fragment.split("&", 1)[0]
    return unquote(value) or None


def _ranking_score(item: HypothesisEvaluation) -> int:
    satisfied_discriminating = sum(
        1
        for requirement in item.requirements
        if requirement.satisfied and requirement.discriminating
    )
    satisfied_other = sum(
        1
        for requirement in item.requirements
        if requirement.satisfied and not requirement.discriminating
    )
    score = 4 * satisfied_discriminating + 2 * satisfied_other
    if item.status is HypothesisStatus.CONFIRMED:
        score += 2
    elif item.status is HypothesisStatus.SUPPORTED:
        score += 1
    if item.supporting_evidence_ids:
        score += 1
    score -= 5 * len(item.refuting_evidence_ids)
    score -= len(item.missing_requirement_ids)
    return score
