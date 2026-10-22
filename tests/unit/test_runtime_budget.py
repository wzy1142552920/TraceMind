"""Unit tests for budget defaults and usage accounting."""

from __future__ import annotations

from tracemind.diagnosis.budget import Budget, BudgetUsage


def test_budget_defaults() -> None:
    budget = Budget()

    assert budget.max_iterations == 10
    assert budget.max_llm_calls == 12
    assert budget.max_tool_calls == 16
    assert budget.max_same_tool_same_args == 1
    assert budget.per_tool_timeout_seconds == 5
    assert budget.max_hypotheses == 6
    assert budget.max_requirements_per_hypothesis == 5
    assert budget.max_remediation_actions == 8
    assert budget.max_evidence_items == 80
    assert budget.max_output_bytes == 32768


def test_budget_usage_as_dict() -> None:
    usage = BudgetUsage(iterations=2, llm_calls=3, tool_calls=4)

    assert usage.as_dict() == {
        "iterations": 2,
        "llm_calls": 3,
        "tool_calls": 4,
        "hypotheses": 0,
        "assessments": 0,
        "remediation_actions": 0,
    }
