"""Deterministic report generation and citation validation for v0.1."""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, PackageLoader
from pydantic import BaseModel, Field

from tracemind.core.models import ParsedLog
from tracemind.diagnosis.evidence import RunResult
from tracemind.diagnosis.state import RuntimeState
from tracemind.workspace.paths import resolve_under_root

_SCHEMA_VERSION = "0.1"
_REPO_REF_RE = re.compile(
    r"^repo://(?P<path>.+?)#L(?P<start>\d+)-L(?P<end>\d+)$"
)
_LOG_FILE_REF_RE = re.compile(
    r"^log://(?P<path>.+?)#L(?P<start>\d+)-L(?P<end>\d+)$"
)

_TEMPLATE_ENV = Environment(
    loader=PackageLoader("tracemind.diagnosis", "templates"),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


class ReportRootCause(BaseModel):
    """A root-cause candidate rendered in a report."""

    hypothesis_id: str
    statement: str
    status: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class ReportSource(BaseModel):
    """A source reference and its verification state."""

    source_ref: str
    kind: str
    verified: bool = False


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
    """Result of deterministic reference and status checks."""

    citations_valid: bool = False
    evidence_ids_valid: bool = False
    status_consistent: bool = False
    errors: list[str] = Field(default_factory=list)


class Report(BaseModel):
    """The JSON report schema for v0.1."""

    schema_version: str = _SCHEMA_VERSION
    incident_id: str
    run_id: str
    service: str
    status: str
    summary: str
    root_causes: list[ReportRootCause] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    tool_calls: list[ReportToolCall] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    stop: ReportStop
    budget_usage: dict[str, int] = Field(default_factory=dict)
    validation: ReportValidation = Field(default_factory=ReportValidation)


def report_status(result: RunResult) -> str:
    """Map runtime state/hypothesis status to the report status."""
    statuses = {hypothesis.status for hypothesis in result.hypotheses}

    if result.state is RuntimeState.FAILED:
        return "insufficient_data"
    if "confirmed" in statuses:
        return "confirmed"
    if (
        result.state is RuntimeState.STOPPED_BUDGET
        and "supported" in statuses
    ):
        return "probable"
    if result.state is RuntimeState.INSUFFICIENT_DATA:
        return "insufficient_data"
    if "supported" in statuses:
        return "probable"
    return "insufficient_data"


def build_report(
    result: RunResult,
    parsed_log: ParsedLog,
    repo_root: Path,
) -> Report:
    """Build and validate a report from one runtime result."""
    status = report_status(result)
    evidence_by_id = {item.evidence_id: item for item in result.evidence}
    sources: dict[str, ReportSource] = {}

    for item in result.evidence:
        sources.setdefault(
            item.source_ref,
            ReportSource(
                source_ref=item.source_ref,
                kind=item.kind,
                verified=False,
            ),
        )

    root_causes: list[ReportRootCause] = []
    for hypothesis in result.hypotheses:
        source_refs: list[str] = []
        for evidence_id in hypothesis.evidence_ids:
            evidence_item = evidence_by_id.get(evidence_id)
            if (
                evidence_item is not None
                and evidence_item.source_ref not in source_refs
            ):
                source_refs.append(evidence_item.source_ref)
        root_causes.append(
            ReportRootCause(
                hypothesis_id=hypothesis.hypothesis_id,
                statement=hypothesis.statement,
                status=hypothesis.status,
                evidence_ids=list(hypothesis.evidence_ids),
                source_refs=source_refs,
                missing_evidence=list(hypothesis.missing_evidence),
            )
        )

    limitations = list(result.limitations)
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

    top = next(
        (
            hypothesis
            for hypothesis in result.hypotheses
            if hypothesis.status in {"confirmed", "supported"}
        ),
        None,
    )
    summary = (
        f"{status}: {top.statement} "
        f"({len(top.evidence_ids)} evidence IDs, {len(result.tool_calls)} tool calls)."
        if top is not None
        else "No supported root cause candidate was produced."
    )

    report = Report(
        incident_id=result.incident_id,
        run_id=result.run_id,
        service=result.service,
        status=status,
        summary=summary,
        root_causes=root_causes,
        sources=list(sources.values()),
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
    """Validate citations and evidence IDs, downgrading unsafe reports."""
    citation_errors: list[str] = []
    evidence_errors: list[str] = []
    status_errors: list[str] = []
    evidence_ids = {item.evidence_id for item in result.evidence}

    for source in report.sources:
        valid, error = _check_source_ref(source.source_ref, parsed_log, repo_root)
        source.verified = valid
        if not valid:
            citation_errors.append(
                f"invalid source reference {source.source_ref}: {error}"
            )

    for root_cause in report.root_causes:
        for evidence_id in root_cause.evidence_ids:
            if evidence_id not in evidence_ids:
                evidence_errors.append(f"missing evidence id {evidence_id}")
        for source_ref in root_cause.source_refs:
            matched_source = next(
                (
                    item
                    for item in report.sources
                    if item.source_ref == source_ref
                ),
                None,
            )
            if matched_source is None or not matched_source.verified:
                citation_errors.append(
                    f"root cause references unverified source {source_ref}"
                )

    citations_valid = not citation_errors
    evidence_ids_valid = not evidence_errors
    expected_status = report_status(result)
    status_consistent = report.status == expected_status

    if not status_consistent:
        status_errors.append(
            f"report status {report.status} does not match runtime status "
            f"{expected_status}"
        )
        if report.status == "confirmed":
            report.status = "probable"
        else:
            report.status = "insufficient_data"
        status_consistent = False

    if not citations_valid or not evidence_ids_valid:
        if report.status != "insufficient_data":
            report.status = "insufficient_data"
            _append_limitation(
                report.limitations,
                "Report validation failed; status was downgraded.",
            )
        status_consistent = False

    report.validation = ReportValidation(
        citations_valid=citations_valid,
        evidence_ids_valid=evidence_ids_valid,
        status_consistent=status_consistent,
        errors=[*citation_errors, *evidence_errors, *status_errors],
    )
    return report


def render_markdown(report: Report) -> str:
    """Render a deterministic human-readable report from the Jinja2 template."""
    template = _TEMPLATE_ENV.get_template("report.md.j2")
    return template.render(report=report)


def _check_source_ref(
    source_ref: str,
    parsed_log: ParsedLog,
    repo_root: Path,
) -> tuple[bool, str]:
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
            int(repo_match.group("end")),
            len(lines),
        )

    log_file_match = _LOG_FILE_REF_RE.fullmatch(source_ref)
    if log_file_match is not None:
        input_path = Path(parsed_log.source_file)
        target = Path(log_file_match.group("path"))
        if not target.is_absolute():
            target = input_path.parent / target
        try:
            if target.resolve() != input_path.resolve():
                return False, "log file does not match the input log"
        except OSError:
            return False, "log file is not resolvable"
        lines = _read_lines(input_path)
        if lines is None:
            return False, "log file is not readable"
        return _check_range(
            int(log_file_match.group("start")),
            int(log_file_match.group("end")),
            len(lines),
        )

    if source_ref.startswith("log://"):
        event_id = source_ref.removeprefix("log://")
        if any(event.event_id == event_id for event in parsed_log.events):
            return True, ""
        return False, "log event does not exist"

    return False, "unsupported source reference"


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
