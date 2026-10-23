"""End-to-end CLI tests for JVM artifacts and report schema 0.4."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tracemind.cli.main import app

ROOT = Path(__file__).resolve().parents[2]
LOG_FIXTURE = ROOT / "fixtures" / "logs" / "basic" / "incident.log"
REPO_FIXTURE = ROOT / "fixtures" / "repos" / "minimal-order-service"
BASIC_MOCK = ROOT / "fixtures" / "mock" / "basic_plan.json"
SOURCE_REF = "repo://src/main/java/com/example/order/OrderService.java#L17-L27"
runner = CliRunner()

THREAD_DUMP = """\
2026-10-23 10:15:00
Full thread dump OpenJDK 64-Bit Server VM (17.0.1+12-LTS):

"pricing-exec-1" #31 prio=5 os_prio=0 tid=0x1 nid=0x1a2c runnable  [0x1]
   java.lang.Thread.State: RUNNABLE
        at com.example.order.OrderService.updateStatus(OrderService.java:24)
        at com.example.order.OrderController.handlePaid(OrderController.java:41)

"http-nio-8080-exec-1" #32 prio=5 os_prio=0 tid=0x2 nid=0x10 waiting on condition  [0x2]
   java.lang.Thread.State: WAITING (parking)
        at jdk.internal.misc.Unsafe.park(Native Method)
        at java.lang.Thread.run(Thread.java:840)
"""
THREAD_CPU = """\
top - 10:15:00 up 1 day,  2:03,  0 users,  load average: 2.10, 2.00, 1.50
Threads:  42 total,   1 running,  41 sleeping,   0 stopped,   0 zombie
  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
 6700 app       20   0  4200000 120000 20000 R  92.3   3.0  10:15.00 pricing-exec-1
   16 app       20   0  4200000 120000 20000 S   3.1   3.0   0:10.00 http-nio-8080-exec-1
