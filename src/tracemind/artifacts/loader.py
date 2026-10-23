"""Safe, bounded loading of user-provided JVM text snapshots."""

from __future__ import annotations

import json
import stat
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from pydantic import ValidationError

from tracemind.artifacts.models import (
    ArtifactBundle,
    ArtifactDocument,
    ArtifactError,
    ArtifactKind,
    ArtifactManifest,
    ArtifactRecord,
    ArtifactSpec,
)

MANIFEST_NAME = "manifest.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ARTIFACTS = 8
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_TOTAL_LINES = 500_000

MB = 1024 * 1024
KIND_LIMITS: dict[ArtifactKind, tuple[int, int]] = {
    ArtifactKind.THREAD_DUMP: (10 * MB, 500_000),
    ArtifactKind.THREAD_CPU: (2 * MB, 100_000),
    ArtifactKind.GC_LOG: (20 * MB, 500_000),
    ArtifactKind.HEAP_HISTOGRAM: (5 * MB, 200_000),
}


def load_artifacts(root: str | Path, expected_service: str) -> ArtifactBundle:
    """Load and strictly validate a JVM snapshot bundle.

    All validation happens before the caller creates any run artifacts. Errors
    never contain absolute paths or file contents.
    """
    bundle_root = Path(root)
    if not bundle_root.is_dir():
        raise ArtifactError("artifacts directory is missing or not a directory")

    manifest = _load_manifest(bundle_root)
    if manifest.service != expected_service:
        raise ArtifactError(
            "manifest.json: service does not match --service "
            f"({manifest.service!r} != {expected_service!r})"
        )

    seen_ids: set[str] = set()
    documents: list[ArtifactDocument] = []
    total_bytes = 0
    total_lines = 0
    for spec in manifest.artifacts:
        if spec.id in seen_ids:
            raise ArtifactError(f"manifest.json: duplicate artifact id {spec.id!r}")
        seen_ids.add(spec.id)
        document = _load_document(bundle_root, spec)
        total_bytes += document.byte_size
        total_lines += document.line_count
        if total_bytes > MAX_TOTAL_BYTES:
            raise ArtifactError(
                f"artifacts exceed the {MAX_TOTAL_BYTES}-byte total limit"
            )
        if total_lines > MAX_TOTAL_LINES:
            raise ArtifactError(
                f"artifacts exceed the {MAX_TOTAL_LINES}-line total limit"
            )
        documents.append(document)

    records = tuple(
        ArtifactRecord(
            artifact_id=document.artifact_id,
            kind=document.kind,
            source_name=document.source_name,
            line_count=document.line_count,
            byte_size=document.byte_size,
            truncated=False,
            warnings=list(document.warnings),
        )
        for document in documents
    )
    return ArtifactBundle(
        root=bundle_root.resolve(),
        manifest=manifest,
        documents=tuple(documents),
        records=records,
    )


