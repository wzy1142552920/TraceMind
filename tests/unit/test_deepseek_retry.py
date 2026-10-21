"""Fake-client tests for DeepSeek transport retries and error taxonomy."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.llm.provider import LLMProviderError


class ApiStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code
        self.request_id = "req_status"


class ScriptedCompletions:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
        self.calls = 0

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ScriptedClient:
    def __init__(self, items: list[Any]) -> None:
        self.completions = ScriptedCompletions(items)
        self.chat = SimpleNamespace(completions=self.completions)


def _success(
    *,
    content: str = "plan",
    arguments: str = '{"query": "rows=0"}',
) -> Any:
    function = SimpleNamespace(name="logs.search", arguments=arguments)
    tool_call = SimpleNamespace(id="call_1", function=function)
    message = SimpleNamespace(content=content, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[choice], usage=usage, id="resp_retry")


def _provider(
    items: list[Any],
    *,
    max_retries: int = 2,
) -> tuple[DeepSeekProvider, ScriptedClient, list[float]]:
    client = ScriptedClient(items)
    sleeps: list[float] = []
    provider = DeepSeekProvider(
        client=client,
        max_retries=max_retries,
        sleep=sleeps.append,
    )
    return provider, client, sleeps


def test_rate_limit_retries_then_succeeds() -> None:
    provider, client, sleeps = _provider([ApiStatusError(429), _success()])

    response = provider.complete([], [])

    assert response.attempts == 2
    assert client.completions.calls == 2
    assert sleeps == [0.5]


def test_server_error_retries_then_succeeds() -> None:
    provider, client, sleeps = _provider([ApiStatusError(503), _success()])

    response = provider.complete([], [])

    assert response.attempts == 2
    assert client.completions.calls == 2
    assert sleeps == [0.5]


def test_timeout_retries_then_succeeds() -> None:
    provider, client, sleeps = _provider([TimeoutError("slow"), _success()])

    response = provider.complete([], [])

    assert response.attempts == 2
    assert client.completions.calls == 2
    assert sleeps == [0.5]


def test_connection_error_retries_then_succeeds() -> None:
    provider, client, sleeps = _provider([ConnectionError("down"), _success()])

    response = provider.complete([], [])

    assert response.attempts == 2
    assert client.completions.calls == 2
    assert sleeps == [0.5]


def test_empty_response_retries_then_succeeds() -> None:
    empty = SimpleNamespace(choices=[], usage=None, id="resp_empty")
    provider, client, sleeps = _provider([empty, _success()])

    response = provider.complete([], [])

    assert response.attempts == 2
    assert client.completions.calls == 2
    assert sleeps == [0.5]


def test_auth_error_is_not_retried() -> None:
    provider, client, sleeps = _provider([ApiStatusError(401)])

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    error = exc_info.value
    assert error.code == "auth_error"
    assert error.retryable is False
    assert error.attempts == 1
    assert error.status_code == 401
    assert error.request_id == "req_status"
    assert client.completions.calls == 1
    assert sleeps == []


def test_bad_request_is_not_retried() -> None:
    provider, client, sleeps = _provider([ApiStatusError(400)])

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "bad_request"
    assert exc_info.value.retryable is False
    assert client.completions.calls == 1
    assert sleeps == []


def test_invalid_tool_arguments_are_not_retried() -> None:
    provider, client, sleeps = _provider(
        [_success(arguments="{not-json")]
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "invalid_tool_arguments"
    assert exc_info.value.retryable is False
    assert client.completions.calls == 1
    assert sleeps == []


def test_retries_exhausted() -> None:
    provider, client, sleeps = _provider(
        [TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")]
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    error = exc_info.value
    assert error.code == "timeout"
    assert error.retryable is True
    assert error.attempts == 3
    assert client.completions.calls == 3
    assert sleeps == [0.5, 1.0]


def test_max_retries_zero() -> None:
    provider, client, sleeps = _provider(
        [ApiStatusError(429)],
        max_retries=0,
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.complete([], [])

    assert exc_info.value.code == "rate_limit"
    assert exc_info.value.attempts == 1
    assert client.completions.calls == 1
    assert sleeps == []


def test_openai_client_is_configured_without_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("tracemind.llm.deepseek.OpenAI", FakeOpenAI)
    provider = DeepSeekProvider(timeout=7, max_retries=2)

    provider._get_client()

    assert captured["timeout"] == 7
    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["api_key"] == "test-key"