"""
GC_LOG = """\
[10:00:00.123][info][gc] GC(12) Pause Young (Normal) 512M->256M(1024M) 12.345ms
[10:00:01.123][info][gc] GC(13) Pause Full (System.gc()) 1024M->900M(1024M) 1234.567ms
"""


def _write_bundle(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "thread-dump.txt").write_text(THREAD_DUMP, encoding="utf-8")
    (root / "thread-cpu.txt").write_text(THREAD_CPU, encoding="utf-8")
    (root / "gc.log").write_text(GC_LOG, encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "service": "order-service",
                "artifacts": [
                    {
                        "id": "thread-dump",
                        "kind": "thread_dump",
                        "path": "thread-dump.txt",
                    },
                    {
                        "id": "thread-cpu",
                        "kind": "thread_cpu",
                        "path": "thread-cpu.txt",
                    },
                    {
                        "id": "gc-log",
                        "kind": "gc_log",
                        "path": "gc.log",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _mock_script() -> dict:
    return {
        "responses": [
            {
                "content": "Propose a hot-code and a GC-pressure candidate.",
                "tool_calls": [
                    {
                        "id": "propose_1",
                        "name": "diagnosis_propose_hypothesis",
                        "arguments": {
                            "statement": (
                                "pricing-exec-1 burns CPU in "
                                "OrderService.updateStatus."
                            ),
                            "cause_chain": [
                                "the request enters the pricing path",
                                "the business thread executes a hot computation",
                                "the thread stays RUNNABLE at high CPU",
                            ],
                            "basis_evidence_ids": ["ev_0001"],
                            "requirements": [
                                {
                                    "description": (
                                        "A business thread dominates CPU."
                                    ),
                                    "evidence_kinds": ["thread_cpu"],
                                    "discriminating": True,
                                    "suggested_tools": [
                                        "jvm.get_hot_threads"
                                    ],
                                },
                                {
                                    "description": (
                                        "The hot stack resolves to source."
                                    ),
                                    "evidence_kinds": ["source_code"],
                                    "discriminating": False,
                                    "suggested_tools": [
                                        "code.find_symbol"
                                    ],
                                },
                            ],
                            "falsifiers": [
                                "The hot thread is not a business thread.",
                                "GC pressure explains the CPU.",
                            ],
                        },
                    },
                    {
                        "id": "propose_2",
                        "name": "diagnosis_propose_hypothesis",
                        "arguments": {
                            "statement": (
                                "GC pressure causes the latency instead of "
                                "hot code."
                            ),
                            "cause_chain": [
                                "allocation pressure rises",
                                "GC pauses lengthen",
                                "requests time out",
                            ],
                            "basis_evidence_ids": ["ev_0001"],
                            "requirements": [
                                {
                                    "description": (
                                        "The GC log shows sustained pressure."
                                    ),
                                    "evidence_kinds": ["gc_summary"],
                                    "discriminating": True,
                                    "suggested_tools": [
                                        "jvm.get_gc_summary"
                                    ],
                                }
                            ],
                            "falsifiers": [
                                "GC pauses are short and the heap recovers."
                            ],
                        },
                    },
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "Investigate the hot thread, GC, and source.",
                "tool_calls": [
                    {
                        "id": "jvm_hot",
                        "name": "jvm_get_hot_threads",
                        "arguments": {
                            "limit": 10,
                            "min_cpu_percent": 1.0,
                            "hypothesis_id": "hyp_001",
                            "requirement_id": "hyp_001_req_01",
                        },
                    },
                    {
                        "id": "jvm_gc",
                        "name": "jvm_get_gc_summary",
                        "arguments": {
                            "hypothesis_id": "hyp_002",
                            "requirement_id": "hyp_002_req_01",
                        },
                    },
                    {
                        "id": "source_1",
                        "name": "code_find_symbol",
                        "arguments": {
                            "query": "OrderService.updateStatus",
                            "hypothesis_id": "hyp_001",
                            "requirement_id": "hyp_001_req_02",
                        },
                    },
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "Assess the bound evidence.",
                "tool_calls": [
                    {
                        "id": "assess_1",
                        "name": "diagnosis_assess_evidence",
                        "arguments": {
                            "assessments": [
                                {
                                    "hypothesis_id": "hyp_001",
                                    "requirement_id": "hyp_001_req_01",
                                    "source_ref": (
                                        "artifact://thread-cpu#L4"
                                    ),
                                    "verdict": "supports",
                                    "rationale": (
                                        "One business thread dominates CPU."
                                    ),
                                },
                                {
                                    "hypothesis_id": "hyp_001",
                                    "requirement_id": "hyp_001_req_02",
                                    "source_ref": SOURCE_REF,
                                    "verdict": "supports",
                                    "rationale": (
                                        "The hot stack resolves to this method."
                                    ),
                                },
                                {
                                    "hypothesis_id": "hyp_002",
                                    "requirement_id": "hyp_002_req_01",
                                    "source_ref": "artifact://gc-log#L1-L2",
                                    "verdict": "refutes",
                                    "rationale": (
                                        "GC counts do not explain the CPU."
                                    ),
                                },
                            ]
                        },
                    }
                ],
                "finish_reason": "tool_calls",
            },
            {
                "content": "",
                "tool_calls": [],
                "finish_reason": "stop",
            },
        ]
    }


def _invoke(
    output_dir: Path,
    *,
    artifacts: Path | None = None,
    mock_script: Path | None = None,
    json_output: bool = False,
):
    args = [
        "diagnose",
        "--log",
        str(LOG_FIXTURE),
        "--repo",
        str(REPO_FIXTURE),
        "--service",
        "order-service",
        "--provider",
        "mock",
        "--mock-script",
        str(mock_script or BASIC_MOCK),
        "--output-dir",
        str(output_dir),
    ]
    if artifacts is not None:
        args.extend(["--artifacts", str(artifacts)])
    if json_output:
        args.append("--json")
    return runner.invoke(app, args)


def _run_dir(output_dir: Path) -> Path:
    directories = sorted(
        path for path in output_dir.iterdir() if path.is_dir()
    )
    assert len(directories) == 1
    return directories[0]


def test_cli_reports_artifacts_and_jvm_evidence(tmp_path: Path) -> None:
    artifacts = _write_bundle(tmp_path / "artifacts")
    script = tmp_path / "jvm.json"
    script.write_text(json.dumps(_mock_script()), encoding="utf-8")
    output_dir = tmp_path / "runs"

    result = _invoke(
        output_dir,
        artifacts=artifacts,
        mock_script=script,
    )

    assert result.exit_code == 0, result.output
    assert "Snapshots: 3 (thread_dump, thread_cpu, gc_log)" in result.output
    assert "JVM evidence: 5" in result.output
    assert "artifact_citations=True" in result.output
    assert "artifacts_labeled=True" in result.output

    run_dir = _run_dir(output_dir)
    report_text = (run_dir / "report.json").read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["schema_version"] == "0.4"
    assert report["status"] == "confirmed"
    assert [
        item["artifact_id"] for item in report["artifacts"]
    ] == ["thread-dump", "thread-cpu", "gc-log"]
    assert all(
        item["source_environment"] == "user_provided"
        for item in report["artifacts"]
    )
    assert [item["source_name"] for item in report["artifacts"]] == [
        "thread-dump.txt",
        "thread-cpu.txt",
        "gc.log",
    ]
    assert report["validation"]["citations_valid"] is True
    assert report["validation"]["artifact_citations_valid"] is True
    assert report["validation"]["artifacts_labeled"] is True
    artifact_sources = [
        source
        for source in report["sources"]
        if source["category"] == "artifact"
    ]
    assert artifact_sources
    assert all(
        source["source_ref"].startswith("artifact://")
        for source in artifact_sources
    )
    assert all(source["verified"] for source in artifact_sources)
    assert str(artifacts) not in report_text
    assert "sk-" not in report_text

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## JVM 快照" in markdown
    assert "thread-cpu.txt" in markdown
    assert "artifact://thread-cpu#L4" in markdown
    assert "Full thread dump OpenJDK" not in markdown
    assert str(artifacts) not in markdown

    run_text = (run_dir / "run.json").read_text(encoding="utf-8")
    run_data = json.loads(run_text)
    assert run_data["schema_version"] == "0.4"
    assert [
        item["artifact_id"] for item in run_data["artifacts"]
    ] == ["thread-dump", "thread-cpu", "gc-log"]
    assert all(
        str(artifacts) not in json.dumps(item)
        for item in run_data["artifacts"]
    )
    assert "sk-" not in run_text


def test_cli_json_summary_with_artifacts(tmp_path: Path) -> None:
    artifacts = _write_bundle(tmp_path / "artifacts")
    script = tmp_path / "jvm.json"
    script.write_text(json.dumps(_mock_script()), encoding="utf-8")
    output_dir = tmp_path / "runs"

    result = _invoke(
        output_dir,
        artifacts=artifacts,
        mock_script=script,
        json_output=True,
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout.strip())
    assert summary["artifact_count"] == 3
    assert summary["artifact_kinds"] == [
        "thread_dump",
        "thread_cpu",
        "gc_log",
    ]
    assert summary["jvm_evidence_count"] == 5
    assert summary["status"] == "confirmed"


def test_cli_without_artifacts_keeps_old_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir)

    assert result.exit_code == 0, result.output
    assert "Snapshots:" not in result.output
    assert "JVM evidence:" not in result.output
    run_dir = _run_dir(output_dir)
    report = json.loads(
        (run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "0.4"
    assert report["artifacts"] == []
    assert report["validation"]["artifact_citations_valid"] is True
    assert report["validation"]["artifacts_labeled"] is True


def test_cli_without_artifacts_json_fields_are_zero(tmp_path: Path) -> None:
    output_dir = tmp_path / "runs"

    result = _invoke(output_dir, json_output=True)

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout.strip())
    assert summary["artifact_count"] == 0
    assert summary["artifact_kinds"] == []
    assert summary["jvm_evidence_count"] == 0
    assert summary["evidence_count"] > 0
    assert summary["tool_calls"] > 0