def _load_manifest(root: Path) -> ArtifactManifest:
    path = root / MANIFEST_NAME
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ArtifactError(
            f"{MANIFEST_NAME}: cannot read manifest: {exc.strerror or exc}"
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode):
        raise ArtifactError(f"{MANIFEST_NAME}: must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ArtifactError(f"{MANIFEST_NAME}: not a regular file")
    if file_stat.st_size > MAX_MANIFEST_BYTES:
        raise ArtifactError(
            f"{MANIFEST_NAME}: file exceeds the {MAX_MANIFEST_BYTES}-byte limit"
        )

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ArtifactError(
            f"{MANIFEST_NAME}: cannot read manifest: {exc.strerror or exc}"
        ) from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ArtifactError(
            f"{MANIFEST_NAME}: file exceeds the {MAX_MANIFEST_BYTES}-byte limit"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError(f"{MANIFEST_NAME}: must be UTF-8") from exc

    try:
        document = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ArtifactError(f"{MANIFEST_NAME}: invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ArtifactError(f"{MANIFEST_NAME}: root must be a JSON object")

    try:
        return ArtifactManifest.model_validate(document)
    except ValidationError as exc:
        raise ArtifactError(_format_validation_error(exc)) from exc


def _load_document(root: Path, spec: ArtifactSpec) -> ArtifactDocument:
    parts = _validate_relative_path(spec.path, spec.id)
    target = _safe_target(root, parts, spec.id)
    kind_limit_bytes, kind_limit_lines = KIND_LIMITS[spec.kind]

    try:
        file_stat = target.lstat()
    except OSError as exc:
        raise ArtifactError(
            f"artifact {spec.id!r}: cannot read file: {exc.strerror or exc}"
        ) from exc
    if stat.S_ISLNK(file_stat.st_mode):
        raise ArtifactError(f"artifact {spec.id!r}: file must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ArtifactError(f"artifact {spec.id!r}: not a regular file")
    if file_stat.st_size > kind_limit_bytes:
        raise ArtifactError(
            f"artifact {spec.id!r} ({spec.kind.value}) exceeds the "
            f"{kind_limit_bytes}-byte limit"
        )

    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ArtifactError(
            f"artifact {spec.id!r}: cannot read file: {exc.strerror or exc}"
        ) from exc
    if len(raw) > kind_limit_bytes:
        raise ArtifactError(
            f"artifact {spec.id!r} ({spec.kind.value}) exceeds the "
            f"{kind_limit_bytes}-byte limit"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactError(f"artifact {spec.id!r}: file must be UTF-8") from exc
    if "\x00" in text:
        raise ArtifactError(f"artifact {spec.id!r}: must be a text file")
    lines = tuple(text.splitlines())
    if not lines:
        raise ArtifactError(f"artifact {spec.id!r}: file is empty")
    if len(lines) > kind_limit_lines:
        raise ArtifactError(
            f"artifact {spec.id!r} ({spec.kind.value}) exceeds the "
            f"{kind_limit_lines}-line limit"
        )

    warnings: tuple[str, ...] = ()
    if spec.kind is ArtifactKind.HEAP_HISTOGRAM:
        header = "\n".join(lines[:5]).lower()
        if ":live" not in header:
            warnings = ("heap histogram may include unreachable objects",)

    return ArtifactDocument(
        spec=spec,
        source_name=PurePosixPath(spec.path).name,
        lines=lines,
        byte_size=len(raw),
        line_count=len(lines),
        warnings=warnings,
    )


def _validate_relative_path(path: str, artifact_id: str) -> tuple[str, ...]:
    if not path or len(path) > 256:
        raise ArtifactError(f"artifact {artifact_id!r}: path is empty or too long")
    if "\x00" in path or any(ord(char) < 32 for char in path):
        raise ArtifactError(f"artifact {artifact_id!r}: path contains control characters")
    if "\\" in path:
        raise ArtifactError(f"artifact {artifact_id!r}: path must use '/' separators")
    if ":" in path:
        raise ArtifactError(f"artifact {artifact_id!r}: path must be relative")
    if path.startswith("/") or path.startswith("~"):
        raise ArtifactError(f"artifact {artifact_id!r}: path must be relative")

    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise ArtifactError(f"artifact {artifact_id!r}: path must be relative")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactError(
            f"artifact {artifact_id!r}: path must not contain empty, '.' or '..' segments"
        )
    return tuple(parts)


def _safe_target(root: Path, parts: tuple[str, ...], artifact_id: str) -> Path:
    root_resolved = root.resolve()
    current = root
    for part in parts:
        current = current / part
        try:
            component_stat = current.lstat()
        except OSError as exc:
            raise ArtifactError(
                f"artifact {artifact_id!r}: path is missing"
            ) from exc
        if stat.S_ISLNK(component_stat.st_mode):
            raise ArtifactError(f"artifact {artifact_id!r}: path must not contain symlinks")

    target = current.resolve()
    if not target.is_relative_to(root_resolved):
        raise ArtifactError(f"artifact {artifact_id!r}: path escapes the artifacts directory")
    return target


def _format_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    message = first["msg"]
    if location:
        return f"{MANIFEST_NAME}: {location}: {message}"
    return f"{MANIFEST_NAME}: {message}"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite number is not allowed: {value}")
