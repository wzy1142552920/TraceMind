"""Schemas for scripted mock responses."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tracemind.llm.messages import LLMResponse


class MockScript(BaseModel):
    """A deterministic sequence of provider responses."""

    responses: list[LLMResponse] = Field(default_factory=list)
