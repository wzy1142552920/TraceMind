"""Audited control tools that mutate the diagnosis protocol state."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel

from tracemind.diagnosis.remediation import RemediationProposal
from tracemind.diagnosis.workspace import (
    AssessmentsProposal,
    DiagnosisWorkspace,
    HypothesisProposal,
    ProtocolError,
)
from tracemind.tools.contracts import (
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolHandlerResult,
    ToolSpec,
)
from tracemind.tools.registry import ToolRegistry


def register_control_tools(registry: ToolRegistry) -> None:
    """Register v0.3 hypothesis and assessment control tools."""
    registry.register(
        ToolSpec(
            name="diagnosis.propose_hypothesis",
            description=(
                "Create a grounded root-cause hypothesis with 1-5 verification "
                "requirements. Prefer existing basis_evidence_ids; any "
                "basis_source_refs must exactly match a ledger source_ref "
                "including its repo://, log://, or db:// prefix. If the primary "
                "event has a thread, include a log_thread_context requirement. "
                "A hypothesis that depends on database state needs a db_row "
                "requirement. Runtime assigns IDs."
            ),
            input_model=HypothesisProposal,
        ),
        _propose_hypothesis,
    )
    registry.register(
        ToolSpec(
            name="diagnosis.assess_evidence",
            description=(
                "Assess evidence for a hypothesis requirement. Use evidence_id "
                "or a unique source_ref; supports/refutes/neutral. Tool-derived "
                "evidence may be reused across requirements. Re-assessing the "
                "same hypothesis/requirement/evidence revises the earlier verdict. "
                "Valid items in a batch are kept; read rejected[] for the rest."
            ),
            input_model=AssessmentsProposal,
        ),
        _assess_evidence,
    )
    registry.register(
        ToolSpec(
            name="diagnosis.propose_remediation",
            description=(
                "Submit structured, evidence-grounded remediation suggestions for "
                "supported or confirmed hypotheses. Never patch or execute code."
            ),
            input_model=RemediationProposal,
        ),
        _propose_remediation,
    )


def _propose_hypothesis(
    context: ToolContext,
    args: BaseModel,
) -> ToolHandlerResult:
    workspace = _require_workspace(context)
    params = cast(HypothesisProposal, args)
    try:
        data = workspace.propose_hypothesis(params)
    except ProtocolError as exc:
        raise ToolError(ToolErrorCode(exc.code), exc.message) from exc
    return ToolHandlerResult(data=data)


def _assess_evidence(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    workspace = _require_workspace(context)
    params = cast(AssessmentsProposal, args)
    try:
        data = workspace.assess_evidence(params)
    except ProtocolError as exc:
        raise ToolError(ToolErrorCode(exc.code), exc.message) from exc
    return ToolHandlerResult(data=data)


def _propose_remediation(
    context: ToolContext,
    args: BaseModel,
) -> ToolHandlerResult:
    workspace = _require_workspace(context)
    params = cast(RemediationProposal, args)
    try:
        data = workspace.propose_remediation(
            params,
            repo_root=context.repo_root,
            verification_backend=context.verification_backend,
        )
    except ProtocolError as exc:
        raise ToolError(ToolErrorCode(exc.code), exc.message) from exc
    return ToolHandlerResult(data=data)


def _require_workspace(context: ToolContext) -> DiagnosisWorkspace:
    if context.workspace is None:
        raise ToolError(
            ToolErrorCode.TOOL_ERROR,
            "diagnosis workspace is not available",
        )
    return context.workspace
