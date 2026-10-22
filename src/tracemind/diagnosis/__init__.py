"""Deterministic diagnosis runtime and evidence models."""

from tracemind.diagnosis.budget import Budget, BudgetUsage
from tracemind.diagnosis.evaluator import evaluate_hypotheses
from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceAssessment,
    EvidenceKind,
    EvidenceProvenance,
    EvidenceRequirement,
    Hypothesis,
    HypothesisStatus,
    RunResult,
    ToolCallRecord,
)
from tracemind.diagnosis.state import (
    InvalidStateTransition,
    RuntimeEvent,
    RuntimeState,
    StopReason,
    is_terminal,
    validate_transition,
)

__all__ = [
    "Budget",
    "BudgetUsage",
    "DiagnosisRuntime",
    "Evidence",
    "EvidenceAssessment",
    "EvidenceKind",
    "EvidenceProvenance",
    "EvidenceRequirement",
    "Hypothesis",
    "HypothesisStatus",
    "InvalidStateTransition",
    "RunResult",
    "RuntimeEvent",
    "RuntimeState",
    "StopReason",
    "ToolCallRecord",
    "evaluate_hypotheses",
    "is_terminal",
    "validate_transition",
]


def __getattr__(name: str) -> object:
    if name == "DiagnosisRuntime":
        from tracemind.diagnosis.runtime import DiagnosisRuntime

        return DiagnosisRuntime
    raise AttributeError(name)
