"""Shared synthetic JVM artifact fixtures for unit tests."""

from __future__ import annotations

import json
from pathlib import Path

from tracemind.artifacts import ArtifactBundle, ArtifactKind, load_artifacts
from tracemind.tools.builtin import build_default_registry
from tracemind.tools.contracts import ToolContext, ToolRequest
from tracemind.tools.executor import ToolExecutor

SERVICE = "order-service"

THREAD_DUMP = """\
2026-10-23 10:15:00
Full thread dump OpenJDK 64-Bit Server VM (17.0.1+12-LTS):

"pricing-exec-1" #31 prio=5 os_prio=0 tid=0x1 nid=0x1a2c runnable  [0x1]
   java.lang.Thread.State: RUNNABLE
        at com.example.pricing.PricingService.recalculate(PricingService.java:88)
        at com.example.pricing.PricingController.quote(PricingController.java:41)
        - locked <0x00000000d001> (a java.lang.Object)

"http-nio-8080-exec-1" #32 prio=5 os_prio=0 tid=0x2 nid=0x10 waiting on condition  [0x2]
   java.lang.Thread.State: WAITING (parking)
        at jdk.internal.misc.Unsafe.park(Native Method)
        - parking to wait for  <0x00000000d002> (a java.util.concurrent.CountDownLatch)
        at java.lang.Thread.run(Thread.java:840)
"""

THREAD_CPU = """\
top - 10:15:00 up 1 day,  2:03,  0 users,  load average: 2.10, 2.00, 1.50
Threads:  42 total,   1 running,  41 sleeping,   0 stopped,   0 zombie
  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND
 6700 app       20   0  4200000 120000 20000 R  92.3   3.0  10:15.00 pricing-exec-1
   16 app       20   0  4200000 120000 20000 S   3.1   3.0   0:10.00 http-nio-8080-exec-1
   99 app       20   0  4200000 120000 20000 S   0.5   3.0   0:01.00 worker-1
"""

GC_LOG = """\
[10:00:00.123][info][gc] GC(12) Pause Young (Normal) 512M->256M(1024M) 12.345ms
[10:00:01.123][info][gc] GC(13) Pause Full (System.gc()) 1024M->900M(1024M) 1234.567ms
"""

HEAP_HISTOGRAM = """\
 num     #instances         #bytes  class name (module)
-------------------------------------------------------
   1:       1234567       98765432  [B (java.base@17.0.1)
   2:        234567       12345678  com.example.ReportEntry
   3:        100000        3200000  java.util.concurrent.ConcurrentHashMap$Node
Total       1569134      114311010
"""

DEADLOCK_DUMP = """\
"Thread-0" #10 prio=5 os_prio=0 tid=0x1 nid=0x10 waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
        at com.example.LockA.call(LockA.java:10)
        - waiting to lock <0x00000000aaaa> (a java.lang.Object)
        at com.example.LockB.call(LockB.java:10)
        - locked <0x00000000bbbb> (a java.lang.Object)

"Thread-1" #11 prio=5 os_prio=0 tid=0x2 nid=0x11 waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
        at com.example.LockB.call(LockB.java:10)
        - waiting to lock <0x00000000bbbb> (a java.lang.Object)
        at com.example.LockA.call(LockA.java:10)
        - locked <0x00000000aaaa> (a java.lang.Object)

Found one Java-level deadlock:
=============================
"Thread-1":
  waiting to lock monitor 0x00000000cc01 (object 0x00000000bbbb, a java.lang.Object),
  which is held by "Thread-0"
"Thread-0":
  waiting to lock monitor 0x00000000cc02 (object 0x00000000aaaa, a java.lang.Object),
  which is held by "Thread-1"
Found 1 deadlock.
"""


def build_bundle(
    root: Path,
    entries: dict[str, tuple[ArtifactKind | str, str]],
) -> ArtifactBundle:
    """Write a manifest plus artifacts and load the validated bundle."""
    root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index, (artifact_id, (kind, text)) in enumerate(entries.items()):
        path = f"{index}-{artifact_id}.txt"
        (root / path).write_text(text, encoding="utf-8")
        artifacts.append(
            {
                "id": artifact_id,
                "kind": ArtifactKind(kind).value,
                "path": path,
            }
        )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "service": SERVICE,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return load_artifacts(root, SERVICE)


def full_bundle(root: Path) -> ArtifactBundle:
    """Build a bundle containing all four supported snapshot kinds."""
    return build_bundle(
        root,
        {
            "thread-dump": (ArtifactKind.THREAD_DUMP, THREAD_DUMP),
            "thread-cpu": (ArtifactKind.THREAD_CPU, THREAD_CPU),
            "gc-log": (ArtifactKind.GC_LOG, GC_LOG),
            "heap-histo": (ArtifactKind.HEAP_HISTOGRAM, HEAP_HISTOGRAM),
        },
    )


def executor_for(bundle: ArtifactBundle) -> ToolExecutor:
    """Build a registry and context scoped to one artifact bundle."""
    registry = build_default_registry(artifacts=bundle)
    return ToolExecutor(registry, ToolContext(artifacts=bundle))


def request(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    tool_call_id: str = "call_1",
) -> ToolRequest:
    """Build one deterministic tool request."""
    return ToolRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments or {},
        run_id="run_jvm_test",
    )
