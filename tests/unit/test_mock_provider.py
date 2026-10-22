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
    assert [call.id for call in first.tool_calls] == [
        "call_1",
        "call_2",
        "call_3",
        "call_4",
        "call_5",
    ]
    assert first.tool_calls[0].name == "diagnosis_propose_hypothesis"
    assert first.tool_calls[2].name == "logs_get_thread_context"
    assert first.tool_calls[4].name == "code_find_sql"
    assert first.usage is not None
    assert first.usage.input_tokens == 100
    assert first.usage.output_tokens == 30

    second = provider.complete([], [])
    assert [call.id for call in second.tool_calls] == ["call_6"]
    assert second.finish_reason == "tool_calls"

    third = provider.complete([], [])
    assert [call.id for call in third.tool_calls] == ["call_7"]
    assert third.tool_calls[0].name == "diagnosis_propose_remediation"
    assert third.finish_reason == "tool_calls"

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
