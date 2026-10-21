"""Unit tests for the tool registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from tracemind.tools.contracts import ToolContext, ToolHandlerResult, ToolSpec
from tracemind.tools.registry import ToolRegistry


class EchoArgs(BaseModel):
    text: str


def _echo(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    return ToolHandlerResult(data={"text": getattr(args, "text", "")})


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description="echo tool", input_model=EchoArgs)


def test_register_and_get() -> None:
    registry = ToolRegistry()
    registry.register(_spec("demo.echo"), _echo)

    registered = registry.get("demo.echo")

    assert registered is not None
    assert registered.spec.name == "demo.echo"
    assert registered.spec.read_only is True
    assert registry.get("missing") is None


def test_duplicate_registration_raises() -> None:
    registry = ToolRegistry()
    registry.register(_spec("demo.echo"), _echo)

    with pytest.raises(ValueError):
        registry.register(_spec("demo.echo"), _echo)


def test_list_tools_is_sorted() -> None:
    registry = ToolRegistry()
    registry.register(_spec("demo.zeta"), _echo)
    registry.register(_spec("demo.alpha"), _echo)

    assert [tool.name for tool in registry.list_tools()] == [
        "demo.alpha",
        "demo.zeta",
    ]
