"""LLM provider protocol and normalized errors."""

from __future__ import annotations

from typing import Protocol

from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
    ToolDefinition,
)


class LLMProviderError(Exception):
    """A provider failure with a stable machine-readable code."""

    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class LLMProvider(Protocol):
    """Provider-neutral synchronous LLM contract."""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse: ...
