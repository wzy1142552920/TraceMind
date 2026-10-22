"""Tool contracts and shared models."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from tracemind.core.models import ParsedLog
from tracemind.indexing.java_index import JavaIndex

if TYPE_CHECKING:
    from tracemind.diagnosis.workspace import DiagnosisWorkspace
    from tracemind.verification import ReadOnlyVerificationBackend


class ToolErrorCode(StrEnum):
    """Stable error codes returned by the tool executor."""

    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    TARGET_DENIED = "TARGET_DENIED"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    DUPLICATE_CALL = "DUPLICATE_CALL"
    TOOL_ERROR = "TOOL_ERROR"
    HYPOTHESIS_NOT_GROUNDED = "HYPOTHESIS_NOT_GROUNDED"
    INVALID_BINDING = "INVALID_BINDING"
    INVALID_ASSESSMENT = "INVALID_ASSESSMENT"
    INVALID_REMEDIATION = "INVALID_REMEDIATION"


class EvidenceToolMeta(BaseModel):
    """Optional binding metadata accepted by evidence-producing tools."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str | None = None
    requirement_id: str | None = None


class ToolRequest(BaseModel):
    """A request to execute one registered tool."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str


class ToolResult(BaseModel):
    """The normalized result of one tool call."""

    ok: bool
    tool_name: str
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    source_ref: str | None = None
    bound_hypothesis_id: str | None = None
    bound_requirement_id: str | None = None
    duration_ms: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class ToolSpec:
    """Static metadata and input schema for a tool."""

    name: str
    description: str
    input_model: type[BaseModel]
    read_only: bool = True
    max_output_bytes: int = 32768
    requires_approval: bool = False


@dataclass
class ToolHandlerResult:
    """A successful handler result before executor sanitization."""

    data: Any
    source_ref: str | None = None
    truncated: bool = False


class ToolError(Exception):
    """A controlled tool failure with a stable error code."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolContext:
    """Read-only context available to local tools."""

    parsed_log: ParsedLog | None = None
    java_index: JavaIndex | None = None
    repo_root: Path | None = None
    log_root: Path | None = None
    workspace: DiagnosisWorkspace | None = None
    verification_backend: ReadOnlyVerificationBackend | None = None


ToolHandler = Callable[[ToolContext, BaseModel], ToolHandlerResult]


class AuditEvent(BaseModel):
    """An in-memory audit record for one tool execution attempt."""

    timestamp: str
    run_id: str
    tool_call_id: str
    tool_name: str
    args_hash: str
    outcome: str
    error_code: str | None = None
    duration_ms: int
    source_ref: str | None = None
    bound_hypothesis_id: str | None = None
    bound_requirement_id: str | None = None
