"""Path-normalization helpers for local read-only tools."""

from __future__ import annotations

from pathlib import Path


def resolve_under_root(root: Path, relative_path: str) -> Path:
    """Resolve a relative path and reject absolute/path-escape candidates."""
    if not relative_path:
        raise ValueError("path is empty")
    if relative_path.startswith("~"):
        raise ValueError("home-relative paths are not allowed")

    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")

    root_resolved = root.expanduser().resolve()
    target = (root_resolved / candidate).resolve()
    if not target.is_relative_to(root_resolved):
        raise ValueError(f"path escapes root: {relative_path}")
    return target
