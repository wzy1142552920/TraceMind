"""Manifest and size/encoding validation for JVM snapshot bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tracemind.artifacts import ArtifactError, ArtifactKind, load_artifacts
from tracemind.artifacts import loader as loader_module

SERVICE = "order-service"


def _write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _bundle(
    root: Path,
    files: dict[str, str | bytes],
    artifacts: list[dict[str, str]],
    **overrides: Any,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": "1",
        "service": SERVICE,
        "artifacts": artifacts,
    }
    manifest.update(overrides)
    _write_manifest(root, manifest)
    return root


def _valid_bundle(root: Path) -> Path:
    return _bundle(
        root,
        {
            "thread-dump.txt": (
                '"main" #1 prio=5 os_prio=0 tid=0x1 nid=0x2 runnable\n'
                "   java.lang.Thread.State: RUNNABLE\n"
            ),
            "thread-cpu.txt": "   123 user 20 0 1 1 1 R 91.0 1.0 1:00.00 java\n",
            "gc.log": (
                "[2026-10-23T10:00:00.000+0800][info][gc] "
                "GC(1) Pause Young 1M->1M(2M) 1.0ms\n"
            ),
            "heap-histo.txt": (
                " num     #instances         #bytes  class name\n"
                "   1:             10            100  com.example.Entry\n"
            ),
        },
        [
            {"id": "thread-dump", "kind": "thread_dump", "path": "thread-dump.txt"},
            {"id": "thread-cpu", "kind": "thread_cpu", "path": "thread-cpu.txt"},
            {"id": "gc-log", "kind": "gc_log", "path": "gc.log"},
            {"id": "heap-histo", "kind": "heap_histogram", "path": "heap-histo.txt"},
        ],
    )


def test_valid_bundle_loads_all_kinds_and_records(tmp_path: Path) -> None:
    bundle = load_artifacts(_valid_bundle(tmp_path / "artifacts"), SERVICE)

    assert [doc.artifact_id for doc in bundle.documents] == [
        "thread-dump",
        "thread-cpu",
        "gc-log",
        "heap-histo",
    ]
    assert bundle.has_kind(ArtifactKind.THREAD_DUMP)
    assert bundle.by_kind(ArtifactKind.GC_LOG)[0].source_name == "gc.log"
    assert bundle.document("missing") is None
    assert bundle.document("thread-dump") is not None
    assert [record.kind for record in bundle.records] == [
        ArtifactKind.THREAD_DUMP,
        ArtifactKind.THREAD_CPU,
        ArtifactKind.GC_LOG,
        ArtifactKind.HEAP_HISTOGRAM,
    ]
    assert all(record.source_environment == "user_provided" for record in bundle.records)
    assert all(record.truncated is False for record in bundle.records)
    assert bundle.records[3].warnings == ["heap histogram may include unreachable objects"]
    assert bundle.records[0].source_name == "thread-dump.txt"
    assert str(tmp_path) not in bundle.records[0].source_name


def test_manifest_missing_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="cannot read manifest"):
        load_artifacts(tmp_path, SERVICE)


def test_manifest_invalid_json_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="invalid JSON"):
        load_artifacts(tmp_path, SERVICE)


def test_manifest_root_must_be_object(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactError, match="root must be a JSON object"):
        load_artifacts(tmp_path, SERVICE)


def test_manifest_unknown_field_is_rejected(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "artifacts",
        {"dump.txt": "x\n"},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
        unexpected=True,
    )
    with pytest.raises(ArtifactError, match="unexpected"):
        load_artifacts(root, SERVICE)


def test_manifest_schema_version_is_strict(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "artifacts",
        {"dump.txt": "x\n"},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
        schema_version="2",
    )
    with pytest.raises(ArtifactError, match="schema_version"):
        load_artifacts(root, SERVICE)


def test_unknown_kind_is_rejected(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "artifacts",
        {"dump.txt": "x\n"},
        [{"id": "dump", "kind": "heap_dump", "path": "dump.txt"}],
    )
    with pytest.raises(ArtifactError, match="kind"):
        load_artifacts(root, SERVICE)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "artifacts",
        {"a.txt": "x\n", "b.txt": "y\n"},
        [
            {"id": "dump", "kind": "thread_dump", "path": "a.txt"},
            {"id": "dump", "kind": "thread_cpu", "path": "b.txt"},
        ],
    )
    with pytest.raises(ArtifactError, match="duplicate artifact id"):
        load_artifacts(root, SERVICE)


def test_invalid_id_and_empty_artifacts_are_rejected(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "artifacts",
        {"a.txt": "x\n"},
        [{"id": "Bad Id", "kind": "thread_dump", "path": "a.txt"}],
    )
    with pytest.raises(ArtifactError, match="id"):
        load_artifacts(root, SERVICE)

    root = _bundle(tmp_path / "empty", {}, [])
    with pytest.raises(ArtifactError, match="artifacts"):
        load_artifacts(root, SERVICE)


def test_more_than_eight_artifacts_are_rejected(tmp_path: Path) -> None:
    files = {f"f{index}.txt": "x\n" for index in range(9)}
    artifacts = [
        {"id": f"a{index}", "kind": "thread_dump", "path": f"f{index}.txt"}
        for index in range(9)
    ]
    root = _bundle(tmp_path / "artifacts", files, artifacts)
    with pytest.raises(ArtifactError, match="artifacts"):
        load_artifacts(root, SERVICE)


def test_service_must_match(tmp_path: Path) -> None:
    root = _valid_bundle(tmp_path / "artifacts")
    with pytest.raises(ArtifactError, match="service"):
        load_artifacts(root, "other-service")


def test_optional_metadata_is_validated(tmp_path: Path) -> None:
    root = _valid_bundle(tmp_path / "artifacts")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["instance"] = "order-service-1"
    manifest["captured_at"] = "2026-10-23T10:15:00+08:00"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    bundle = load_artifacts(root, SERVICE)
    assert bundle.manifest.instance == "order-service-1"

    manifest["captured_at"] = "not-a-timestamp"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError, match="captured_at"):
        load_artifacts(root, SERVICE)


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        '{"schema_version": "1", "schema_version": "1", '
        '"service": "order-service", "artifacts": []}',
        encoding="utf-8",
    )
    with pytest.raises(ArtifactError, match="duplicate JSON key"):
        load_artifacts(tmp_path, SERVICE)


def test_non_utf8_and_empty_files_are_rejected(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path / "bad-encoding",
        {"dump.txt": b"\xff\xfe\x00"},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
    )
    with pytest.raises(ArtifactError, match="UTF-8"):
        load_artifacts(root, SERVICE)

    root = _bundle(
        tmp_path / "empty-file",
        {"dump.txt": ""},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
    )
    with pytest.raises(ArtifactError, match="empty"):
        load_artifacts(root, SERVICE)


def test_directory_and_missing_artifacts_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "nested").mkdir()
    _write_manifest(
        root,
        {
            "schema_version": "1",
            "service": SERVICE,
            "artifacts": [
                {"id": "dump", "kind": "thread_dump", "path": "nested"}
            ],
        },
    )
    with pytest.raises(ArtifactError, match="not a regular file"):
        load_artifacts(root, SERVICE)

    _write_manifest(
        root,
        {
            "schema_version": "1",
            "service": SERVICE,
            "artifacts": [
                {"id": "dump", "kind": "thread_dump", "path": "missing.txt"}
            ],
        },
    )
    with pytest.raises(ArtifactError, match="missing"):
        load_artifacts(root, SERVICE)


def test_per_kind_byte_and_line_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        loader_module.KIND_LIMITS,
        ArtifactKind.THREAD_DUMP,
        (5, 100),
    )
    root = _bundle(
        tmp_path / "bytes",
        {"dump.txt": "123456"},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
    )
    with pytest.raises(ArtifactError, match="byte limit"):
        load_artifacts(root, SERVICE)

    monkeypatch.setitem(
        loader_module.KIND_LIMITS,
        ArtifactKind.THREAD_DUMP,
        (100, 2),
    )
    root = _bundle(
        tmp_path / "lines",
        {"dump.txt": "a\nb\nc\n"},
        [{"id": "dump", "kind": "thread_dump", "path": "dump.txt"}],
    )
    with pytest.raises(ArtifactError, match="line limit"):
        load_artifacts(root, SERVICE)


def test_total_byte_and_line_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loader_module, "MAX_TOTAL_BYTES", 5)
    root = _bundle(
        tmp_path / "bytes",
        {"a.txt": "abc", "b.txt": "def"},
        [
            {"id": "a", "kind": "thread_dump", "path": "a.txt"},
            {"id": "b", "kind": "thread_cpu", "path": "b.txt"},
        ],
    )
    with pytest.raises(ArtifactError, match="total limit"):
        load_artifacts(root, SERVICE)

    monkeypatch.setattr(loader_module, "MAX_TOTAL_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(loader_module, "MAX_TOTAL_LINES", 1)
    root = _bundle(
        tmp_path / "lines",
        {"a.txt": "a\n", "b.txt": "b\n"},
        [
            {"id": "a", "kind": "thread_dump", "path": "a.txt"},
            {"id": "b", "kind": "thread_cpu", "path": "b.txt"},
        ],
    )
    with pytest.raises(ArtifactError, match="total limit"):
        load_artifacts(root, SERVICE)
