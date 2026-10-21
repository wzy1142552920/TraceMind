"""Contract tests for the DeepSeek OpenAI-compatible adapter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.llm.messages import Message, ToolDefinition
from tracemind.llm.provider import LLMProviderError


class FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: Any) -> None:
        self.completions = FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)


class FailingCompletions:
    def create(self, **kwargs: Any) -> Any:
        raise RuntimeError("upstream unavailable")


def _response(
    *,
    content: str | None = "plan",
    arguments: str = '{"query": "rows=0"}',
    with_usage: bool = True,
) -> Any:
    function = SimpleNamespace(name="logs.search", arguments=arguments)
    tool_call = SimpleNamespace(id="call_1", function=function)
    message = SimpleNamespace(content=content, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    usage = (
        SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        if with_usage
        else None
    )
    return SimpleNamespace(choices=[choice], usage=usage, id="resp_1")


def test_deepseek_maps_messages_tools_and_tool_calls() -> None:
    client = FakeClient(_response())
    provider = DeepSeekProvider(client=client)
    messages = [Message(role="user", content="diagnose")]
    tools = [
        ToolDefinition(
            name="logs.search",
            description="search logs",
            parameters={"type": "object"},
        )
    ]

    result = provider.complete(messages, tools)

    assert result.content == "plan"
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "logs.search"
    assert result.tool_calls[0].arguments == {"query": "rows=0"}
    assert result.finish_reason == "tool_calls"
    assert result.usage is not None
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.raw_provider_id == "resp_1"

    call = client.completions.calls[0]
    assert call["model"] == "deepseek-flash"
    assert call["messages"] == [{"role": "user", "content": "diagnose"}]
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "logs.search",
                "description": "search logs",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_deepseek_disables_thinking_by_default() -> None:
    client = FakeClient(_response())
    provider = DeepSeekProvider(client=client)

    provider.complete([], [])

    call = client.completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}


def test_deepseek_can_enable_thinking() -> None:
    client = FakeClient(_response())
    provider = DeepSeekProvider(client=client, thinking_enabled=True)

    provider.complete([], [])

    call = client.completions.calls[0]
    assert "extra_body" not in call


def test_deepseek_uses_configured_model_and_tokens() -> None:
    client = FakeClient(_response())
    provider = DeepSeekProvider(
        model="custom-model",
        max_tokens=123,
        timeout=5,
        max_retries=1,
        client=client,
    )

    provider.complete([Message(role="user", content="diagnose")], [])

    call = client.completions.calls[0]
    assert call["model"] == "custom-model"
    assert call["max_tokens"] == 123


def test_deepseek_omits_tools_when_empty() -> None:
    client = FakeClient(_response())
    provider = DeepSeekProvider(client=client)

    provider.complete([Message(role="user", content="diagnose")], [])

    assert "tools" not in client.completions.calls[0]


def test_deepseek_handles_missing_content_and_usage() -> None:
    provider = DeepSeekProvider(
        client=FakeClient(_response(content=None, with_usage=False))
    )

    result = provider.complete([], [])

    assert result.content == ""
    assert result.usage is None


def test_deepseek_invalid_tool_arguments() -> None:
    provider = DeepSeekProvider(client=FakeClient(_response(arguments="{not-json")))

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "invalid_tool_arguments"


def test_deepseek_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    provider = DeepSeekProvider()

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "missing_api_key"


def test_deepseek_empty_response() -> None:
    response = SimpleNamespace(choices=[], usage=None, id="resp_empty")
    provider = DeepSeekProvider(client=FakeClient(response))

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "empty_response"


def test_deepseek_wraps_provider_errors() -> None:
    client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    provider = DeepSeekProvider(client=client)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "provider_error"
