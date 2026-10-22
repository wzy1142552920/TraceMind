"""Deterministic report generation and citation validation for v0.3."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from jinja2 import Environment, PackageLoader
from pydantic import BaseModel, Field

from tracemind.core.models import ParsedLog
from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
    Hypothesis,
    HypothesisStatus,
    LLMCallRecord,
    LLMUsageSummary,
    RemediationAction,
    RunResult,
)
from tracemind.diagnosis.remediation import allowed_evidence_for
from tracemind.diagnosis.state import RuntimeState
from tracemind.workspace.paths import resolve_under_root

_SCHEMA_VERSION = "0.3"
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPO_REF_RE = re.compile(
    r"^repo://(?P<path>.+?)#L(?P<start>\d+)(?:-L(?P<end>\d+))?$"
)
_LOG_FILE_REF_RE = re.compile(
    r"^log://(?P<path>[^#]+)#(?:thread=(?P<thread>[^&]+)&)?"
    r"L(?P<start>\d+)-L(?P<end>\d+)$"
)
_DB_KINDS = frozenset({EvidenceKind.DB_ROW, EvidenceKind.DB_SCHEMA})
_CONFIRMED = HypothesisStatus.CONFIRMED
_SUPPORTED = HypothesisStatus.SUPPORTED

_TEMPLATE_ENV = Environment(
    loader=PackageLoader("tracemind.diagnosis", "templates"),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


class ReportRequirement(BaseModel):
    """One verification requirement and its deterministic coverage."""

    requirement_id: str
    description: str
    evidence_kinds: list[str] = Field(default_factory=list)
    discriminating: bool = False
    satisfied: bool = False
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    refuting_evidence_ids: list[str] = Field(default_factory=list)


class ReportHypothesis(BaseModel):
    """A ranked root-cause hypothesis rendered in a report."""

    hypothesis_id: str
    statement: str
    cause_chain: list[str] = Field(default_factory=list)
    status: str
    ranking_score: int = 0
    basis_evidence_ids: list[str] = Field(default_factory=list)
    requirements: list[ReportRequirement] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    refuting_evidence_ids: list[str] = Field(default_factory=list)
    missing_requirement_ids: list[str] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)


class ReportSource(BaseModel):
    """A referenced source and, when available, its reviewable context."""

    evidence_id: str
    kind: str
    source_ref: str
    claim: str
    verified: bool = False
    thread: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    messages: list[str] = Field(default_factory=list)


class ReportRemediationAction(BaseModel):
    """A validated remediation suggestion with its conditional flag."""

    action_id: str
    hypothesis_id: str
    type: str
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    target: str
    risk: str
    prerequisites: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    conditional: bool = False


class ReportVerification(BaseModel):
    """Which read-only verification environment produced runtime evidence."""

    environment: str = "none"
    backend: str | None = None
    tables_queried: list[str] = Field(default_factory=list)
    note: str = ""


class ReportToolCall(BaseModel):
    """A tool call summary rendered in a report."""

    tool_call_id: str
    tool_name: str
    ok: bool
    error_code: str | None = None
    duration_ms: int = 0


class ReportStop(BaseModel):
    """Why the runtime stopped."""

    reason: str
    state: str


class ReportValidation(BaseModel):
    """Result of deterministic reference, grounding, and status checks."""

    citations_valid: bool = False
    evidence_ids_valid: bool = False
    hypotheses_valid: bool = False
    remediation_grounded: bool = False
    verification_labeled: bool = False
    status_consistent: bool = False
    errors: list[str] = Field(default_factory=list)


class Report(BaseModel):
    """The JSON report schema for v0.3."""

    schema_version: str = _SCHEMA_VERSION
    incident_id: str
    run_id: str
    service: str
    status: str
    summary: str
    hypotheses: list[ReportHypothesis] = Field(default_factory=list)
    remediation_plan: list[ReportRemediationAction] = Field(default_factory=list)
    verification: ReportVerification = Field(default_factory=ReportVerification)
    sources: list[ReportSource] = Field(default_factory=list)
    tool_calls: list[ReportToolCall] = Field(default_factory=list)
    llm_usage: LLMUsageSummary = Field(default_factory=LLMUsageSummary)
    llm_calls: list[LLMCallRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stop: ReportStop
    budget_usage: dict[str, int] = Field(default_factory=dict)
    validation: ReportValidation = Field(default_factory=ReportValidation)


def report_status(result: RunResult) -> str:
    """Map the run-level deterministic evaluation to the report status."""
    if result.state is RuntimeState.FAILED:
        return "insufficient_data"
    has_confirmed = any(
        hypothesis.status is _CONFIRMED for hypothesis in result.hypotheses
    )
    if has_confirmed and result.evaluation.run_confirmed:
        return "confirmed"
    if any(
        hypothesis.status in {_CONFIRMED, _SUPPORTED}
        for hypothesis in result.hypotheses
    ):
        return "probable"
    return "insufficient_data"


def build_report(
    result: RunResult,
    parsed_log: ParsedLog,
    repo_root: Path,
) -> Report:
    """Build and validate a report from one runtime result."""
    status = report_status(result)
    verification = _build_verification(result)
    limitations = list(result.limitations)
    if verification.environment == "fixture":
        _append_limitation(
            limitations,
            "Database verification used fixture data, not a live database.",
        )
    if result.state is RuntimeState.STOPPED_BUDGET:
        _append_limitation(
            limitations,
            "Run stopped because the configured budget was exhausted.",
        )
    elif result.state is RuntimeState.INSUFFICIENT_DATA:
        _append_limitation(
            limitations,
            "Evidence was insufficient to confirm a root cause.",
        )
    elif result.state is RuntimeState.FAILED:
        _append_limitation(
            limitations,
            "The run failed before a complete diagnosis could be produced.",
        )
    if (
        not result.remediation_actions
        and any(
            hypothesis.status in {_CONFIRMED, _SUPPORTED}
            for hypothesis in result.hypotheses
        )
    ):
        _append_limitation(
            limitations,
            "No validated remediation action was available; the report "
            "contains no remediation plan.",
        )

    hypotheses = _build_hypotheses(result)
    remediation_plan = [
        _report_action(action, result.hypotheses)
        for action in result.remediation_actions
    ]
    sources = _build_sources(result, hypotheses, remediation_plan)
    summary = _build_summary(status, hypotheses, result, verification)

    report = Report(
        incident_id=result.incident_id,
        run_id=result.run_id,
        service=result.service,
        status=status,
        summary=summary,
        hypotheses=hypotheses,
        remediation_plan=remediation_plan,
        verification=verification,
        sources=sources,
        tool_calls=[
            ReportToolCall(
                tool_call_id=record.tool_call_id,
                tool_name=record.tool_name,
                ok=record.ok,
                error_code=record.error_code,
                duration_ms=record.duration_ms,
            )
            for record in result.tool_calls
        ],
        llm_usage=result.llm_usage.model_copy(deep=True),
        llm_calls=[record.model_copy(deep=True) for record in result.llm_calls],
        limitations=limitations,
        stop=ReportStop(
            reason=result.stop_reason.value,
            state=result.state.value,
        ),
        budget_usage=dict(result.budget_usage),
    )
    return validate_report(report, result, parsed_log, repo_root)


def validate_report(
    report: Report,
    result: RunResult,
    parsed_log: ParsedLog,
    repo_root: Path,
) -> Report:
    """Validate citations, evidence IDs, hypotheses, and remediation grounding."""
    citation_errors: list[str] = []
    evidence_errors: list[str] = []
    hypothesis_errors: list[str] = []
    remediation_errors: list[str] = []
    verification_errors: list[str] = []
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    evidence_ids = set(evidence_by_id)
    evidence_source_refs = {
        item.source_ref for item in result.evidence
    }
    thread_evidence = [
        item
        for item in result.evidence
        if item.kind is EvidenceKind.LOG_THREAD_CONTEXT
    ]

    for source in report.sources:
        if source.evidence_id not in evidence_ids:
            evidence_errors.append(
                f"missing source evidence id {source.evidence_id}"
            )
        valid, error = _check_source_ref(
            source,
            parsed_log,
            repo_root,
            thread_evidence,
            evidence_source_refs,
        )
        source.verified = valid
        if not valid:
            citation_errors.append(
                f"invalid source reference {source.source_ref}: {error}"
            )

    for hypothesis in report.hypotheses:
        for evidence_id in _hypothesis_evidence_ids(hypothesis):
            if evidence_id not in evidence_ids:
                evidence_errors.append(f"missing evidence id {evidence_id}")
        if hypothesis.status == "confirmed" and not result.evaluation.run_confirmed:
            hypothesis_errors.append(
                f"hypothesis {hypothesis.hypothesis_id} is confirmed without "
                "run-level confirmation"
            )
        if hypothesis.status not in {
            "confirmed",
            "supported",
            "contradicted",
            "insufficient_data",
        }:
            hypothesis_errors.append(
                f"hypothesis {hypothesis.hypothesis_id} has invalid report "
                f"status {hypothesis.status}"
            )
    if result.evaluation.run_confirmed and not any(
        hypothesis.status == "confirmed" for hypothesis in report.hypotheses
    ):
        hypothesis_errors.append(
            "run-level confirmation is missing a confirmed report hypothesis"
        )

    source_hypotheses = {
        hypothesis.hypothesis_id: hypothesis for hypothesis in result.hypotheses
    }
    grounded_actions: list[ReportRemediationAction] = []
    for action in report.remediation_plan:
        action_errors = _validate_report_action(
            action,
            source_hypotheses,
            evidence_ids,
            result,
            repo_root,
        )
        if action_errors:
            remediation_errors.extend(action_errors)
            continue
        grounded_actions.append(action)
    if remediation_errors:
        report.remediation_plan = grounded_actions
        if not grounded_actions:
            _append_limitation(
                report.limitations,
                "All remediation actions in the report failed grounding "
                "validation and were dropped.",
            )
    if result.rejected_remediations and not report.remediation_plan:
        remediation_errors.extend(
            f"all remediation actions were rejected: {rejection.reason[:300]}"
            for rejection in result.rejected_remediations[:10]
        )
    elif result.rejected_remediations:
        _append_limitation(
            report.limitations,
            f"{len(result.rejected_remediations)} rejected remediation "
            "attempt(s) were excluded; the report keeps only validated actions.",
        )
    remediation_grounded = not remediation_errors

    verification_errors.extend(_validate_verification(report, result))

    citations_valid = not citation_errors
    evidence_ids_valid = not evidence_errors
    hypotheses_valid = not hypothesis_errors
    verification_labeled = not verification_errors
    expected_status = report_status(result)
    status_consistent = report.status == expected_status
    status_errors: list[str] = []
    if not status_consistent:
        status_errors.append(
            f"report status {report.status} does not match runtime status "
            f"{expected_status}"
        )
        report.status = expected_status
        status_consistent = False

    diagnostic_failure = not (
        citations_valid and evidence_ids_valid and hypotheses_valid
    )
    if diagnostic_failure and report.status != "insufficient_data":
        report.status = "insufficient_data"
        _append_limitation(
            report.limitations,
            "Report diagnosis validation failed; status was downgraded.",
        )
        status_consistent = False

    report.validation = ReportValidation(
        citations_valid=citations_valid,
        evidence_ids_valid=evidence_ids_valid,
        hypotheses_valid=hypotheses_valid,
        remediation_grounded=remediation_grounded,
        verification_labeled=verification_labeled,
        status_consistent=status_consistent,
        errors=[
            *citation_errors,
            *evidence_errors,
            *hypothesis_errors,
            *remediation_errors,
            *verification_errors,
            *status_errors,
        ],
    )
    return report


def render_markdown(report: Report) -> str:
    """Render a deterministic human-readable report from the Jinja2 template."""
    template = _TEMPLATE_ENV.get_template("report.md.j2")
    return template.render(report=report)


def _build_hypotheses(result: RunResult) -> list[ReportHypothesis]:
    hypotheses: list[ReportHypothesis] = []
    for hypothesis in result.hypotheses:
        item_eval = result.evaluation.for_hypothesis(hypothesis.hypothesis_id)
        requirements: list[ReportRequirement] = []
        for requirement in hypothesis.requirements:
            requirement_eval = (
                next(
                    (
                        item
                        for item in item_eval.requirements
                        if item.requirement_id == requirement.requirement_id
                    ),
                    None,
                )
                if item_eval is not None
                else None
            )
            requirements.append(
                ReportRequirement(
                    requirement_id=requirement.requirement_id,
                    description=requirement.description,
                    evidence_kinds=[
                        kind.value for kind in requirement.evidence_kinds
                    ],
                    discriminating=requirement.discriminating,
                    satisfied=(
                        requirement_eval.satisfied
                        if requirement_eval is not None
                        else requirement.requirement_id
                        not in hypothesis.missing_requirement_ids
                    ),
                    supporting_evidence_ids=(
                        list(requirement_eval.supporting_evidence_ids)
                        if requirement_eval is not None
                        else []
                    ),
                    refuting_evidence_ids=(
                        list(requirement_eval.refuting_evidence_ids)
                        if requirement_eval is not None
                        else []
                    ),
                )
            )
        report_status_value = (
            "insufficient_data"
            if hypothesis.status is HypothesisStatus.CANDIDATE
            else hypothesis.status.value
        )
        hypotheses.append(
            ReportHypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                statement=hypothesis.statement,
                cause_chain=list(hypothesis.cause_chain),
                status=report_status_value,
                ranking_score=hypothesis.ranking_score,
                basis_evidence_ids=list(hypothesis.basis_evidence_ids),
                requirements=requirements,
                supporting_evidence_ids=(
                    list(item_eval.supporting_evidence_ids)
                    if item_eval is not None
                    else []
                ),
                refuting_evidence_ids=(
                    list(item_eval.refuting_evidence_ids)
                    if item_eval is not None
                    else []
                ),
                missing_requirement_ids=list(
                    hypothesis.missing_requirement_ids
                ),
                falsifiers=list(hypothesis.falsifiers),
            )
        )
    return sorted(
        hypotheses,
        key=lambda item: (-item.ranking_score, item.hypothesis_id),
    )


def _report_action(
    action: RemediationAction,
    hypotheses: list[Hypothesis],
) -> ReportRemediationAction:
    hypothesis = next(
        (
            item
            for item in hypotheses
            if item.hypothesis_id == action.hypothesis_id
        ),
        None,
    )
    return ReportRemediationAction(
        action_id=action.action_id,
        hypothesis_id=action.hypothesis_id,
        type=action.type,
        title=action.title,
        description=action.description,
        evidence_ids=list(action.evidence_ids),
        target=action.target,
        risk=action.risk,
        prerequisites=list(action.prerequisites),
        verification_steps=list(action.verification_steps),
        conditional=(
            hypothesis is not None and hypothesis.status is _SUPPORTED
        ),
    )


def _build_sources(
    result: RunResult,
    hypotheses: list[ReportHypothesis],
    remediation_plan: list[ReportRemediationAction],
) -> list[ReportSource]:
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    referenced: set[str] = set()
    for source_hypothesis in result.hypotheses:
        referenced.update(source_hypothesis.evidence_ids)
    for hypothesis in hypotheses:
        referenced.update(hypothesis.basis_evidence_ids)
        referenced.update(hypothesis.supporting_evidence_ids)
        referenced.update(hypothesis.refuting_evidence_ids)
        for requirement in hypothesis.requirements:
            referenced.update(requirement.supporting_evidence_ids)
            referenced.update(requirement.refuting_evidence_ids)
    for action in remediation_plan:
        referenced.update(action.evidence_ids)

    sources: list[ReportSource] = []
    for evidence_id in sorted(referenced):
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        sources.append(_report_source(evidence))
    return sources


def _report_source(evidence: Evidence) -> ReportSource:
    source = ReportSource(
        evidence_id=evidence.evidence_id,
        kind=evidence.kind.value,
        source_ref=evidence.source_ref,
        claim=evidence.claim,
    )
    if evidence.kind is EvidenceKind.LOG_THREAD_CONTEXT:
        content = evidence.content
        thread = content.get("thread")
        line_start = content.get("line_start")
        line_end = content.get("line_end")
        source.thread = thread if isinstance(thread, str) else None
        source.line_start = line_start if isinstance(line_start, int) else None
        source.line_end = line_end if isinstance(line_end, int) else None
        items = content.get("items")
        if isinstance(items, list):
            source.messages = [
                str(item["message"])
                for item in items[:5]
                if isinstance(item, dict) and "message" in item
            ]
    return source


def _build_verification(result: RunResult) -> ReportVerification:
    database_evidence = [
        item
        for item in result.evidence
        if item.kind in _DB_KINDS
        or item.provenance is EvidenceProvenance.FAKE_VERIFICATION
    ]
    if not database_evidence:
        return ReportVerification(
            environment="none",
            backend=None,
            tables_queried=[],
            note="No read-only database verification was performed.",
        )
    tables: list[str] = []
    for item in database_evidence:
        table = item.content.get("table")
        if isinstance(table, str) and table not in tables:
            tables.append(table)
    return ReportVerification(
        environment="fixture",
        backend="fake",
        tables_queried=tables,
        note=(
            "Runtime database checks used fixture data, not a live database; "
            "results are not production confirmation."
        ),
    )


def _build_summary(
    status: str,
    hypotheses: list[ReportHypothesis],
    result: RunResult,
    verification: ReportVerification,
) -> str:
    top = next(
        (
            hypothesis
            for hypothesis in hypotheses
            if hypothesis.status in {"confirmed", "supported"}
        ),
        None,
    )
    verification_note = (
        "Read-only DB verification used fixture data."
        if verification.environment == "fixture"
        else "No DB verification was performed."
    )
    if top is None:
        return (
            "No supported root cause candidate was produced. "
            f"{verification_note}"
        )
    return (
        f"{status}: {top.statement} "
        f"({len(top.supporting_evidence_ids)} supporting evidence IDs, "
        f"{len(result.tool_calls)} tool calls, "
        f"{len(result.remediation_actions)} remediation actions). "
        f"{verification_note} "
        f"verification={verification.environment}."
    )


def _hypothesis_evidence_ids(hypothesis: ReportHypothesis) -> list[str]:
    ids = [
        *hypothesis.basis_evidence_ids,
        *hypothesis.supporting_evidence_ids,
        *hypothesis.refuting_evidence_ids,
    ]
    for requirement in hypothesis.requirements:
        ids.extend(requirement.supporting_evidence_ids)
        ids.extend(requirement.refuting_evidence_ids)
    return list(dict.fromkeys(ids))


def _validate_report_action(
    action: ReportRemediationAction,
    hypotheses: dict[str, Hypothesis],
    evidence_ids: set[str],
    result: RunResult,
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    hypothesis = hypotheses.get(action.hypothesis_id)
    if hypothesis is None:
        return [f"remediation {action.action_id} references unknown hypothesis"]
    if hypothesis.status not in {_SUPPORTED, _CONFIRMED}:
        errors.append(
            f"remediation {action.action_id} references hypothesis "
            f"{action.hypothesis_id} with status {hypothesis.status.value}"
        )
    allowed = allowed_evidence_for(
        hypothesis,
        result.assessments,
        result.evidence,
    )
    for evidence_id in action.evidence_ids:
        if evidence_id not in evidence_ids:
            errors.append(
                f"remediation {action.action_id} cites missing evidence "
                f"{evidence_id}"
            )
        elif evidence_id not in allowed:
            errors.append(
                f"remediation {action.action_id} cites evidence not associated "
                f"with {action.hypothesis_id}: {evidence_id}"
            )
    expected_conditional = hypothesis.status is _SUPPORTED
    if action.conditional != expected_conditional:
        errors.append(
            f"remediation {action.action_id} has conditional="
            f"{action.conditional}, expected {expected_conditional}"
        )
    if action.type == "code":
        file_path = action.target.split("#", 1)[0].strip()
        try:
            target = resolve_under_root(repo_root, file_path)
        except ValueError as exc:
            errors.append(
                f"remediation {action.action_id} code target is outside the "
                f"repo: {exc}"
            )
        else:
            if not target.is_file():
                errors.append(
                    f"remediation {action.action_id} code target does not "
                    f"exist: {file_path}"
                )
    elif action.type == "data":
        table = (
            action.target.removeprefix("db://")
            .split("#", 1)[0]
            .split("/", 1)[0]
        )
        if _TABLE_RE.fullmatch(table) is None:
            errors.append(
                f"remediation {action.action_id} has an invalid data target"
            )
    return errors


def _validate_verification(
    report: Report,
    result: RunResult,
) -> list[str]:
    errors: list[str] = []
    database_evidence = [
        item
        for item in result.evidence
        if item.kind in _DB_KINDS
        or item.provenance is EvidenceProvenance.FAKE_VERIFICATION
    ]
    if database_evidence:
        if report.verification.environment != "fixture":
            errors.append(
                "verification.environment must be fixture when fixture DB "
                "evidence exists"
            )
        if not report.verification.backend:
            errors.append(
                "verification.backend is required when fixture DB evidence exists"
            )
        if not report.verification.note.strip():
            errors.append("verification.note must not be empty")
        if "fixture" not in report.verification.note.lower():
            errors.append(
                "verification.note must state that fixture data was used"
            )
        if "fixture" not in report.summary.lower():
            errors.append(
                "report summary must state that fixture verification was used"
            )
        if not any(
            "fixture" in limitation.lower()
            for limitation in report.limitations
        ):
            errors.append(
                "report limitations must state that fixture verification was used"
            )
        for item in database_evidence:
            if item.content.get("environment") != "fixture":
                errors.append(
                    f"database evidence {item.evidence_id} is not labeled as "
                    "fixture"
                )
    elif report.verification.environment != "none":
        errors.append(
            "verification.environment must be none when no DB evidence exists"
        )
    return errors


def _check_source_ref(
    source: ReportSource,
    parsed_log: ParsedLog,
    repo_root: Path,
    thread_evidence: list[Evidence],
    evidence_source_refs: set[str],
) -> tuple[bool, str]:
    source_ref = source.source_ref
    repo_match = _REPO_REF_RE.fullmatch(source_ref)
    if repo_match is not None:
        try:
            target = resolve_under_root(repo_root, repo_match.group("path"))
        except ValueError as exc:
            return False, str(exc)
        if not target.is_file():
            return False, "file does not exist"
        lines = _read_lines(target)
        if lines is None:
            return False, "file is not readable"
        return _check_range(
            int(repo_match.group("start")),
            int(repo_match.group("end") or repo_match.group("start")),
            len(lines),
        )

    log_file_match = _LOG_FILE_REF_RE.fullmatch(source_ref)
    if log_file_match is not None:
        input_path = Path(parsed_log.source_file)
        log_target = Path(log_file_match.group("path"))
        if not log_target.is_absolute():
            log_target = input_path.parent / log_target
        try:
            if log_target.resolve() != input_path.resolve():
                return False, "log file does not match the input log"
        except OSError:
            return False, "log file is not resolvable"
        lines = _read_lines(input_path)
        if lines is None:
            return False, "log file is not readable"
        start = int(log_file_match.group("start"))
        end = int(log_file_match.group("end"))
        valid, error = _check_range(start, end, len(lines))
        if not valid:
            return False, error
        thread = log_file_match.group("thread")
        if thread is None:
            return True, ""
        decoded_thread = unquote(thread)
        matching = [
            item
            for item in thread_evidence
            if item.content.get("thread") == decoded_thread
        ]
        if not matching:
            return False, "no matching same-thread context evidence in ledger"
        if not any(
            _range_within(item, start, end) for item in matching
        ):
            return False, (
                "thread context line range is outside the recorded same-thread "
                "evidence"
            )
        if source.kind == EvidenceKind.LOG_THREAD_CONTEXT.value and (
            source.thread is None
        ):
            return False, "thread context source is missing thread metadata"
        return True, ""

    if source_ref.startswith("log://"):
        event_id = source_ref.removeprefix("log://")
        if any(event.event_id == event_id for event in parsed_log.events):
            return True, ""
        return False, "log event does not exist"

    if source_ref.startswith("db://"):
        if source_ref not in evidence_source_refs:
            return False, "db source is not present in the evidence ledger"
        return True, ""

    return False, "unsupported source reference"


def _range_within(
    evidence: Evidence,
    start: int,
    end: int,
) -> bool:
    recorded_start = evidence.content.get("line_start")
    recorded_end = evidence.content.get("line_end")
    if not isinstance(recorded_start, int) or not isinstance(recorded_end, int):
        return False
    return recorded_start <= start and end <= recorded_end


def _check_range(start: int, end: int, line_count: int) -> tuple[bool, str]:
    if start < 1 or end < start:
        return False, "invalid line range"
    if end > line_count:
        return False, "line range exceeds file length"
    return True, ""


def _read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def _append_limitation(limitations: list[str], message: str) -> None:
    if message not in limitations:
        limitations.append(message)
