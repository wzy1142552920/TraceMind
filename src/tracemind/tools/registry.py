"""Tool registry for the TraceMind minimal loop."""

from __future__ import annotations

from dataclasses import dataclass

from tracemind.tools.contracts import ToolHandler, ToolSpec


@dataclass(frozen=True)
class RegisteredTool:
    """A tool specification paired with its handler."""

    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """Name-keyed registry of read-only tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return [self._tools[name].spec for name in sorted(self._tools)]
