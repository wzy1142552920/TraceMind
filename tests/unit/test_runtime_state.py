"""Unit tests for runtime states and transition validation."""

from __future__ import annotations

import pytest

from tracemind.diagnosis.state import (
    TERMINAL_STATES,
    InvalidStateTransition,
    RuntimeState,
    StopReason,
    is_terminal,
    validate_transition,
)


def test_terminal_states() -> None:
    assert RuntimeState.COMPLETED in TERMINAL_STATES
    assert RuntimeState.INSUFFICIENT_DATA in TERMINAL_STATES
    assert RuntimeState.STOPPED_BUDGET in TERMINAL_STATES
    assert RuntimeState.FAILED in TERMINAL_STATES
    assert not is_terminal(RuntimeState.PLANNING)
    assert is_terminal(RuntimeState.COMPLETED)


def test_valid_transition_does_not_raise() -> None:
    validate_transition(RuntimeState.INGESTING, RuntimeState.SEEDING)
    validate_transition(RuntimeState.PLANNING, RuntimeState.EXECUTING)
    validate_transition(RuntimeState.EVALUATING, RuntimeState.REPORTING)
    validate_transition(RuntimeState.REPORTING, RuntimeState.COMPLETED)


def test_invalid_transition_raises() -> None:
    with pytest.raises(InvalidStateTransition):
        validate_transition(RuntimeState.COMPLETED, RuntimeState.PLANNING)

    with pytest.raises(InvalidStateTransition):
        validate_transition(RuntimeState.INGESTING, RuntimeState.EXECUTING)


def test_stop_reason_values() -> None:
    assert StopReason.EVIDENCE_SUFFICIENT.value == "evidence_sufficient"
    assert StopReason.NO_PROGRESS.value == "no_progress"
    assert StopReason.BUDGET_EXHAUSTED.value == "budget_exhausted"
    assert StopReason.ERROR.value == "error"
