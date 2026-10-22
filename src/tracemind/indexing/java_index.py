"""In-memory Java source index backed by tree-sitter-java."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Protocol

import tree_sitter_java
from pydantic import BaseModel, Field
from tree_sitter import Language, Node, Parser

from tracemind.core.errors import JavaIndexError
from tracemind.core.models import StackFrame

_CLASS_TYPES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
}
_METHOD_TYPES = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
}
_MODIFIER_KEYWORDS = {
    "public",
    "protected",
    "private",
    "static",
    "final",
    "abstract",
    "default",
    "native",
    "synchronized",
    "transient",
    "volatile",
    "strictfp",
    "sealed",
    "non-sealed",
}
_SQL_ANNOTATIONS = {
    "Select": "SELECT",
    "Insert": "INSERT",
    "Update": "UPDATE",
    "Delete": "DELETE",
}
_SQL_PROVIDER_ANNOTATIONS = {
    "SelectProvider",
    "InsertProvider",
    "UpdateProvider",
    "DeleteProvider",
}
_SKIPPED_CALL_CONTAINERS = {"lambda_expression", "method_reference"}
_CALL_RECEIVERS = {
    "identifier",
    "this",
    "super",
    "type_identifier",
    "scoped_identifier",
    "field_access",
}
_SKIP_DIRS = {".git", "target", "build", "out", "node_modules", "dist"}
_TABLE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([`\"\[]?[A-Za-z_][\w.$]*[`\"\]]?)",
    re.IGNORECASE,
)


class AnnotationInfo(BaseModel):
    """A Java annotation with simple literal arguments."""

    name: str
    arguments: dict[str, str] = Field(default_factory=dict)
    line: int


class JavaSymbol(BaseModel):
    """A class-like declaration or method/constructor in a Java repository."""

    symbol_id: str
    fqn: str
    class_name: str
    method_name: str | None = None
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int
    signature: str | None = None
    provenance: str
    annotations: list[AnnotationInfo] = Field(default_factory=list)
    parameter_count: int | None = None
    return_type: str | None = None
    modifiers: list[str] = Field(default_factory=list)


class JavaField(BaseModel):
    """A field declaration used to resolve injected receiver types."""

    owner_fqn: str
    name: str
    type_name: str
    annotations: list[AnnotationInfo] = Field(default_factory=list)
    start_line: int


class MethodCall(BaseModel):
    """A syntactic call site before symbol resolution."""

    caller_symbol_id: str
    receiver: str | None = None
    method_name: str
    argument_count: int
    line: int


class CallEdge(BaseModel):
    """One resolved candidate call edge derived from the AST."""

    caller_symbol_id: str
    caller_fqn: str
    callee_symbol_id: str
    callee_fqn: str
    file_path: str
    line: int
    receiver: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: str = "ast_heuristic"


class SqlArtifact(BaseModel):
    """SQL extracted from a MyBatis annotation."""

    symbol_id: str
    file_path: str
    start_line: int
    end_line: int
    sql_text: str
    statement_type: str
    tables: list[str] = Field(default_factory=list)
    provenance: str = "annotation_sql"


class SourceMatch(BaseModel):
    """A source location matched to a stack frame or symbol query."""

    symbol: JavaSymbol
    file_path: str
    start_line: int
    end_line: int
    matched_line: int | None = None
    confidence: float
    match_reason: str
    provenance: str


class SourceSnippet(BaseModel):
    """A line-numbered source range returned to tools and reports."""

    file_path: str
    start_line: int
    end_line: int
    text: str
    truncated: bool = False


class IndexStats(BaseModel):
    """Summary of one indexing run."""

    repo_path: str
    parser: str
    files_indexed: int = 0
    symbols_indexed: int = 0
    errors: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class JavaIndex(Protocol):
    """Minimal Java source index contract."""

    def index(self, repo_path: Path) -> IndexStats: ...

    def find_symbol(self, query: str, limit: int = 10) -> list[JavaSymbol]: ...

    def get_symbol(self, symbol_id: str) -> JavaSymbol | None: ...

    def get_fields(self, owner_fqn: str) -> list[JavaField]: ...

    def get_callers(self, symbol_id: str) -> list[CallEdge]: ...

    def get_callees(self, symbol_id: str) -> list[CallEdge]: ...

    def find_sql(self, query: str) -> list[SqlArtifact]: ...

    def resolve_frame(self, frame: StackFrame) -> list[SourceMatch]: ...

    def get_source_range(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> SourceSnippet: ...


@dataclass
class _FileInfo:
    package: str = ""
    imports: dict[str, str] = dataclass_field(default_factory=dict)
    static_imports: dict[str, str] = dataclass_field(default_factory=dict)


class TreeSitterJavaIndex:
    """Single-repository in-memory index using tree-sitter-java."""

    def __init__(self) -> None:
        language = Language(tree_sitter_java.language())
        self._parser = Parser(language)
        self._repo_path: Path | None = None
        self._symbols: list[JavaSymbol] = []
        self._fields: list[JavaField] = []
        self._calls: list[MethodCall] = []
        self._call_edges: list[CallEdge] = []
        self._sql_artifacts: list[SqlArtifact] = []
        self._file_info: dict[str, _FileInfo] = {}
        self._parse_warnings: list[str] = []
        self._next_symbol = 0
        self._files_indexed = 0

    def index(self, repo_path: Path) -> IndexStats:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise JavaIndexError(f"repository is not a directory: {repo}")

        self._repo_path = repo
        self._symbols = []
        self._fields = []
        self._calls = []
        self._call_edges = []
        self._sql_artifacts = []
        self._file_info = {}
        self._parse_warnings = []
        self._next_symbol = 0
        self._files_indexed = 0

        stats = IndexStats(repo_path=str(repo), parser="tree_sitter")
        for path in sorted(repo.rglob("*.java")):
            relative = path.relative_to(repo)
            if any(part in _SKIP_DIRS for part in relative.parts):
                continue
            relative_path = relative.as_posix()
            try:
                source = path.read_bytes()
                source.decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                stats.errors.append(f"{relative_path}: {exc}")
                continue

            try:
                tree = self._parser.parse(source)
                package = _package_name(tree.root_node)
                self._file_info[relative_path] = _file_info(
                    tree.root_node,
                    package,
                )
                for child in tree.root_node.named_children:
                    self._walk(child, package, [], relative_path)
            except Exception as exc:  # keep indexing best-effort
                stats.errors.append(f"{relative_path}: {exc}")
                continue

            self._files_indexed += 1

        self._resolve_calls()

        stats.files_indexed = self._files_indexed
        stats.symbols_indexed = len(self._symbols)
        stats.parse_warnings = list(self._parse_warnings)
        return stats

    def find_symbol(self, query: str, limit: int = 10) -> list[JavaSymbol]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        scored = [
            (score, symbol)
            for symbol in self._symbols
            if (score := _match_score(symbol, normalized))
        ]
        if not scored and "." in normalized:
            simple = normalized.rsplit(".", 1)[-1]
            class_matches = [
                symbol
                for symbol in self._symbols
                if symbol.method_name is None
                and symbol.class_name.lower() == simple
            ]
            scored = [(100, symbol) for symbol in class_matches]

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].file_path,
                item[1].start_line,
                item[1].symbol_id,
            )
        )
        return [symbol for _, symbol in scored[: max(1, min(limit, 50))]]

    def get_symbol(self, symbol_id: str) -> JavaSymbol | None:
        return next(
            (symbol for symbol in self._symbols if symbol.symbol_id == symbol_id),
            None,
        )

    def get_fields(self, owner_fqn: str) -> list[JavaField]:
        return [
            field for field in self._fields if field.owner_fqn == owner_fqn
        ]

    def get_callers(self, symbol_id: str) -> list[CallEdge]:
        return _sorted_edges(
            edge for edge in self._call_edges if edge.callee_symbol_id == symbol_id
        )

    def get_callees(self, symbol_id: str) -> list[CallEdge]:
        return _sorted_edges(
            edge for edge in self._call_edges if edge.caller_symbol_id == symbol_id
        )

    def find_sql(self, query: str) -> list[SqlArtifact]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        symbols = {symbol.symbol_id: symbol for symbol in self._symbols}
        matches: list[SqlArtifact] = []
        for artifact in self._sql_artifacts:
            symbol = symbols.get(artifact.symbol_id)
            searchable = [
                artifact.sql_text,
                artifact.statement_type,
                *artifact.tables,
            ]
            if symbol is not None:
                searchable.extend(
                    part
                    for part in (
                        symbol.fqn,
                        symbol.class_name,
                        symbol.method_name or "",
                    )
                    if part
                )
            if any(normalized in value.lower() for value in searchable):
                matches.append(artifact)
        matches.sort(
            key=lambda item: (
                item.file_path,
                item.start_line,
                item.symbol_id,
            )
        )
        return matches

    def resolve_frame(self, frame: StackFrame) -> list[SourceMatch]:
        frame_class = _normalize_class_name(frame.class_name)
        method_name = frame.method_name
        if method_name == "<init>":
            method_name = frame_class.rsplit(".", 1)[-1]

        method_matches: list[SourceMatch] = []
        for symbol in self._symbols:
            if symbol.method_name != method_name:
                continue
            if _normalize_class_name(symbol.fqn) != frame_class:
                continue
            if (
                frame.line_number is not None
                and symbol.start_line <= frame.line_number <= symbol.end_line
            ):
                method_matches.append(
                    self._source_match(symbol, frame, 0.95, "fqn_method_line")
                )
            else:
                method_matches.append(
                    self._source_match(symbol, frame, 0.70, "fqn_method")
                )

        if method_matches:
            return _sort_matches(method_matches)

        class_matches = [
            self._source_match(symbol, frame, 0.60, "fqn")
            for symbol in self._symbols
            if symbol.method_name is None
            and _normalize_class_name(symbol.fqn) == frame_class
        ]
        if class_matches:
            return _sort_matches(class_matches)

        if frame.file_name:
            file_name = Path(frame.file_name).name
            file_matches = [
                self._source_match(symbol, frame, 0.50, "file_method")
                for symbol in self._symbols
                if symbol.method_name == method_name
                and Path(symbol.file_path).name == file_name
            ]
            if file_matches:
                return _sort_matches(file_matches)

        return []

    def get_source_range(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> SourceSnippet:
        if self._repo_path is None:
            raise JavaIndexError("index has not been built")

        root = self._repo_path
        target = (root / file_path).resolve()
        if not target.is_relative_to(root):
            raise JavaIndexError(f"source path escapes repository: {file_path}")
        if not target.is_file():
            raise JavaIndexError(f"source file not found: {file_path}")

        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise JavaIndexError(f"cannot read source file {file_path}: {exc}") from exc

        relative_path = target.relative_to(root).as_posix()
        if not lines:
            return SourceSnippet(
                file_path=relative_path,
                start_line=1,
                end_line=0,
                text="",
                truncated=True,
            )

        safe_start = max(1, min(start_line, len(lines)))
        safe_end = max(safe_start, min(end_line, len(lines)))
        truncated = safe_start != start_line or safe_end != end_line
        numbered = "\n".join(
            f"{number:>4}: {lines[number - 1]}"
            for number in range(safe_start, safe_end + 1)
        )
        return SourceSnippet(
            file_path=relative_path,
            start_line=safe_start,
            end_line=safe_end,
            text=numbered,
            truncated=truncated,
        )

    def _walk(
        self,
        node: Node,
        package: str,
        class_stack: list[str],
        file_path: str,
    ) -> None:
        class_type = _CLASS_TYPES.get(node.type)
        if class_type is not None:
            name = _node_name(node)
            if name is not None:
                new_stack = [*class_stack, name]
                self._add_symbol(
                    fqn=_class_fqn(package, new_stack),
                    class_name=name,
                    method_name=None,
                    symbol_type=class_type,
                    file_path=file_path,
                    node=node,
                    signature=name,
                )
                body = _body_node(node)
                if body is not None:
                    for child in body.named_children:
                        self._walk(child, package, new_stack, file_path)
            return

        method_type = _METHOD_TYPES.get(node.type)
        if method_type is not None:
            if class_stack:
                name = _node_name(node)
                if name is not None:
                    symbol = self._add_symbol(
                        fqn=_class_fqn(package, class_stack),
                        class_name=class_stack[-1],
                        method_name=name,
                        symbol_type=method_type,
                        file_path=file_path,
                        node=node,
                        signature=_header_text(node),
                    )
                    if symbol is not None:
                        self._add_sql_artifacts(symbol)
                        body = _body_node(node)
                        if body is not None:
                            self._collect_calls(body, symbol)
            return

        if node.type == "field_declaration":
            if class_stack:
                self._add_field(
                    node,
                    owner_fqn=_class_fqn(package, class_stack),
                )
            return

        for child in node.named_children:
            self._walk(child, package, class_stack, file_path)

    def _add_symbol(
        self,
        *,
        fqn: str,
        class_name: str,
        method_name: str | None,
        symbol_type: str,
        file_path: str,
        node: Node,
        signature: str,
    ) -> JavaSymbol | None:
        self._next_symbol += 1
        annotations = _annotations(node)
        symbol = JavaSymbol(
            symbol_id=f"sym_{self._next_symbol:04d}",
            fqn=fqn,
            class_name=class_name,
            method_name=method_name,
            symbol_type=symbol_type,
            file_path=file_path,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            signature=signature,
            provenance="tree_sitter",
            annotations=annotations,
            parameter_count=(
                _parameter_count(node)
                if symbol_type in {"method", "constructor"}
                else None
            ),
            return_type=(
                _node_text(node.child_by_field_name("type"))
                if symbol_type == "method"
                else None
            ),
            modifiers=_modifiers(node),
        )
        self._symbols.append(symbol)
        return symbol

    def _add_field(self, node: Node, *, owner_fqn: str) -> None:
        type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        if type_node is None or declarator is None:
            return
        name_node = _declarator_name(declarator)
        type_name = _node_text(type_node)
        if not type_name:
            return
        self._fields.append(
            JavaField(
                owner_fqn=owner_fqn,
                name=name_node,
                type_name=type_name,
                annotations=_annotations(node),
                start_line=node.start_point.row + 1,
            )
        )

    def _add_sql_artifacts(self, symbol: JavaSymbol) -> None:
        for annotation in symbol.annotations:
            if annotation.name in _SQL_PROVIDER_ANNOTATIONS:
                self._parse_warnings.append(
                    f"{symbol.file_path}:{annotation.line}: "
                    f"@{annotation.name} is not supported"
                )
                continue
            statement_type = _SQL_ANNOTATIONS.get(annotation.name)
            if statement_type is None:
                continue
            sql_text = annotation.arguments.get("value")
            if not sql_text:
                self._parse_warnings.append(
                    f"{symbol.file_path}:{annotation.line}: "
                    f"@{annotation.name} has no literal SQL argument"
                )
                continue
            self._sql_artifacts.append(
                SqlArtifact(
                    symbol_id=symbol.symbol_id,
                    file_path=symbol.file_path,
                    start_line=annotation.line,
                    end_line=annotation.line,
                    sql_text=sql_text,
                    statement_type=statement_type,
                    tables=_sql_tables(sql_text),
                )
            )

    def _collect_calls(self, node: Node, caller: JavaSymbol) -> None:
        if node.type in _SKIPPED_CALL_CONTAINERS:
            return
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            arguments = node.child_by_field_name("arguments")
            receiver_node = node.child_by_field_name("object")
            receiver: str | None = None
            if receiver_node is not None and receiver_node.type in _CALL_RECEIVERS:
                receiver = _node_text(receiver_node) or None
            method_name = _node_text(name_node)
            if method_name:
                self._calls.append(
                    MethodCall(
                        caller_symbol_id=caller.symbol_id,
                        receiver=receiver,
                        method_name=method_name,
                        argument_count=(
                            len(arguments.named_children)
                            if arguments is not None
                            else 0
                        ),
                        line=(
                            name_node.start_point.row + 1
                            if name_node is not None
                            else node.start_point.row + 1
                        ),
                    )
                )
        for child in node.named_children:
            self._collect_calls(child, caller)

    def _resolve_calls(self) -> None:
        methods_by_class: dict[str, list[JavaSymbol]] = {}
        symbols = {symbol.symbol_id: symbol for symbol in self._symbols}
        methods = [
            symbol
            for symbol in self._symbols
            if symbol.symbol_type in {"method", "constructor"}
        ]
        class_fqns = {
            symbol.fqn
            for symbol in self._symbols
            if symbol.symbol_type != "method" and symbol.method_name is None
        }
        for symbol in methods:
            methods_by_class.setdefault(symbol.fqn, []).append(symbol)

        fields_by_owner: dict[str, dict[str, JavaField]] = {}
        for field in self._fields:
            fields_by_owner.setdefault(field.owner_fqn, {})[field.name] = field

        edges: dict[tuple[str, str, int, str | None], CallEdge] = {}
        for call in self._calls:
            caller = symbols.get(call.caller_symbol_id)
            if caller is None:
                continue
            info = self._file_info.get(caller.file_path, _FileInfo())
            candidates, confidence = _resolve_call_candidates(
                call,
                caller,
                info,
                methods_by_class,
                fields_by_owner,
                class_fqns,
                methods,
            )
            for candidate in candidates:
                key = (
                    caller.symbol_id,
                    candidate.symbol_id,
                    call.line,
                    call.receiver,
                )
                edge = CallEdge(
                    caller_symbol_id=caller.symbol_id,
                    caller_fqn=caller.fqn,
                    callee_symbol_id=candidate.symbol_id,
                    callee_fqn=candidate.fqn,
                    file_path=caller.file_path,
                    line=call.line,
                    receiver=call.receiver,
                    confidence=confidence,
                )
                existing = edges.get(key)
                if existing is None or edge.confidence > existing.confidence:
                    edges[key] = edge
        self._call_edges = _sorted_edges(edges.values())

    def _source_match(
        self,
        symbol: JavaSymbol,
        frame: StackFrame,
        confidence: float,
        reason: str,
    ) -> SourceMatch:
        return SourceMatch(
            symbol=symbol,
            file_path=symbol.file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            matched_line=frame.line_number,
            confidence=confidence,
            match_reason=reason,
            provenance=symbol.provenance,
        )


def _resolve_call_candidates(
    call: MethodCall,
    caller: JavaSymbol,
    info: _FileInfo,
    methods_by_class: dict[str, list[JavaSymbol]],
    fields_by_owner: dict[str, dict[str, JavaField]],
    class_fqns: set[str],
    methods: list[JavaSymbol],
) -> tuple[list[JavaSymbol], float]:
    fallback = _arity_candidates(methods, call.method_name, call.argument_count)
    receiver = call.receiver
    if receiver is None or receiver == "this":
        local = _arity_candidates(
            methods_by_class.get(caller.fqn, []),
            call.method_name,
            call.argument_count,
        )
        if local:
            return local, _confidence(0.90, len(local))
        if receiver is None:
            static_class = info.static_imports.get(call.method_name)
            if static_class is not None:
                candidates = _arity_candidates(
                    methods_by_class.get(static_class, []),
                    call.method_name,
                    call.argument_count,
                )
                if candidates:
                    return candidates, _confidence(0.65, len(candidates))
        return fallback, _confidence(0.40, len(fallback))

    if receiver == "super":
        return fallback, _confidence(0.40, len(fallback))

    field_name = receiver.rsplit(".", 1)[-1]
    field = fields_by_owner.get(caller.fqn, {}).get(field_name)
    if field is not None:
        target_fqn = _resolve_type(
            field.type_name,
            info,
            class_fqns,
        )
        if target_fqn is not None:
            candidates = _arity_candidates(
                methods_by_class.get(target_fqn, []),
                call.method_name,
                call.argument_count,
            )
            if candidates:
                return candidates, _confidence(0.75, len(candidates))

    target_fqn = _resolve_class_receiver(receiver, info, class_fqns)
    if target_fqn is not None:
        candidates = _arity_candidates(
            methods_by_class.get(target_fqn, []),
            call.method_name,
            call.argument_count,
        )
        if candidates:
            return candidates, _confidence(0.65, len(candidates))

    return fallback, _confidence(0.40, len(fallback))


def _arity_candidates(
    methods: list[JavaSymbol],
    method_name: str,
    argument_count: int,
) -> list[JavaSymbol]:
    return [
        method
        for method in methods
        if method.method_name == method_name
        and method.parameter_count == argument_count
    ]


def _confidence(base: float, candidate_count: int) -> float:
    if candidate_count > 1:
        return round(max(0.05, base - 0.10), 2)
    return base


def _resolve_type(
    type_name: str,
    info: _FileInfo,
    class_fqns: set[str],
) -> str | None:
    base = _base_type_name(type_name)
    if not base:
        return None
    if base in class_fqns:
        return base
    simple = base.rsplit(".", 1)[-1]
    candidates = [
        info.imports.get(simple),
        f"{info.package}.{simple}" if info.package else None,
        base if "." in base else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate in class_fqns:
            return candidate
    matches = [
        fqn
        for fqn in class_fqns
        if fqn.rsplit(".", 1)[-1] == simple
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _resolve_class_receiver(
    receiver: str,
    info: _FileInfo,
    class_fqns: set[str],
) -> str | None:
    if receiver in class_fqns:
        return receiver
    receiver = receiver.rsplit(".", 1)[-1]
    imported = info.imports.get(receiver)
    if imported is not None and imported in class_fqns:
        return imported
    same_package = f"{info.package}.{receiver}" if info.package else receiver
    if same_package in class_fqns:
        return same_package
    matches = [
        fqn
        for fqn in class_fqns
        if fqn.rsplit(".", 1)[-1] == receiver
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _base_type_name(type_name: str) -> str:
    text = type_name.strip()
    if "<" in text:
        text = text.split("<", 1)[0]
    text = text.replace("[]", "").replace("...", "").strip()
    return text


def _sorted_edges(edges: Iterable[CallEdge]) -> list[CallEdge]:
    return sorted(
        edges,
        key=lambda edge: (
            edge.file_path,
            edge.line,
            -edge.confidence,
            edge.callee_symbol_id,
        ),
    )


def _sort_matches(matches: list[SourceMatch]) -> list[SourceMatch]:
    return sorted(
        matches,
        key=lambda match: (
            -match.confidence,
            match.start_line,
            match.symbol.symbol_id,
        ),
    )


def _file_info(root: Node, package: str) -> _FileInfo:
    info = _FileInfo(package=package)
    for child in root.named_children:
        if child.type != "import_declaration":
            continue
        text = _node_text(child)
        if not text:
            continue
        imported = text.removeprefix("import").removesuffix(";").strip()
        is_static = imported.startswith("static ")
        if is_static:
            imported = imported.removeprefix("static ").strip()
        if not imported or imported.endswith(".*"):
            continue
        parts = imported.split(".")
        if is_static:
            if len(parts) >= 2:
                info.static_imports[parts[-1]] = ".".join(parts[:-1])
        else:
            info.imports[parts[-1]] = imported
    return info


def _annotations(node: Node) -> list[AnnotationInfo]:
    modifiers = next(
        (child for child in node.named_children if child.type == "modifiers"),
        None,
    )
    if modifiers is None:
        return []
    return [
        annotation
        for child in modifiers.named_children
        if child.type in {"annotation", "marker_annotation"}
        and (annotation := _annotation_info(child)) is not None
    ]


def _annotation_info(node: Node) -> AnnotationInfo | None:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node)
    if not name:
        return None
    arguments: dict[str, str] = {}
    args_node = node.child_by_field_name("arguments")
    if args_node is not None:
        for child in args_node.named_children:
            if child.type == "element_value_pair":
                key_node = child.child_by_field_name("key")
                value_node = child.child_by_field_name("value")
                key = _node_text(key_node)
                value = _annotation_literal(value_node)
                if key and value is not None:
                    arguments[key] = value
            else:
                value = _annotation_literal(child)
                if value is not None:
                    arguments["value"] = value
    return AnnotationInfo(
        name=name.rsplit(".", 1)[-1],
        arguments=arguments,
        line=node.start_point.row + 1,
    )


def _annotation_literal(node: Node | None) -> str | None:
    if node is None:
        return None
    if node.type == "element_value_array_initializer":
        for child in node.named_children:
            value = _annotation_literal(child)
            if value is not None:
                return value
        return None
    if node.type == "string_literal":
        raw = _node_text(node)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw.strip('"')
        return value if isinstance(value, str) else str(value)
    if node.type.endswith("_literal") or node.type in {"true", "false"}:
        return _node_text(node)
    return None


def _sql_tables(sql_text: str) -> list[str]:
    tables: list[str] = []
    for match in _TABLE_PATTERN.finditer(sql_text):
        table = match.group(1).strip("`\"[]")
        if table and table not in tables:
            tables.append(table)
    return tables


def _modifiers(node: Node) -> list[str]:
    modifiers = next(
        (child for child in node.named_children if child.type == "modifiers"),
        None,
    )
    if modifiers is None:
        return []
    return [
        child.type
        for child in modifiers.children
        if child.type in _MODIFIER_KEYWORDS
    ]


def _parameter_count(node: Node) -> int:
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        return 0
    return len(
        [
            child
            for child in parameters.named_children
            if child.type in {"formal_parameter", "spread_parameter"}
        ]
    )


def _declarator_name(node: Node) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node) or ""
    for child in node.named_children:
        if child.type == "identifier":
            return _node_text(child) or ""
    return ""


def _node_text(node: Node | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.decode("utf-8", errors="replace")


def _package_name(root: Node) -> str:
    for child in root.named_children:
        if child.type != "package_declaration":
            continue
        for named in child.named_children:
            if named.type in {"scoped_identifier", "identifier"}:
                return _node_text(named) or ""
    return ""


def _node_name(node: Node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        for child in node.named_children:
            if child.type == "identifier":
                name_node = child
                break
    return _node_text(name_node)


def _body_node(node: Node) -> Node | None:
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for child in node.named_children:
        if child.type.endswith("_body"):
            return child
    return None


def _header_text(node: Node) -> str:
    raw = node.text
    if raw is None:
        return ""
    text = raw.decode("utf-8", errors="replace")
    header = text.split("{", 1)[0]
    return " ".join(header.split())


def _class_fqn(package: str, class_stack: list[str]) -> str:
    nested = "$".join(class_stack)
    return f"{package}.{nested}" if package else nested


def _normalize_class_name(name: str) -> str:
    return name.rsplit("/", 1)[-1].replace("$", ".")


def _match_score(symbol: JavaSymbol, query: str) -> int:
    names = [
        symbol.fqn,
        symbol.class_name,
        symbol.fqn.replace("$", "."),
    ]
    if symbol.method_name:
        names.extend(
            [
                symbol.method_name,
                f"{symbol.class_name}.{symbol.method_name}",
                f"{symbol.fqn}.{symbol.method_name}",
                f"{symbol.fqn.replace('$', '.')}.{symbol.method_name}",
            ]
        )

    score = 0
    for name in names:
        lowered = name.lower()
        if lowered == query:
            return 100
        if query in lowered:
            score = max(score, 50)
    return score
