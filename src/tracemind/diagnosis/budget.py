"""Budget limits and usage accounting for one diagnosis run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    """Deterministic limits enforced by the runtime."""

    max_iterations: int = 6
    max_llm_calls: int = 12
    max_tool_calls: int = 8
    max_same_tool_same_args: int = 1
    per_tool_timeout_seconds: int = 5
    max_output_bytes: int = 32768


@dataclass
class BudgetUsage:
    """Mutable usage counters for one run."""

    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "iterations": self.iterations,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
        }
