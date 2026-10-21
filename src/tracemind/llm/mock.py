"""Deterministic scripted provider for tests and offline demos."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
    ToolDefinition,
)
from tracemind.llm.provider import LLMProviderError
from tracemind.llm.schemas import MockScript


class MockProvider:
    """Return a scripted response sequence without network access."""

    def __init__(
        self,
        responses: Sequence[LLMResponse | dict[str, Any]],
    ) -> None:
        self._responses = [
            response
            if isinstance(response, LLMResponse)
            else LLMResponse.model_validate(response)
            for response in responses
        ]
        self._index = 0

    @classmethod
    def from_script(cls, path: Path | str) -> MockProvider:
        script_path = Path(path)
        try:
            data = json.loads(script_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise LLMProviderError(
                f"cannot read mock script {script_path}: {exc}",
                code="invalid_mock_script",
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"invalid JSON in mock script {script_path}: {exc}",
                code="invalid_mock_script",
            ) from exc

        try:
            script = MockScript.model_validate(data)
        except Exception as exc:
            raise LLMProviderError(
                f"invalid mock script {script_path}: {exc}",
                code="invalid_mock_script",
            ) from exc
        return cls(script.responses)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=True,
            parallel_tool_calls=True,
        )

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        if self._index >= len(self._responses):
            return LLMResponse(finish_reason="stop")
        response = self._responses[self._index].model_copy(deep=True)
        self._index += 1
        return response
