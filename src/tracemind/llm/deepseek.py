"""DeepSeek provider using the OpenAI-compatible API."""

from __future__ import annotations

import json
import os
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

        try:
            response = client.chat.completions.create(**payload)
        except Exception as exc:
            raise LLMProviderError(
                f"DeepSeek request failed: {exc}",
                code="provider_error",
            ) from exc
        return _parse_response(response)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise LLMProviderError(
                f"{self._api_key_env} is not set",
                code="missing_api_key",
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=self._timeout,
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
        )

    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise LLMProviderError(
            "DeepSeek response has no message",
            code="empty_response",
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
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMProviderError(
            f"tool arguments for {name} must be a JSON object",
            code="invalid_tool_arguments",
        )
    return parsed


def _parse_usage(raw: Any) -> Usage | None:
    if raw is None:
        return None
    return Usage(
        input_tokens=getattr(raw, "prompt_tokens", None),
        output_tokens=getattr(raw, "completion_tokens", None),
    )
