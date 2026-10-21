"""Runtime states, stop reasons, and transition validation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuntimeState(StrEnum):
    """States of the v0.1 diagnosis runtime."""

    INGESTING = "INGESTING"
    SEEDING = "SEEDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    EVALUATING = "EVALUATING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STOPPED_BUDGET = "STOPPED_BUDGET"
    FAILED = "FAILED"


class StopReason(StrEnum):
    """Machine-readable reasons for terminating a run."""

    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    NO_PROGRESS = "no_progress"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


TERMINAL_STATES = frozenset(
    {
        RuntimeState.COMPLETED,
        RuntimeState.INSUFFICIENT_DATA,
        RuntimeState.STOPPED_BUDGET,
        RuntimeState.FAILED,
    }
)

VALID_TRANSITIONS: dict[RuntimeState, frozenset[RuntimeState]] = {
    RuntimeState.INGESTING: frozenset(
        {RuntimeState.SEEDING, RuntimeState.INSUFFICIENT_DATA, RuntimeState.FAILED}
    ),
    RuntimeState.SEEDING: frozenset(
        {
            RuntimeState.PLANNING,
            RuntimeState.INSUFFICIENT_DATA,
            RuntimeState.FAILED,
        }
    ),
    RuntimeState.PLANNING: frozenset(
        {
            RuntimeState.EXECUTING,
            RuntimeState.EVALUATING,
            RuntimeState.REPORTING,
            RuntimeState.INSUFFICIENT_DATA,
            RuntimeState.STOPPED_BUDGET,
            RuntimeState.FAILED,
        }
    ),
    RuntimeState.EXECUTING: frozenset(
        {
            RuntimeState.EVALUATING,
            RuntimeState.STOPPED_BUDGET,
            RuntimeState.FAILED,
        }
    ),
    RuntimeState.EVALUATING: frozenset(
        {
            RuntimeState.PLANNING,
            RuntimeState.REPORTING,
            RuntimeState.INSUFFICIENT_DATA,
            RuntimeState.STOPPED_BUDGET,
            RuntimeState.FAILED,
        }
    ),
    RuntimeState.REPORTING: frozenset(
        {
            RuntimeState.COMPLETED,
            RuntimeState.INSUFFICIENT_DATA,
            RuntimeState.FAILED,
        }
    ),
    RuntimeState.COMPLETED: frozenset(),
    RuntimeState.INSUFFICIENT_DATA: frozenset(),
    RuntimeState.STOPPED_BUDGET: frozenset(),
    RuntimeState.FAILED: frozenset(),
}


class InvalidStateTransition(ValueError):
    """Raised when the runtime attempts an invalid state transition."""


def is_terminal(state: RuntimeState) -> bool:
    """Return True for terminal runtime states."""
    return state in TERMINAL_STATES


def validate_transition(current: RuntimeState, new_state: RuntimeState) -> None:
    """Validate a state transition or raise a clear error."""
    if new_state not in VALID_TRANSITIONS[current]:
        raise InvalidStateTransition(
            f"invalid transition {current.value} -> {new_state.value}"
        )


class RuntimeEvent(BaseModel):
    """A structured event emitted by the runtime."""

    event_type: str
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)
