"""Unit tests for conditional JVM snapshot tools."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from jvm_helpers import (
    DEADLOCK_DUMP,
    THREAD_CPU,
    THREAD_DUMP,
    build_bundle,
    executor_for,
    full_bundle,
    request,
)

from tracemind.artifacts import ArtifactKind
from tracemind.diagnosis.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceProvenance,
)
from tracemind.diagnosis.ledger import EvidenceLedger
from tracemind.diagnosis.workspace import (
    DiagnosisWorkspace,
    HypothesisProposal,
    RequirementProposal,
)
from tracemind.tools import jvm as jvm_module
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolErrorCode
from tracemind.tools.executor import ToolExecutor


def test_tools_are_registered_conditionally(tmp_path: Path) -> None:
    assert not {
        spec.name
        for spec in build_default_registry().list_tools()
        if spec.name.startswith("jvm.")
    }

    dump_only = build_bundle(
        tmp_path / "dump",
        {"dump": (ArtifactKind.THREAD_DUMP, THREAD_DUMP)},
    )
    assert {
        spec.name
        for spec in build_default_registry(artifacts=dump_only).list_tools()
        if spec.name.startswith("jvm.")
    } == {"jvm.get_thread_dump", "jvm.get_deadlocks"}

    cpu_only = build_bundle(
        tmp_path / "cpu",
        {"cpu": (ArtifactKind.THREAD_CPU, THREAD_CPU)},
    )
    assert not {
        spec.name
        for spec in build_default_registry(artifacts=cpu_only).list_tools()
        if spec.name.startswith("jvm.")
    }

    cpu_and_dump = build_bundle(
        tmp_path / "both",
        {
            "dump": (ArtifactKind.THREAD_DUMP, THREAD_DUMP),
            "cpu": (ArtifactKind.THREAD_CPU, THREAD_CPU),
        },
    )
    names = {
        spec.name
        for spec in build_default_registry(artifacts=cpu_and_dump).list_tools()
        if spec.name.startswith("jvm.")
    }
    assert names == {
        "jvm.get_thread_dump",
        "jvm.get_deadlocks",
        "jvm.get_hot_threads",
    }

    full = full_bundle(tmp_path / "full")
    assert {
        spec.name
        for spec in build_default_registry(artifacts=full).list_tools()
        if spec.name.startswith("jvm.")
    } == {
        "jvm.get_thread_dump",
        "jvm.get_hot_threads",
        "jvm.get_deadlocks",
        "jvm.get_gc_summary",
        "jvm.get_gc_events",
        "jvm.get_heap_histogram",
    }


def test_argument_validation_rejects_out_of_range_and_extra_fields(
    tmp_path: Path,
) -> None:
    bundle = full_bundle(tmp_path)
    invalid_calls = [
        ("jvm.get_thread_dump", {"limit": 0}),
        ("jvm.get_thread_dump", {"limit": 20, "extra": True}),
        ("jvm.get_thread_dump", {"thread_name": "x" * 200}),
        ("jvm.get_thread_dump", {"state": "x" * 40}),
        ("jvm.get_hot_threads", {"limit": 0}),
        ("jvm.get_hot_threads", {"min_cpu_percent": 101}),
        ("jvm.get_hot_threads", {"extra": True}),
        ("jvm.get_deadlocks", {"extra": True}),
        ("jvm.get_gc_summary", {"extra": True}),
        ("jvm.get_gc_events", {"limit": 101}),
        ("jvm.get_gc_events", {"extra": True}),
        ("jvm.get_heap_histogram", {"limit": 0}),
        ("jvm.get_heap_histogram", {"class_pattern": "com.example.*("}),
        ("jvm.get_heap_histogram", {"class_pattern": "a/b"}),
        ("jvm.get_heap_histogram", {"extra": True}),
    ]
    for index, (tool_name, arguments) in enumerate(invalid_calls):
        result = executor_for(bundle).execute(
            request(tool_name, arguments, tool_call_id=f"call_bad_{index}")
        )
        assert not result.ok, (tool_name, arguments)
        assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS.value

    valid = executor_for(bundle).execute(
        request("jvm.get_heap_histogram", {"class_pattern": "com.example.*"})
    )
    assert valid.ok


def test_thread_dump_filters_limit_and_no_match_warning(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)

    default = executor_for(bundle).execute(request("jvm.get_thread_dump", {}))
    assert default.ok
    data = default.data
    assert isinstance(data, dict)
    assert len(data["threads"]) == 2
    assert data["threads"][0]["name"] == "pricing-exec-1"
    assert data["threads"][0]["frames"][0]["method"] == "recalculate"
    assert data["deadlocks"] == []

    by_state = executor_for(bundle).execute(
        request("jvm.get_thread_dump", {"state": "waiting"})
    )
    assert [item["name"] for item in by_state.data["threads"]] == [
        "http-nio-8080-exec-1"
    ]

    by_name = executor_for(bundle).execute(
        request("jvm.get_thread_dump", {"thread_name": "PRICING"})
    )
    assert [item["name"] for item in by_name.data["threads"]] == [
        "pricing-exec-1"
    ]

    limited = executor_for(bundle).execute(
        request("jvm.get_thread_dump", {"limit": 1})
    )
    assert len(limited.data["threads"]) == 1
    assert limited.data["truncated"] is True

    deadlock_only = executor_for(bundle).execute(
        request("jvm.get_thread_dump", {"deadlock_only": True})
    )
    assert deadlock_only.ok
    assert deadlock_only.data["threads"] == []
    assert any(
        "no threads matched" in warning
        for warning in deadlock_only.data["warnings"]
    )


def test_deadlocks_are_returned_and_absence_is_not_an_error(
    tmp_path: Path,
) -> None:
    deadlock_bundle = build_bundle(
        tmp_path / "deadlock",
        {"dump": (ArtifactKind.THREAD_DUMP, DEADLOCK_DUMP)},
    )
    result = executor_for(deadlock_bundle).execute(
        request("jvm.get_deadlocks", {})
    )
    assert result.ok
    assert len(result.data["deadlocks"]) == 1
    deadlock = result.data["deadlocks"][0]
    assert set(deadlock["threads"]) == {"Thread-0", "Thread-1"}
    assert set(deadlock["lock_ids"]) == {"0x00000000aaaa", "0x00000000bbbb"}
    assert deadlock["source_ref"].startswith("artifact://dump#L")

    absent = executor_for(full_bundle(tmp_path / "full")).execute(
        request("jvm.get_deadlocks", {})
    )
    assert absent.ok
    assert absent.data["deadlocks"] == []
    assert any(
        "no Java-level deadlocks" in warning
        for warning in absent.data["warnings"]
    )


def test_hot_threads_map_nids_sort_and_report_unmatched(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    result = executor_for(bundle).execute(
        request("jvm.get_hot_threads", {"limit": 10})
    )
    assert result.ok
    samples = result.data["samples"]
    assert [sample["tid_decimal"] for sample in samples] == [6700, 16]
    assert [sample["cpu_percent"] for sample in samples] == [92.3, 3.1]
    assert samples[0]["tid_hex"] == "0x1a2c"
    assert samples[0]["thread_name"] == "pricing-exec-1"
    assert samples[0]["matched_thread"]["state"] == "RUNNABLE"
    assert samples[0]["matched_thread"]["top_frames"][0]["method"] == "recalculate"
    assert result.data["unmatched_tids"] == []
    assert set(result.data["artifact_ids"]) == {"thread-cpu", "thread-dump"}

    with_unmatched = executor_for(bundle).execute(
        request(
            "jvm.get_hot_threads",
            {"limit": 10, "min_cpu_percent": 0.0},
        )
    )
    assert with_unmatched.data["unmatched_tids"] == [99]
    assert any(
        "did not match" in warning
        for warning in with_unmatched.data["warnings"]
    )


def test_gc_summary_and_events_match_parser(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    summary = executor_for(bundle).execute(request("jvm.get_gc_summary", {}))
    assert summary.ok
    assert summary.data["summary"]["total_events"] == 2
    assert summary.data["summary"]["young_events"] == 1
    assert summary.data["summary"]["full_events"] == 1
    assert summary.data["source_ref"] == "artifact://gc-log#L1-L2"

    full_only = executor_for(bundle).execute(
        request("jvm.get_gc_summary", {"full_only": True})
    )
    assert full_only.data["full_scope"]["event_count_in_retained_window"] == 1
    assert full_only.data["full_scope"]["max_pause_ms"] == 1234.567

    events = executor_for(bundle).execute(
        request("jvm.get_gc_events", {"limit": 20})
    )
    assert [event["event_type"] for event in events.data["events"]] == [
        "young",
        "full",
    ]
    assert events.data["events"][-1]["pause_ms"] == 1234.567

    recent = executor_for(bundle).execute(
        request("jvm.get_gc_events", {"limit": 1})
    )
    assert len(recent.data["events"]) == 1
    assert recent.data["events"][0]["event_type"] == "full"
    assert recent.data["truncated"] is True

    full_events = executor_for(bundle).execute(
        request("jvm.get_gc_events", {"full_only": True})
    )
    assert [event["event_type"] for event in full_events.data["events"]] == [
        "full"
    ]


def test_heap_histogram_limit_and_pattern(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    result = executor_for(bundle).execute(
        request("jvm.get_heap_histogram", {"limit": 2})
    )
    assert result.ok
    assert result.data["live"] is False
    assert len(result.data["classes"]) == 2
    assert result.data["classes"][0]["class_name"].startswith("[B")
    assert result.data["total_bytes"] == 114311010
    assert result.data["truncated"] is True

    filtered = executor_for(bundle).execute(
        request("jvm.get_heap_histogram", {"class_pattern": "reportentry"})
    )
    assert [
        item["class_name"] for item in filtered.data["classes"]
    ] == ["com.example.ReportEntry"]

    wildcard = executor_for(bundle).execute(
        request("jvm.get_heap_histogram", {"class_pattern": "*Report*"})
    )
    assert len(wildcard.data["classes"]) == 1

    missing = executor_for(bundle).execute(
        request("jvm.get_heap_histogram", {"class_pattern": "no.such.Class"})
    )
    assert missing.data["classes"] == []
    assert any(
        "no heap classes matched" in warning
        for warning in missing.data["warnings"]
    )


def test_binding_metadata_reaches_result_and_audit(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    ledger = EvidenceLedger()
    ledger.add(
        Evidence(
            evidence_id="ev_0001",
            kind=EvidenceKind.LOG_EVENT,
            claim="request timeout",
            source_ref="log://evt_0001",
            provenance=EvidenceProvenance.LOG_PARSER,
            observed_at="2026-10-23T00:00:00+00:00",
        )
    )
    workspace = DiagnosisWorkspace(ledger)
    created = workspace.propose_hypothesis(
        HypothesisProposal(
            statement="a hot pricing loop consumes CPU",
            cause_chain=["hot loop"],
            basis_evidence_ids=["ev_0001"],
            requirements=[
                RequirementProposal(
                    description="high CPU thread matches the pricing stack",
                    evidence_kinds=[EvidenceKind.THREAD_CPU],
                    discriminating=True,
                )
            ],
            falsifiers=["no hot CPU thread"],
        )
    )
    executor = ToolExecutor(
        build_default_registry(artifacts=bundle),
        ToolContext(artifacts=bundle, workspace=workspace),
    )
    result = executor.execute(
        request(
            "jvm.get_hot_threads",
            {
                "hypothesis_id": created["hypothesis_id"],
                "requirement_id": created["requirement_ids"][0],
            },
        )
    )
    assert result.ok
    assert result.bound_hypothesis_id == created["hypothesis_id"]
    assert result.bound_requirement_id == created["requirement_ids"][0]
    assert executor.audit_events[-1].outcome == "allowed"
    assert (
        executor.audit_events[-1].bound_hypothesis_id
        == created["hypothesis_id"]
    )


def test_tool_descriptions_mark_snapshots_read_only(tmp_path: Path) -> None:
    bundle = full_bundle(tmp_path)
    specs = [
        spec
        for spec in build_default_registry(artifacts=bundle).list_tools()
        if spec.name.startswith("jvm.")
    ]
    assert len(specs) == 6
    for spec in specs:
        description = spec.description.lower()
        assert "read-only" in description
        assert "user-provided" in description
        assert "not live" in description


def test_thread_dump_output_stays_below_executor_limit(
    tmp_path: Path,
) -> None:
    lines: list[str] = []
    for index in range(80):
        lines.append(
            f'"t{index}" #{index} tid=0x{index} nid=0x{index:x} runnable'
        )
        lines.append("   java.lang.Thread.State: RUNNABLE")
        for frame_index in range(8):
            lines.append(
                f"        at com.example.pkg{index}.Service{index}."
                f"method{frame_index}(Service{index}.java:{frame_index})"
            )
    bundle = build_bundle(
        tmp_path / "big-dump",
        {"dump": (ArtifactKind.THREAD_DUMP, "\n".join(lines) + "\n")},
    )
    executor = executor_for(bundle)
    result = executor.execute(request("jvm.get_thread_dump", {"limit": 100}))
    assert result.ok
    assert isinstance(result.data, dict)
    encoded = json.dumps(result.data, ensure_ascii=False)
    assert len(encoded.encode("utf-8")) <= 32768
    assert result.truncated is True
    assert any(
        "byte bound" in warning for warning in result.data["warnings"]
    )


def test_jvm_tools_do_not_import_exec_or_network_modules() -> None:
    source_path = jvm_module.__file__
    assert source_path is not None
    source = Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "os",
    }
    assert "open(" not in source
    assert "Popen" not in source
