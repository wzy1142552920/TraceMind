"""Path traversal, symlink, and metadata leak checks for artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tracemind.artifacts import ArtifactError, load_artifacts

SERVICE = "order-service"


def _manifest(root: Path, path: str = "dump.txt", **extra: Any) -> None:
    manifest = {
        "schema_version": "1",
        "service": SERVICE,
        "artifacts": [
            {"id": "dump", "kind": "thread_dump", "path": path},
        ],
    }
    manifest.update(extra)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "dump.txt").write_text("x\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "/absolute/dump.txt",
        "./dump.txt",
        "a/../dump.txt",
        "a//dump.txt",
        "dump.txt/",
        "dir\\dump.txt",
        "~/.ssh/id_rsa",
        "C:/dump.txt",
        "bad\x00name.txt",
        "line\nbreak.txt",
    ],
)
def test_unsafe_paths_are_rejected(tmp_path: Path, path: str) -> None:
    root = _root(tmp_path)
    _manifest(root, path)
    with pytest.raises(ArtifactError):
        load_artifacts(root, SERVICE)


def test_symlink_file_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    link = root / "link.txt"
    os.symlink(root / "dump.txt", link)
    _manifest(root, "link.txt")
    with pytest.raises(ArtifactError, match="symlink"):
        load_artifacts(root, SERVICE)


def test_symlink_parent_component_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    real_dir = root / "real"
    real_dir.mkdir()
    (real_dir / "dump.txt").write_text("x\n", encoding="utf-8")
    os.symlink(real_dir, root / "linked")
    _manifest(root, "linked/dump.txt")
    with pytest.raises(ArtifactError, match="symlink"):
        load_artifacts(root, SERVICE)


def test_manifest_symlink_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    manifest = root / "manifest.json"
    target = tmp_path / "manifest-target.json"
    _manifest(root)
    manifest.rename(target)
    os.symlink(target, manifest)
    with pytest.raises(ArtifactError, match="symlink"):
        load_artifacts(root, SERVICE)


def test_records_never_expose_absolute_paths(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _manifest(root)
    bundle = load_artifacts(root, SERVICE)
    record = bundle.records[0]
    assert record.source_name == "dump.txt"
    assert str(tmp_path) not in record.source_name
    assert not Path(record.source_name).is_absolute()


def test_missing_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="artifacts directory"):
        load_artifacts(tmp_path / "missing", SERVICE)


def test_non_regular_manifest_is_rejected(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "manifest.json").mkdir()
    with pytest.raises(ArtifactError, match="not a regular file"):
        load_artifacts(root, SERVICE)
