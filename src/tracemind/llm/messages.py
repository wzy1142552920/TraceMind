"""Provider-neutral LLM message and response types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class Message(BaseModel):
    """One provider-neutral chat message."""

    role: Role
    content: str = ""
    tool_call_id: str | None = None


class ToolDefinition(BaseModel):
    """A tool exposed to the model."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """A normalized tool call returned by a provider."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Token usage reported by a provider."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LLMResponse(BaseModel):
    """A normalized model response."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    raw_provider_id: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capabilities used by the runtime to degrade gracefully."""

    tool_calling: bool = True
    parallel_tool_calls: bool = False
    context_window: int | None = None
    prompt_caching: bool = False
