"""DeepSeek provider using the OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
    ToolCall,
    ToolDefinition,
    Usage,
)
from tracemind.llm.provider import LLMProviderError


class DeepSeekProvider:
    """Synchronous DeepSeek provider with native tool calling."""

    def __init__(
        self,
        *,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com",
        api_key_env: str = "DEEPSEEK_API_KEY",
        temperature: float = 0.2,
        max_tokens: int = 4000,
        timeout: float = 60.0,
        max_retries: int = 2,
        thinking_enabled: bool = False,
        client: Any | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key_env = api_key_env
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max_retries
        self._thinking_enabled = thinking_enabled
        self._client = client
        self._sleep = sleep or time.sleep

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=True,
            parallel_tool_calls=True,
            prompt_caching=False,
        )

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_message_to_dict(message) for message in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = [_tool_to_dict(tool) for tool in tools]
        if not self._thinking_enabled:
            payload["extra_body"] = {"thinking": {"type": "disabled"}}

        attempt = 0
        while attempt <= self._max_retries:
            attempt += 1
            try:
                response = client.chat.completions.create(**payload)
                parsed = _parse_response(response)
            except LLMProviderError as exc:
                exc.attempts = attempt
                if exc.retryable and attempt <= self._max_retries:
                    self._sleep(_retry_delay(attempt))
                    continue
                raise
            except Exception as exc:
                error = _classify_exception(exc, attempt)
                if error.retryable and attempt <= self._max_retries:
                    self._sleep(_retry_delay(attempt))
                    continue
                raise error from exc

            parsed.attempts = attempt
            return parsed

        raise LLMProviderError(
            "DeepSeek request failed after retries",
            code="provider_error",
            attempts=attempt,
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise LLMProviderError(
                f"{self._api_key_env} is not set",
                code="missing_api_key",
                retryable=False,
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=0,
        )
        return self._client


def _message_to_dict(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    if message.tool_call_id is not None:
        data["tool_call_id"] = message.tool_call_id
    return data


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_response(response: Any) -> LLMResponse:
    choices = getattr(response, "choices", None)
    if not choices:
        raise LLMProviderError(
            "DeepSeek returned no choices",
            code="empty_response",
            retryable=True,
        )

    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise LLMProviderError(
            "DeepSeek response has no message",
            code="empty_response",
            retryable=True,
        )

    content = getattr(message, "content", None) or ""
    tool_calls: list[ToolCall] = []
    for raw_call in getattr(message, "tool_calls", None) or []:
        function = getattr(raw_call, "function", None)
        if function is None:
            continue
        name = str(getattr(function, "name", ""))
        arguments = _parse_arguments(name, getattr(function, "arguments", None))
        tool_calls.append(
            ToolCall(
                id=str(getattr(raw_call, "id", "")),
                name=name,
                arguments=arguments,
            )
        )

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=getattr(choice, "finish_reason", None),
        usage=_parse_usage(getattr(response, "usage", None)),
        raw_provider_id=getattr(response, "id", None),
    )


def _parse_arguments(name: str, raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw

    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LLMProviderError(
            f"invalid tool arguments for {name}: {exc}",
            code="invalid_tool_arguments",
            retryable=False,
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMProviderError(
            f"tool arguments for {name} must be a JSON object",
            code="invalid_tool_arguments",
            retryable=False,
        )
    return parsed


def _parse_usage(raw: Any) -> Usage | None:
    if raw is None:
        return None
    input_tokens = getattr(raw, "prompt_tokens", None)
    output_tokens = getattr(raw, "completion_tokens", None)
    total_tokens = getattr(raw, "total_tokens", None)
    if (
        total_tokens is None
        and input_tokens is not None
        and output_tokens is not None
    ):
        total_tokens = input_tokens + output_tokens
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


_RETRY_DELAYS = (0.5, 1.0)


def _retry_delay(attempt: int) -> float:
    if attempt <= len(_RETRY_DELAYS):
        return _RETRY_DELAYS[attempt - 1]
    return _RETRY_DELAYS[-1]


def _classify_exception(exc: Exception, attempt: int) -> LLMProviderError:
    status_code = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    name = type(exc).__name__.lower()

    if status_code == 429:
        code, retryable = "rate_limit", True
    elif status_code in (401, 403):
        code, retryable = "auth_error", False
    elif status_code in (400, 404, 422):
        code, retryable = "bad_request", False
    elif isinstance(status_code, int) and 500 <= status_code < 600:
        code, retryable = "server_error", True
    elif isinstance(exc, TimeoutError) or "timeout" in name:
        code, retryable = "timeout", True
    elif isinstance(exc, ConnectionError) or "connection" in name:
        code, retryable = "connection_error", True
    else:
        code, retryable = "provider_error", False

    return LLMProviderError(
        f"DeepSeek request failed: {exc}",
        code=code,
        retryable=retryable,
        attempts=attempt,
        status_code=status_code if isinstance(status_code, int) else None,
        request_id=request_id,
    )
