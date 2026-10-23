"""Integration tests for JVM artifacts in the v0.4 diagnosis runtime."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.artifacts import ArtifactBundle, load_artifacts
from tracemind.diagnosis.budget import Budget
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.diagnosis.state import RuntimeState, StopReason
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.messages import (
    LLMResponse,
    Message,
    ProviderCapabilities,
    ToolCall,
    ToolDefinition,
)
from tracemind.log_analysis.parser import LogParser

ROOT = Path(__file__).resolve().parents[2]
LOG_FIXTURE = ROOT / "fixtures" / "logs" / "basic" / "incident.log"
REPO_FIXTURE = ROOT / "fixtures" / "repos" / "minimal-order-service"
SOURCE_REF = "repo://src/main/java/com/example/order/OrderService.java#L17-L27"

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


class RecordingProvider:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[Message], list[ToolDefinition]]] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(tool_calling=True)

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append((messages, list(tools)))
        if not self.responses:
            return LLMResponse(content="", tool_calls=[], finish_reason="stop")
        return self.responses.pop(0)

    def tool_names(self, index: int) -> set[str]:
        return {definition.name for definition in self.calls[index][1]}

    def user_prompt(self, index: int) -> str:
        return next(
            message.content
            for message in self.calls[index][0]
            if message.role == "user"
        )

    def system_prompt(self, index: int) -> str:
        return next(
            message.content
            for message in self.calls[index][0]
            if message.role == "system"
        )


def _bundle(root: Path) -> ArtifactBundle:
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "thread-dump": ("thread_dump", THREAD_DUMP),
        "thread-cpu": ("thread_cpu", THREAD_CPU),
        "gc-log": ("gc_log", GC_LOG),
    }
    artifacts = []
    for index, (artifact_id, (kind, text)) in enumerate(files.items()):
        path = f"{index}-{artifact_id}.txt"
        (root / path).write_text(text, encoding="utf-8")
        artifacts.append({"id": artifact_id, "kind": kind, "path": path})
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "service": "order-service",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return load_artifacts(root, "order-service")


def _response(
    calls: list[ToolCall],
    *,
    content: str = "",
) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
    )


def _proposals(*, with_code: bool = True) -> list[ToolCall]:
    requirements = [
        {
            "description": "The thread CPU snapshot shows a hot business thread.",
            "evidence_kinds": ["thread_cpu"],
            "discriminating": True,
            "suggested_tools": ["jvm.get_hot_threads"],
        }
    ]
    if with_code:
        requirements.append(
            {
                "description": "The source executes the hot business path.",
                "evidence_kinds": ["source_code"],
                "discriminating": False,
                "suggested_tools": ["code.find_symbol"],
            }
        )
    return [
        ToolCall(
            id="propose_1",
            name="diagnosis_propose_hypothesis",
            arguments={
                "statement": (
                    "pricing-exec-1 burns CPU in OrderService.updateStatus "
                    "while handling the request."
                ),
                "cause_chain": [
                    "the request enters the pricing path",
                    "the business thread executes a hot computation",
                    "the thread stays RUNNABLE at high CPU",
                ],
                "basis_evidence_ids": ["ev_0001"],
                "requirements": requirements,
                "falsifiers": [
                    "The hot thread is not a business thread.",
                    "GC pressure explains the CPU instead of application code.",
                ],
            },
        ),
        ToolCall(
            id="propose_2",
            name="diagnosis_propose_hypothesis",
            arguments={
                "statement": "GC pressure causes the latency instead of hot code.",
                "cause_chain": [
                    "allocation pressure rises",
                    "GC pauses lengthen",
                    "requests time out",
                ],
                "basis_evidence_ids": ["ev_0001"],
                "requirements": [
                    {
                        "description": "The GC log shows sustained GC pressure.",
                        "evidence_kinds": ["gc_summary"],
                        "discriminating": True,
                        "suggested_tools": ["jvm.get_gc_summary"],
                    }
                ],
                "falsifiers": [
                    "GC pauses are short and the heap recovers after collection."
                ],
            },
        ),
    ]


def _bound_call(
    call_id: str,
    name: str,
    arguments: dict[str, object],
    *,
    hypothesis_id: str,
    requirement_id: str,
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        arguments={
            **arguments,
            "hypothesis_id": hypothesis_id,
            "requirement_id": requirement_id,
        },
    )


def _assess(
    assessments: list[dict[str, object]],
) -> ToolCall:
    return ToolCall(
        id="assess_1",
        name="diagnosis_assess_evidence",
        arguments={"assessments": assessments},
    )


def _index() -> TreeSitterJavaIndex:
    index = TreeSitterJavaIndex()
    index.index(REPO_FIXTURE)
    return index


def _run(
    provider: RecordingProvider,
    *,
    log_path: Path = LOG_FIXTURE,
    artifacts: ArtifactBundle | None = None,
    repair_attempts: int = 0,
):
    parsed = LogParser().parse(log_path)
    runtime = DiagnosisRuntime(
        repo_root=REPO_FIXTURE,
        provider_name="mock",
        model="v04",
        repair_attempts=repair_attempts,
        artifacts=artifacts,
    )
    return runtime.run(parsed, _index(), "order-service", provider, Budget())


def test_jvm_artifacts_confirm_without_same_thread_repair(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "artifacts")
    provider = RecordingProvider(
        [
            _response(_proposals()),
            _response(
                [
                    _bound_call(
                        "jvm_hot",
                        "jvm_get_hot_threads",
                        {"limit": 10, "min_cpu_percent": 1.0},
                        hypothesis_id="hyp_001",
                        requirement_id="hyp_001_req_01",
                    ),
                    _bound_call(
                        "jvm_gc",
                        "jvm_get_gc_summary",
                        {},
                        hypothesis_id="hyp_002",
                        requirement_id="hyp_002_req_01",
                    ),
                    _bound_call(
                        "source_1",
                        "code_find_symbol",
                        {"query": "OrderService.updateStatus"},
                        hypothesis_id="hyp_001",
                        requirement_id="hyp_001_req_02",
                    ),
                ]
            ),
            _response(
                [
                    _assess(
                        [
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_01",
                                "source_ref": "artifact://thread-cpu#L4",
                                "verdict": "supports",
                                "rationale": "One business thread dominates CPU.",
                            },
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_02",
                                "source_ref": SOURCE_REF,
                                "verdict": "supports",
                                "rationale": "The hot stack resolves to this method.",
                            },
                            {
                                "hypothesis_id": "hyp_002",
                                "requirement_id": "hyp_002_req_01",
                                "source_ref": "artifact://gc-log#L1-L2",
                                "verdict": "refutes",
                                "rationale": "GC counts and pauses do not explain the CPU.",
                            },
                        ]
                    )
                ]
            ),
            _response([]),
        ]
    )

    result = _run(provider, artifacts=bundle)

    assert result.state is RuntimeState.COMPLETED
    assert result.stop_reason is StopReason.EVIDENCE_SUFFICIENT
    assert result.evaluation.run_confirmed is True
    statuses = {item.hypothesis_id: item.status for item in result.hypotheses}
    assert statuses == {"hyp_001": "confirmed", "hyp_002": "contradicted"}
    assert not any(
        event.event_type == "agent.repair" for event in result.events
    )
    assert all(
        not (
            event.event_type == "agent.repair"
            and event.data.get("reason") == "missing_thread_context"
        )
        for event in result.events
    )

    assert provider.tool_names(0) == {"diagnosis_propose_hypothesis"}
    assert {
        "jvm_get_hot_threads",
        "jvm_get_deadlocks",
        "jvm_get_gc_summary",
        "jvm_get_thread_dump",
    } <= provider.tool_names(1)
    assert provider.tool_names(2) == {"diagnosis_assess_evidence"}

    user_prompt = provider.user_prompt(0)
    assert "JVM artifacts (user-provided point-in-time snapshots, not live):" in user_prompt
    assert "id=thread-dump kind=thread_dump" in user_prompt
    assert "JVM snapshot analysis:" in provider.system_prompt(0)
    assert "same-thread log context is optional" in provider.system_prompt(0)
    assert str(tmp_path) not in user_prompt

    assert [record.artifact_id for record in result.artifacts] == [
        "thread-dump",
        "thread-cpu",
        "gc-log",
    ]
    assert all(
        record.source_environment == "user_provided"
        for record in result.artifacts
    )
    assert all(
        str(tmp_path) not in json.dumps(record.model_dump())
        for record in result.artifacts
    )

    jvm_calls = [
        record
        for record in result.tool_calls
        if record.tool_name.startswith("jvm.")
    ]
    assert {record.tool_name for record in jvm_calls} == {
        "jvm.get_hot_threads",
        "jvm.get_gc_summary",
    }
    assert all(record.ok for record in jvm_calls)
    assert all(record.evidence_ids for record in jvm_calls)
    assert result.budget_usage["tool_calls"] == len(result.tool_calls) == 6

    cpu_evidence = next(
        item for item in result.evidence if item.kind == "thread_cpu"
    )
    assert cpu_evidence.provenance == "user_artifact"
    assert cpu_evidence.source_ref == "artifact://thread-cpu#L4"
    assert cpu_evidence.bound_hypothesis_id == "hyp_001"
    assert any("point-in-time" in item for item in result.limitations)
    assert any(
        "same-thread log context is not required" in item
        for item in result.limitations
    )


def test_snapshot_symptom_without_code_mechanism_is_not_confirmed(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "artifacts")
    provider = RecordingProvider(
        [
            _response(_proposals(with_code=False)),
            _response(
                [
                    _bound_call(
                        "jvm_hot",
                        "jvm_get_hot_threads",
                        {"limit": 10},
                        hypothesis_id="hyp_001",
                        requirement_id="hyp_001_req_01",
                    ),
                    _bound_call(
                        "jvm_gc",
                        "jvm_get_gc_summary",
                        {},
                        hypothesis_id="hyp_002",
                        requirement_id="hyp_002_req_01",
                    ),
                ]
            ),
            _response(
                [
                    _assess(
                        [
                            {
                                "hypothesis_id": "hyp_001",
                                "requirement_id": "hyp_001_req_01",
                                "source_ref": "artifact://thread-cpu#L4",
                                "verdict": "supports",
                                "rationale": (
                                    "The hot thread is real but no code "
                                    "mechanism was read."
                                ),
                            },
                            {
                                "hypothesis_id": "hyp_002",
                                "requirement_id": "hyp_002_req_01",
                                "source_ref": "artifact://gc-log#L1-L2",
                                "verdict": "refutes",
                                "rationale": "GC does not explain the CPU profile.",
                            },
                        ]
                    )
                ]
            ),
        ]
    )

    result = _run(provider, artifacts=bundle)

    assert result.state is RuntimeState.INSUFFICIENT_DATA
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.evaluation.run_confirmed is False
    target = result.evaluation.for_hypothesis("hyp_001")
    assert target is not None
    assert target.status == "supported"
    assert target.qualifies is False
    assert any(
        reason.startswith("missing_mechanism_evidence:")
        for reason in target.reasons
    )
    assert not any(
        item.kind
        in {"source_code", "call_path", "sql", "annotation", "config", "db_schema"}
        and item.bindings
        for item in result.evidence
    )
    assert not any(
        event.event_type == "agent.repair"
        and event.data.get("reason") == "missing_thread_context"
        for event in result.events
    )


def test_cause_chain_frames_seed_source_matching(tmp_path: Path) -> None:
    log_path = tmp_path / "cause.log"
    log_path.write_text(
        "2026-10-18 10:21:03.416 ERROR [http-a] c.e.order.OrderService - "
        "failed to update order status\n"
        "java.lang.RuntimeException: wrapped failure\n"
        "    at com.example.Unknown.call(Unknown.java:1)\n"
        "Caused by: java.lang.IllegalStateException: update failed for "
        "orderId=10086\n"
        "    at com.example.order.OrderService.updateStatus("
        "OrderService.java:24)\n"
        "    at com.example.order.OrderController.handlePaid("
        "OrderController.java:41)\n",
        encoding="utf-8",
    )
    provider = RecordingProvider([])

    result = _run(provider, log_path=log_path)

    source = next(
        item for item in result.evidence if item.kind == "source_code"
    )
    assert source.source_ref == SOURCE_REF
    assert source.content["file_path"].endswith("OrderService.java")
    prompt = provider.user_prompt(0)
    assert "- cause chain:" in prompt
    assert "caused by [1] java.lang.IllegalStateException" in prompt
    assert "OrderService.updateStatus" in prompt
    assert str(log_path) not in prompt
