"""Shared behavioral contract for all LLM providers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.llm.messages import LLMResponse, Message, ToolCall, ToolDefinition
from tracemind.llm.mock import MockProvider
from tracemind.llm.provider import LLMProvider

SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "mock_responses.json"


def _deepseek_provider() -> DeepSeekProvider:
    function = SimpleNamespace(name="logs.search", arguments='{"query": "x"}')
    tool_call = SimpleNamespace(id="call_x", function=function)
    message = SimpleNamespace(content="", tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    response = SimpleNamespace(choices=[choice], usage=None, id="resp_x")
    completions = SimpleNamespace(create=lambda **kwargs: response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return DeepSeekProvider(client=client)


def _assert_provider_contract(provider: LLMProvider) -> None:
    response = provider.complete(
        [Message(role="user", content="diagnose")],
        [ToolDefinition(name="logs.search")],
    )

    assert isinstance(response, LLMResponse)
    assert response.tool_calls
    assert isinstance(response.tool_calls[0], ToolCall)
    assert isinstance(response.tool_calls[0].arguments, dict)
    assert provider.capabilities.tool_calling is True


def test_mock_provider_satisfies_contract() -> None:
    _assert_provider_contract(MockProvider.from_script(SCRIPT))


def test_deepseek_provider_satisfies_contract() -> None:
    _assert_provider_contract(_deepseek_provider())
