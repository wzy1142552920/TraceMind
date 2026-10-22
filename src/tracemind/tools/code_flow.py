"""Read-only tools for AST-heuristic Java call-flow inspection."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, Field

from tracemind.indexing.java_index import CallEdge, JavaIndex, JavaSymbol
from tracemind.tools.contracts import (
    EvidenceToolMeta,
    ToolContext,
    ToolError,
    ToolErrorCode,
    ToolHandlerResult,
    ToolSpec,
)
from tracemind.tools.registry import ToolRegistry


class CodeGetSymbolArgs(EvidenceToolMeta):
    """Arguments for ``code.get_symbol``."""

    symbol_id: str = Field(min_length=1)


class CodeCallEdgesArgs(EvidenceToolMeta):
    """Arguments for ``code.get_callers`` and ``code.get_callees``."""

    symbol_id: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class CodeFindSqlArgs(EvidenceToolMeta):
    """Arguments for ``code.find_sql``."""

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=20)


def register_code_flow_tools(registry: ToolRegistry) -> None:
    """Register code-flow tools whose call edges are AST heuristics."""
    registry.register(
        ToolSpec(
            name="code.get_symbol",
            description=(
                "Return one indexed Java symbol by its indexed symbol_id "
                "(for example sym_0009), not an FQN. Use code.find_symbol "
                "first when you only know a class or method name. Call counts "
                "summarize AST-heuristic candidate edges."
            ),
            input_model=CodeGetSymbolArgs,
        ),
        _code_get_symbol,
    )
    registry.register(
        ToolSpec(
            name="code.get_callers",
            description=(
                "Return AST-heuristic candidate callers, not a runtime call graph. "
                "Every edge includes confidence and provenance."
            ),
            input_model=CodeCallEdgesArgs,
        ),
        _code_get_callers,
    )
    registry.register(
        ToolSpec(
            name="code.get_callees",
            description=(
                "Return AST-heuristic candidate callees, not a runtime call graph. "
                "Every edge includes confidence and provenance."
            ),
            input_model=CodeCallEdgesArgs,
        ),
        _code_get_callees,
    )
    registry.register(
        ToolSpec(
            name="code.find_sql",
            description=(
                "Find SQL from @Select/@Insert/@Update/@Delete annotations by "
                "SQL text, table, or symbol name."
            ),
            input_model=CodeFindSqlArgs,
        ),
        _code_find_sql,
    )


def _code_get_symbol(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeGetSymbolArgs, args)
    java_index = _require_java_index(context)
    symbol = _require_symbol(java_index, params.symbol_id)
    data = symbol.model_dump()
    data["source_ref"] = _repo_ref(
        symbol.file_path,
        symbol.start_line,
        symbol.end_line,
    )
    data["calls"] = {
        "callee_count": len(java_index.get_callees(symbol.symbol_id)),
        "caller_count": len(java_index.get_callers(symbol.symbol_id)),
    }
    return ToolHandlerResult(data=data, source_ref=data["source_ref"])


def _code_get_callers(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeCallEdgesArgs, args)
    java_index = _require_java_index(context)
    _require_symbol(java_index, params.symbol_id)
    return _edge_result(
        java_index.get_callers(params.symbol_id),
        params.limit,
    )


def _code_get_callees(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeCallEdgesArgs, args)
    java_index = _require_java_index(context)
    _require_symbol(java_index, params.symbol_id)
    return _edge_result(
        java_index.get_callees(params.symbol_id),
        params.limit,
    )


def _code_find_sql(context: ToolContext, args: BaseModel) -> ToolHandlerResult:
    params = cast(CodeFindSqlArgs, args)
    java_index = _require_java_index(context)
    artifacts = java_index.find_sql(params.query)
    items: list[dict[str, object]] = []
    for artifact in artifacts[: params.limit]:
        symbol = java_index.get_symbol(artifact.symbol_id)
        source_ref = _repo_line_ref(artifact.file_path, artifact.start_line)
        items.append(
            {
                "symbol_id": artifact.symbol_id,
                "fqn": symbol.fqn if symbol is not None else "",
                "statement_type": artifact.statement_type,
                "sql_text": artifact.sql_text,
                "tables": list(artifact.tables),
                "file_path": artifact.file_path,
                "start_line": artifact.start_line,
                "end_line": artifact.end_line,
                "source_ref": source_ref,
                "provenance": artifact.provenance,
            }
        )
    first_ref = (
        _repo_line_ref(artifacts[0].file_path, artifacts[0].start_line)
        if artifacts[: params.limit]
        else None
    )
    return ToolHandlerResult(
        data={"items": items, "count": len(items)},
        source_ref=first_ref,
        truncated=len(artifacts) > params.limit,
    )


def _edge_result(edges: list[CallEdge], limit: int) -> ToolHandlerResult:
    items = [
        {
            **edge.model_dump(),
            "source_ref": _repo_line_ref(edge.file_path, edge.line),
        }
        for edge in edges[:limit]
    ]
    return ToolHandlerResult(
        data={
            "items": items,
            "count": len(items),
            "provenance": "ast_heuristic",
        },
        source_ref=items[0]["source_ref"] if items else None,
        truncated=len(edges) > limit,
    )


def _require_java_index(context: ToolContext) -> JavaIndex:
    if context.java_index is None:
        raise ToolError(
            ToolErrorCode.TOOL_ERROR,
            "Java index context is not available",
        )
    return context.java_index


def _require_symbol(java_index: JavaIndex, symbol_id: str) -> JavaSymbol:
    symbol = java_index.get_symbol(symbol_id)
    if symbol is None:
        raise ToolError(
            ToolErrorCode.TARGET_DENIED,
            f"symbol_id not found: {symbol_id}; use code.find_symbol and "
            "pass the returned sym_* id, not an FQN",
        )
    return symbol


def _repo_ref(file_path: str, start_line: int, end_line: int) -> str:
    return f"repo://{file_path}#L{start_line}-L{end_line}"


def _repo_line_ref(file_path: str, line: int) -> str:
    return f"repo://{file_path}#L{line}"
