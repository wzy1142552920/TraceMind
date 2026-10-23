"""Unit tests for mapping JVM tool results into evidence drafts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jvm_helpers import (
    executor_for,
    full_bundle,
    request,
)

from tracemind.artifacts import ArtifactBundle, ArtifactKind
from tracemind.diagnosis.evidence import EvidenceKind, EvidenceProvenance
from tracemind.diagnosis.evidence_mapping import (
    EvidenceDraft,
    MappingOutcome,
    map_tool_result,
)
from tracemind.tools.contracts import ToolResult

_REF_RE = re.compile(
    r"^artifact://[a-z][a-z0-9_-]{0,31}#L\d+(?:-L\d+)?$"
)


def _mapped(
    bundle: ArtifactBundle,
    tool_name: str,
    arguments: dict[str, object] | None = None,
) -> tuple[MappingOutcome, ToolResult]:
    result = executor_for(bundle).execute(request(tool_name, arguments))
    assert result.ok
    return map_tool_result(result, artifacts=bundle), result


def _assert_artifact_refs(outcome: MappingOutcome) -> None:
    for draft in outcome.drafts:
        assert _REF_RE.fullmatch(draft.source_ref), draft.source_ref
        assert draft.provenance is EvidenceProvenance.USER_ARTIFACT
        assert draft.strength == "strong"


def test_thread_dump_maps_each_thread_to_artifact_evidence(
    tmp_path: Path,
) -> None:
    bundle = full_bundle(tmp_path)
    outcome, result = _mapped(bundle, "jvm.get_thread_dump")

    assert outcome.failure_reason is None
    assert outcome.warnings == []
    assert len(outcome.drafts) == 2
    _assert_artifact_refs(outcome)
    assert {draft.kind for draft in outcome.drafts} == {
        EvidenceKind.THREAD_DUMP
    }
    first = outcome.drafts[0]
    assert "pricing-exec-1" in first.claim
    assert first.content["frames"][0]["method"] == "recalculate"
    assert first.content["frames"][0]["line"] == 88
    assert len(first.content["frames"]) <= 8
    assert set(result.data["source_refs"]) == {
        draft.source_ref for draft in outcome.drafts
    }


def test_hot_threads_maps_cpu_samples_and_matched_stacks(
    tmp_path: Path,
) -> None:
    bundle = full_bundle(tmp_path)
    outcome, _ = _mapped(bundle, "jvm.get_hot_threads", {"limit": 10})

    assert outcome.failure_reason is None
    assert outcome.warnings == []
    by_kind: dict[EvidenceKind, list[EvidenceDraft]] = {}
    for draft in outcome.drafts:
        by_kind.setdefault(draft.kind, []).append(draft)

    assert len(by_kind[EvidenceKind.THREAD_CPU]) == 2
    assert len(by_kind[EvidenceKind.THREAD_DUMP]) == 2
    cpu_draft = by_kind[EvidenceKind.THREAD_CPU][0]
    assert cpu_draft.content["cpu_percent"] == 92.3
    assert cpu_draft.content["tid_hex"] == "0x1a2c"
    assert cpu_draft.source_ref.startswith("artifact://thread-cpu#L4")
    matched = by_kind[EvidenceKind.THREAD_DUMP][0]
    assert matched.source_ref.startswith("artifact://thread-dump#L")
    assert matched.content["frames"][0]["method"] == "recalculate"
    _assert_artifact_refs(outcome)


def test_deadlock_maps_threads_and_lock_ids(tmp_path: Path) -> None:
    from jvm_helpers import DEADLOCK_DUMP, build_bundle

    bundle = build_bundle(
        tmp_path / "deadlock",
        {"dump": (ArtifactKind.THREAD_DUMP, DEADLOCK_DUMP)},
    )
    outcome, _ = _mapped(bundle, "jvm.get_deadlocks")

    assert outcome.failure_reason is None
    assert len(outcome.drafts) == 1
    draft = outcome.drafts[0]
    _assert_artifact_refs(outcome)
    assert draft.kind is EvidenceKind.THREAD_DUMP
    assert "Thread-0" in draft.content["threads"]
    assert "0x00000000aaaa" in draft.content["lock_ids"]


def test_gc_summary_and_events_map_with_bounded_content(
    tmp_path: Path,
) -> None:
    bundle = full_bundle(tmp_path)

    summary, _ = _mapped(bundle, "jvm.get_gc_summary")
    assert summary.failure_reason is None
    assert len(summary.drafts) == 1
    summary_draft = summary.drafts[0]
    _assert_artifact_refs(summary)
    assert summary_draft.kind is EvidenceKind.GC_SUMMARY
    assert summary_draft.source_ref == "artifact://gc-log#L1-L2"
    assert summary_draft.content["summary"]["full_events"] == 1
    assert summary_draft.content["full_only"] is False

    full_only, _ = _mapped(
        bundle,
        "jvm.get_gc_summary",
        {"full_only": True},
    )
    assert full_only.drafts[0].content["full_only"] is True
    assert full_only.drafts[0].content["full_scope"][
        "event_count_in_retained_window"
    ] == 1

    events, _ = _mapped(bundle, "jvm.get_gc_events")
    assert events.failure_reason is None
    assert [draft.kind for draft in events.drafts] == [
        EvidenceKind.GC_EVENT,
        EvidenceKind.GC_EVENT,
    ]
    _assert_artifact_refs(events)
    assert events.drafts[0].source_ref == "artifact://gc-log#L1"
    assert events.drafts[1].content["cause"] == "System.gc()"
    assert events.drafts[1].content["pause_ms"] == 1234.567


def test_heap_histogram_maps_one_bounded_summary(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    outcome, _ = _mapped(
        bundle,
        "jvm.get_heap_histogram",
        {"limit": 3},
    )

    assert outcome.failure_reason is None
    assert len(outcome.drafts) == 1
    draft = outcome.drafts[0]
    _assert_artifact_refs(outcome)
    assert draft.kind is EvidenceKind.HEAP_SUMMARY
    assert draft.content["live"] is False
    assert len(draft.content["classes"]) == 3
    assert draft.content["classes"][0]["class_name"].startswith("[B")
    assert draft.source_ref == "artifact://heap-histo#L1-L6"


def test_invalid_artifact_refs_are_skipped_with_warnings(
    tmp_path: Path,
) -> None:
    bundle = full_bundle(tmp_path)
    outcome, result = _mapped(bundle, "jvm.get_thread_dump")
    assert isinstance(result.data, dict)
    threads = [dict(item) for item in result.data["threads"]]
    original_ref = threads[0]["source_ref"]
    threads[0]["source_ref"] = "artifact://missing#L1-L1"
    threads[1]["source_ref"] = "artifact://thread-dump#L9999-L9999"
    mutated = result.model_copy(
        update={"data": {**result.data, "threads": threads}}
    )

    mapped = map_tool_result(mutated, artifacts=bundle)
    assert mapped.drafts == []
    assert mapped.failure_reason is None
    assert len(mapped.warnings) == 2
    assert any("unknown artifact id" in item for item in mapped.warnings)
    assert any("exceeds" in item for item in mapped.warnings)

    threads[0]["source_ref"] = original_ref
    threads[1]["source_ref"] = "artifact://thread-dump#L3"
    mapped_single_line = map_tool_result(
        result.model_copy(
            update={"data": {**result.data, "threads": threads}}
        ),
        artifacts=bundle,
    )
    assert len(mapped_single_line.drafts) == 2
    assert {
        draft.source_ref for draft in mapped_single_line.drafts
    } == {original_ref, "artifact://thread-dump#L3"}

    threads[0]["source_ref"] = "log://evt_0001"
    threads[1]["source_ref"] = "artifact://thread-dump#L3"
    mapped_non_artifact = map_tool_result(
        result.model_copy(
            update={"data": {**result.data, "threads": threads}}
        ),
        artifacts=bundle,
    )
    assert len(mapped_non_artifact.drafts) == 1
    assert any(
        "invalid artifact source_ref" in item
        for item in mapped_non_artifact.warnings
    )


def test_empty_jvm_results_produce_no_drafts(tmp_path: Path) -> None:
    from jvm_helpers import build_bundle

    bundle = build_bundle(
        tmp_path / "empty",
        {
            "gc-log": (ArtifactKind.GC_LOG, "GC log started\n"),
            "heap-histo": (
                ArtifactKind.HEAP_HISTOGRAM,
                " num     #instances         #bytes  class name\n",
            ),
        },
    )
    gc_outcome, _ = _mapped(bundle, "jvm.get_gc_summary")
    assert gc_outcome.drafts == []
    assert any(
        "no GC events" in item for item in gc_outcome.warnings
    )

    heap_outcome, _ = _mapped(bundle, "jvm.get_heap_histogram")
    assert heap_outcome.drafts == []
    assert any(
        "no heap classes" in item for item in heap_outcome.warnings
    )

    no_match, _ = _mapped(
        bundle,
        "jvm.get_heap_histogram",
        {"class_pattern": "no.such.Class"},
    )
    assert no_match.drafts == []
    assert any(
        "no heap classes" in item for item in no_match.warnings
    )


def test_malformed_jvm_result_is_a_failure(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    cases: list[tuple[str, Any, str]] = [
        ("jvm.get_thread_dump", {"threads": "bad"}, "expected threads"),
        ("jvm.get_hot_threads", {}, "expected samples"),
        ("jvm.get_deadlocks", {"deadlocks": None}, "expected deadlocks"),
        ("jvm.get_gc_summary", {"summary": 1}, "missing summary"),
        ("jvm.get_gc_events", {}, "expected events"),
        ("jvm.get_heap_histogram", {"classes": {}}, "expected classes"),
    ]
    for tool_name, data, expected in cases:
        result = ToolResult(
            ok=True,
            tool_name=tool_name,
            data=data,
        )
        outcome = map_tool_result(result, artifacts=bundle)
        assert outcome.drafts == []
        assert outcome.failure_reason is not None
        assert expected in outcome.failure_reason


def test_mapping_content_has_no_absolute_paths(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    outcomes = [
        _mapped(bundle, "jvm.get_thread_dump")[0],
        _mapped(bundle, "jvm.get_hot_threads")[0],
        _mapped(bundle, "jvm.get_gc_summary")[0],
        _mapped(bundle, "jvm.get_gc_events")[0],
        _mapped(bundle, "jvm.get_heap_histogram")[0],
    ]
    encoded = json.dumps(
        [
            [
                {
                    "claim": draft.claim,
                    "content": draft.content,
                    "source_ref": draft.source_ref,
                }
                for draft in outcome.drafts
            ]
            for outcome in outcomes
        ],
        ensure_ascii=False,
        default=str,
    )
    assert str(tmp_path) not in encoded
    assert str(bundle.root) not in encoded
