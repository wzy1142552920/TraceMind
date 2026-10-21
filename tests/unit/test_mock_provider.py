"""Unit tests for the deterministic mock provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracemind.llm.messages import Message
from tracemind.llm.mock import MockProvider
from tracemind.llm.provider import LLMProviderError

SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "mock_responses.json"


def test_scripted_responses() -> None:
    provider = MockProvider.from_script(SCRIPT)
    first = provider.complete(
        [Message(role="user", content="diagnose")],
        [],
    )

    assert first.finish_reason == "tool_calls"
    assert [call.id for call in first.tool_calls] == ["call_1", "call_2"]
    assert first.tool_calls[0].name == "code.find_symbol"
    assert first.tool_calls[0].arguments == {"query": "OrderService.updateStatus"}
    assert first.tool_calls[1].name == "logs.search"
    assert first.usage is not None
    assert first.usage.input_tokens == 100
    assert first.usage.output_tokens == 30

    second = provider.complete([], [])
    assert second.tool_calls == []
    assert second.finish_reason == "stop"

    exhausted = provider.complete([], [])
    assert exhausted.tool_calls == []
    assert exhausted.finish_reason == "stop"


def test_mock_provider_is_deterministic() -> None:
    first = MockProvider.from_script(SCRIPT).complete([], [])
    second = MockProvider.from_script(SCRIPT).complete([], [])

    assert first == second


def test_mock_provider_capabilities() -> None:
    provider = MockProvider([])

    assert provider.capabilities.tool_calling is True
    assert provider.capabilities.parallel_tool_calls is True


def test_invalid_mock_script(tmp_path: Path) -> None:
    script = tmp_path / "bad.json"
    script.write_text("{not-json", encoding="utf-8")

    with pytest.raises(LLMProviderError) as exc_info:
        MockProvider.from_script(script)

    assert exc_info.value.code == "invalid_mock_script"


def test_missing_mock_script(tmp_path: Path) -> None:
    with pytest.raises(LLMProviderError) as exc_info:
        MockProvider.from_script(tmp_path / "missing.json")

    assert exc_info.value.code == "invalid_mock_script"
