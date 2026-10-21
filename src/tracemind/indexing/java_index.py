"""In-memory Java source index backed by tree-sitter-java."""

from __future__ import annotations

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
_SKIP_DIRS = {".git", "target", "build", "out", "node_modules", "dist"}


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


class JavaIndex(Protocol):
    """Minimal Java source index contract for v0.1."""

    def index(self, repo_path: Path) -> IndexStats: ...

    def find_symbol(self, query: str, limit: int = 10) -> list[JavaSymbol]: ...

    def resolve_frame(self, frame: StackFrame) -> list[SourceMatch]: ...

    def get_source_range(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
    ) -> SourceSnippet: ...


class TreeSitterJavaIndex:
    """Single-repository in-memory index using tree-sitter-java."""

    def __init__(self) -> None:
        language = Language(tree_sitter_java.language())
        self._parser = Parser(language)
        self._repo_path: Path | None = None
        self._symbols: list[JavaSymbol] = []
        self._next_symbol = 0
        self._files_indexed = 0

    def index(self, repo_path: Path) -> IndexStats:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise JavaIndexError(f"repository is not a directory: {repo}")

        self._repo_path = repo
        self._symbols = []
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
                for child in tree.root_node.named_children:
                    self._walk(child, package, [], relative_path)
            except Exception as exc:  # keep indexing best-effort
                stats.errors.append(f"{relative_path}: {exc}")
                continue

            self._files_indexed += 1

        stats.files_indexed = self._files_indexed
        stats.symbols_indexed = len(self._symbols)
        return stats

    def find_symbol(self, query: str, limit: int = 10) -> list[JavaSymbol]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        scored: list[tuple[int, JavaSymbol]] = []
        for symbol in self._symbols:
            score = _match_score(symbol, normalized)
            if score:
                scored.append((score, symbol))

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].file_path,
                item[1].start_line,
                item[1].symbol_id,
            )
        )
        return [symbol for _, symbol in scored[: max(1, min(limit, 50))]]

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
                    self._add_symbol(
                        fqn=_class_fqn(package, class_stack),
                        class_name=class_stack[-1],
                        method_name=name,
                        symbol_type=method_type,
                        file_path=file_path,
                        node=node,
                        signature=_header_text(node),
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
    ) -> None:
        self._next_symbol += 1
        self._symbols.append(
            JavaSymbol(
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
            )
        )

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


def _sort_matches(matches: list[SourceMatch]) -> list[SourceMatch]:
    return sorted(
        matches,
        key=lambda match: (
            -match.confidence,
            match.start_line,
            match.symbol.symbol_id,
        ),
    )


def _package_name(root: Node) -> str:
    for child in root.named_children:
        if child.type != "package_declaration":
            continue
        for named in child.named_children:
            if named.type in {"scoped_identifier", "identifier"}:
                text = named.text
                return text.decode("utf-8") if text is not None else ""
    return ""


def _node_name(node: Node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        for child in node.named_children:
            if child.type == "identifier":
                name_node = child
                break
    if name_node is None or name_node.text is None:
        return None
    return name_node.text.decode("utf-8")


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
