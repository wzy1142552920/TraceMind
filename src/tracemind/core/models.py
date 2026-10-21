"""Core Pydantic models for the TraceMind minimal loop."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StackFrame(BaseModel):
    """A single Java stack frame."""

    class_name: str
    method_name: str
    file_name: str | None = None
    line_number: int | None = None
    is_native: bool = False
    is_reflection: bool = False
    raw: str


class ExceptionCause(BaseModel):
    """A nested or suppressed exception attached to a log event."""

    kind: str = "caused_by"
    exception_type: str
    exception_message: str | None = None
    stack_frames: list[StackFrame] = Field(default_factory=list)


class LogEvent(BaseModel):
    """A parsed log event, including its multi-line stack trace."""

    event_id: str
    source_file: str
    line_start: int
    line_end: int
    timestamp: str | None = None
    level: str | None = None
    thread: str | None = None
    logger: str | None = None
    message: str = ""
    exception_type: str | None = None
    exception_message: str | None = None
    stack_frames: list[StackFrame] = Field(default_factory=list)
    cause_chain: list[ExceptionCause] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class ParsedLog(BaseModel):
    """The result of parsing one text log file."""

    source_file: str
    events: list[LogEvent] = Field(default_factory=list)
    primary_event_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
