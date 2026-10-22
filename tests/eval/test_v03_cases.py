"""Deterministic offline evaluation of the three v0.3 incident cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import (
    CASE_IDS,
    CODE_KINDS,
    FIXTURES,
    ROOT,
    case_fixture,
    expected_ref_is_present,
    hypothesis_evidence_ids,
    hypothesis_sources,
    keyword_matches,
    run_case,
    satisfied_kinds,
    source_refs_for,
    source_text,
    sources_by_id,
    top_hypothesis,
)

from tracemind.log_analysis.parser import LogParser
from tracemind.log_analysis.thread_context import collect_thread_context

_READ_ONLY_DB_TOOLS = frozenset({"db.get_row", "db.describe_table"})
_VALIDATION_FLAGS = (
    "citations_valid",
    "evidence_ids_valid",
    "hypotheses_valid",
    "remediation_grounded",
    "verification_labeled",
    "status_consistent",
)


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_case_report_matches_expected(case_id: str) -> None:
    """Each case must produce a fully grounded, confirmed schema 0.3 report."""
    run = run_case(case_id)
    expected = run.expected
    report = run.report
    assert report.schema_version == "0.3", f"{case_id}: expected schema 0.3"
    assert report.status == expected["expected_status"], (
        f"{case_id}: got report status {report.status!r}"
    )
    assert report.hypotheses, f"{case_id}: expected ranked hypotheses"
    top = top_hypothesis(report)
    assert top.status == expected["expected_hypothesis_status"], (
        f"{case_id}: Top-1 status was {top.status!r}"
    )
    assert keyword_matches(top.statement, expected["expected_top_cause_keywords"]), (
        f"{case_id}: Top-1 statement did not match expected cause: {top.statement!r}"
    )
    assert run.result.evaluation.run_confirmed, (
        f"{case_id}: deterministic evaluation did not confirm the run"
    )

    actual_refs = source_refs_for(report, top)
    missing_refs = [
        ref
        for ref in expected["expected_evidence_refs"]
        if not expected_ref_is_present(ref, actual_refs)
    ]
    assert not missing_refs, (
        f"{case_id}: Top-1 missing expected source refs {missing_refs}; "
        f"got {sorted(actual_refs)}"
    )

    kinds = satisfied_kinds(report, top)
    missing_kinds = set(expected["expected_evidence_kinds"]) - kinds
    assert not missing_kinds, (
        f"{case_id}: satisfied requirements missing evidence kinds "
        f"{sorted(missing_kinds)}; got {sorted(kinds)}"
    )
    assert "log_thread_context" in kinds, (
        f"{case_id}: Top-1 lacks an assessed same-thread context requirement"
    )
    assert kinds & CODE_KINDS, (
        f"{case_id}: Top-1 lacks a satisfied code-flow requirement"
    )

    assert all(requirement.satisfied for requirement in top.requirements), (
        f"{case_id}: unsupported requirements remain: "
        f"{top.missing_requirement_ids}"
    )
    assert any(
        requirement.discriminating and requirement.satisfied
        for requirement in top.requirements
    ), f"{case_id}: no discriminating requirement was satisfied"

    context_sources = [
        source
        for source in hypothesis_sources(report, top)
        if source.kind == "log_thread_context"
    ]
    assert context_sources, f"{case_id}: no same-thread context source in report"
    assert all(
        source.thread == expected["expected_thread"] for source in context_sources
    ), (
        f"{case_id}: context sources used unexpected threads: "
        f"{[source.thread for source in context_sources]}"
    )
    context_text = " ".join(source_text(source) for source in context_sources)
    for message in expected["expected_thread_context_messages"]:
        assert message in context_text, (
            f"{case_id}: same-thread context missing {message!r}"
        )
    for marker in expected["forbidden_thread_context_markers"]:
        assert marker not in context_text, (
            f"{case_id}: cross-thread marker {marker!r} leaked into context"
        )

    indexed_sources = sources_by_id(report)
    referenced = hypothesis_evidence_ids(top)
    assert referenced <= set(indexed_sources), (
        f"{case_id}: Top-1 references evidence missing from report sources"
    )
    assert all(source.verified for source in report.sources), (
        f"{case_id}: report contains unverified citations"
    )

    actions = report.remediation_plan
    assert actions, f"{case_id}: expected a non-empty remediation plan"
    action_types = {action.type for action in actions}
    missing_types = set(expected["expected_remediation_types"]) - action_types
    assert not missing_types, (
        f"{case_id}: remediation missing types {sorted(missing_types)}; "
        f"got {sorted(action_types)}"
    )
    target_keywords = expected["expected_remediation_target_keywords"]
    assert any(
        keyword.lower() in action.target.lower()
        for action in actions
        for keyword in target_keywords
    ), (
        f"{case_id}: no remediation target matched {target_keywords}; "
        f"targets={[action.target for action in actions]}"
    )
    for action in actions:
        assert action.hypothesis_id == top.hypothesis_id, (
            f"{case_id}: action {action.action_id} is attached to "
            f"{action.hypothesis_id}, not Top-1"
        )
        assert action.evidence_ids, (
            f"{case_id}: action {action.action_id} has no evidence binding"
        )
        assert set(action.evidence_ids) <= referenced, (
            f"{case_id}: action {action.action_id} references evidence "
            f"outside the confirmed hypothesis"
        )

    for flag in _VALIDATION_FLAGS:
        assert getattr(report.validation, flag), (
            f"{case_id}: validation flag {flag} is false: "
            f"{report.validation.errors}"
        )

    assert report.verification.environment == "fixture", (
        f"{case_id}: verification must be labeled as a fixture"
    )
    assert report.verification.backend == "fake", (
        f"{case_id}: expected fake backend labeling"
    )
    assert report.verification.tables_queried, (
        f"{case_id}: expected the orders table to be queried"
    )

    forbidden_calls = set(expected["forbidden_tool_calls"])
    called = {call.tool_name for call in run.result.tool_calls}
    assert not called & forbidden_calls, (
        f"{case_id}: forbidden tool calls were made: {called & forbidden_calls}"
    )
    assert all(call.ok for call in run.result.tool_calls), (
        f"{case_id}: failed tool calls in audit: "
        f"{[(call.tool_name, call.error_code) for call in run.result.tool_calls if not call.ok]}"
    )
    db_calls = [
        call
        for call in run.result.tool_calls
        if call.tool_name.startswith("db.")
    ]
    assert db_calls, f"{case_id}: expected database verification tool calls"
    assert {call.tool_name for call in db_calls} <= _READ_ONLY_DB_TOOLS, (
        f"{case_id}: non-read-only DB tool call"
    )
    assert not run.result.rejected_remediations, (
        f"{case_id}: expected no rejected remediation actions"
    )


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_expected_yaml_matches_case(case_id: str) -> None:
    """The case fixture and its expected answer must agree."""
    fixture = case_fixture(case_id)
    expected = run_case(case_id).expected
    assert expected["case_id"] == case_id
    assert expected["symptom"] == "updateStatus returned rows=0; update failed"
    assert expected["expected_thread"] == "http-nio-8080-exec-7"
    assert expected["expected_status"] == "confirmed"
    assert expected["expected_hypothesis_status"] == "confirmed"
    assert fixture.log_path.is_file()
    assert fixture.repo_path.is_dir()
    assert fixture.verification_path.is_file()
    assert fixture.mock_path.is_file()


def test_logs_are_identical_and_hide_the_root_cause() -> None:
    """All cases share one symptom log that does not reveal code or DB state."""
    contents = [
        case_fixture(case_id).log_path.read_bytes() for case_id in CASE_IDS
    ]
    assert len(set(contents)) == 1, "case logs must be byte-identical"
    text = contents[0].decode("utf-8")
    for marker in ("OrderMapper", "PAID", "PENDING", "default", "SQL", "duplicate"):
        assert marker not in text, f"log leaks root-cause marker {marker!r}"
    assert "OrderService" in text
    assert "PaymentNotifier" in text, "cross-thread noise must be present"


def test_parser_excludes_cross_thread_noise() -> None:
    """The raw log contains another thread, but context only keeps exec-7."""
    parsed = LogParser().parse(case_fixture(CASE_IDS[0]).log_path)
    primary = next(
        event
        for event in parsed.events
        if event.event_id == parsed.primary_event_id
    )
    assert primary.thread == "http-nio-8080-exec-7"
    context = collect_thread_context(parsed, primary.event_id)
    assert context.thread == "http-nio-8080-exec-7"
    messages = [item.message for item in context.items]
    assert any("paid callback orderId=10086" in message for message in messages)
    assert any("updateStatus returned rows=0" in message for message in messages)
    assert any("failed to update order status" in message for message in messages)
    assert not any("PaymentNotifier" in message for message in messages)
    assert not any("retry probe" in message for message in messages)


def test_repo_variants_share_business_flow() -> None:
    """Fixed and stub repositories differ only in the OrderMapper file."""
    fixed = FIXTURES / "repos" / "minimal-order-service-fixed"
    stub = FIXTURES / "repos" / "minimal-order-service"
    fixed_files = {
        path.relative_to(fixed) for path in fixed.rglob("*.java")
    }
    stub_files = {path.relative_to(stub) for path in stub.rglob("*.java")}
    assert fixed_files == stub_files
    assert fixed_files == {
        Path("src/main/java/com/example/order/OrderController.java"),
        Path("src/main/java/com/example/order/OrderMapper.java"),
        Path("src/main/java/com/example/order/OrderService.java"),
    }
    for relative in (
        Path("src/main/java/com/example/order/OrderController.java"),
        Path("src/main/java/com/example/order/OrderService.java"),
    ):
        assert (fixed / relative).read_bytes() == (stub / relative).read_bytes(), (
            f"{relative} must be identical across repo variants"
        )
    mapper = Path("src/main/java/com/example/order/OrderMapper.java")
    assert (fixed / mapper).read_bytes() != (stub / mapper).read_bytes()
    fixed_mapper = (fixed / mapper).read_text(encoding="utf-8")
    stub_mapper = (stub / mapper).read_text(encoding="utf-8")
    assert "int updateStatus(Long orderId, String status);" in fixed_mapper
    assert "default int updateStatus" not in fixed_mapper
    assert "default int updateStatus" in stub_mapper
    assert "return 0;" in stub_mapper

    for repo in (fixed, stub):
        service_lines = (repo / "src/main/java/com/example/order/OrderService.java").read_text(
            encoding="utf-8"
        ).splitlines()
        controller_lines = (
            repo / "src/main/java/com/example/order/OrderController.java"
        ).read_text(encoding="utf-8").splitlines()
        assert "throw new IllegalStateException" in service_lines[23]
        assert "this.updateStatus(orderId, \"PAID\")" in service_lines[13]
        assert "orderService.handlePaid(orderId)" in controller_lines[15]


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_verification_fixture_matches_case(case_id: str) -> None:
    """Fixture rows must encode missing, already-PAID, and PENDING states."""
    payload = json.loads(
        case_fixture(case_id).verification_path.read_text(encoding="utf-8")
    )
    assert payload["backend"] == "fake", f"{case_id}: fixture backend must be fake"
    orders = payload["tables"]["orders"]
    assert orders["primary_key"] == "id"
    assert orders["columns"] == ["id", "status", "updated_at"]
    assert orders["sensitive_columns"] == []
    rows = orders["rows"]

    if case_id == "v03-c1-missing-row":
        assert rows == [], f"{case_id}: expected no orders row"
    elif case_id == "v03-c2-duplicate-callback":
        assert len(rows) == 1
        assert rows[0]["id"] == 10086
        assert rows[0]["status"] == "PAID"
    else:
        assert len(rows) == 1
        assert rows[0]["id"] == 10086
        assert rows[0]["status"] == "PENDING"

    for row in rows:
        assert "secret" not in " ".join(row).lower()


def test_case_metrics_meet_thresholds() -> None:
    """Aggregate the acceptance metrics across all three cases."""
    top1 = top3 = context = code = coverage = 0
    total_sources = valid_sources = 0
    total_actions = grounded_actions = 0
    unauthorized = 0
    details: dict[str, dict[str, bool | int]] = {}

    for case_id in CASE_IDS:
        run = run_case(case_id)
        expected = run.expected
        report = run.report
        top = top_hypothesis(report)
        matched = keyword_matches(
            top.statement, expected["expected_top_cause_keywords"]
        )
        top1 += int(top.status == "confirmed" and matched)
        top3 += int(
            any(
                hypothesis.status == "confirmed"
                and keyword_matches(
                    hypothesis.statement,
                    expected["expected_top_cause_keywords"],
                )
                for hypothesis in report.hypotheses[:3]
            )
        )
        kinds = satisfied_kinds(report, top)
        has_context = "log_thread_context" in kinds
        has_code = bool(kinds & CODE_KINDS)
        context += int(has_context)
        code += int(has_code)
        complete = all(
            requirement.satisfied for requirement in top.requirements
        )
        coverage += int(complete)
        total_sources += len(report.sources)
        valid_sources += sum(1 for source in report.sources if source.verified)
        total_actions += len(report.remediation_plan)
        grounded_actions += sum(
            1
            for action in report.remediation_plan
            if action.evidence_ids
            and set(action.evidence_ids)
            <= set(sources_by_id(report))
        )
        unauthorized += sum(
            1
            for call in run.result.tool_calls
            if call.tool_name.startswith("db.")
            and call.tool_name not in _READ_ONLY_DB_TOOLS
        )
        details[case_id] = {
            "top1": matched and top.status == "confirmed",
            "thread_context": has_context,
            "code_evidence": has_code,
            "coverage": complete,
        }

    case_count = len(CASE_IDS)
    metrics = {
        "details": details,
        "top1": f"{top1}/{case_count}",
        "top3": f"{top3}/{case_count}",
        "thread_context": f"{context}/{case_count}",
        "code_evidence": f"{code}/{case_count}",
        "coverage": f"{coverage}/{case_count}",
        "citations": f"{valid_sources}/{total_sources}",
        "grounding": f"{grounded_actions}/{total_actions}",
        "unauthorized": unauthorized,
    }
    assert top1 == case_count, metrics
    assert top3 == case_count, metrics
    assert context == case_count, metrics
    assert code == case_count, metrics
    assert coverage == case_count, metrics
    assert total_sources > 0 and valid_sources == total_sources, metrics
    assert total_actions > 0 and grounded_actions == total_actions, metrics
    assert unauthorized == 0, metrics


def test_eval_is_offline() -> None:
    """The case harness must not read external configuration or the network."""
    for case_id in CASE_IDS:
        run = run_case(case_id)
        assert run.result.llm_calls, f"{case_id}: expected local mock LLM calls"
        assert {record.provider for record in run.result.llm_calls} == {"mock"}
        assert {record.model for record in run.result.llm_calls} == {
            "v03-case"
        }


def test_helpers_resolve_under_repo_root() -> None:
    """Guard against accidental fixture paths outside the repository."""
    assert ROOT.name == "TraceMind"
    assert FIXTURES.is_dir()
    for case_id in CASE_IDS:
        fixture = case_fixture(case_id)
        assert fixture.log_path.is_relative_to(ROOT)
        assert fixture.repo_path.is_relative_to(ROOT)
        assert fixture.verification_path.is_relative_to(ROOT)
