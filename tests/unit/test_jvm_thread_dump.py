"""Thread-dump parser tests for common jstack text."""

from __future__ import annotations

from tracemind.artifacts.parsers import parse_thread_dump

JSTACK = """\
2026-10-23 10:15:00
Full thread dump OpenJDK 64-Bit Server VM (17.0.1+12-LTS):

"pricing-exec-1" #31 prio=5 os_prio=0 tid=0x1 nid=0x1a2c runnable  [0x1]
   java.lang.Thread.State: RUNNABLE
        at com.example.pricing.PricingService.recalculate(PricingService.java:88)
        at com.example.pricing.PricingController.quote(PricingController.java:41)
        - locked <0x00000000d001> (a java.lang.Object)

"http-nio-8080-exec-1" #32 prio=5 os_prio=0 tid=0x2 nid=0x1a2d waiting on condition  [0x2]
   java.lang.Thread.State: WAITING (parking)
        at jdk.internal.misc.Unsafe.park(Native Method)
        - parking to wait for  <0x00000000d002> (a java.util.concurrent.CountDownLatch)
        at java.lang.Thread.run(Thread.java:840)

"Reference Handler" #2 daemon prio=10 os_prio=0 tid=0x3 nid=0x1a2e waiting on condition  [0x3]
   java.lang.Thread.State: WAITING (on object monitor)
        at java.lang.Object.wait(Native Method)
        - waiting on <0x00000000d003> (a java.lang.ref.Reference$Lock)

JNI global refs: 41, weak refs: 0
"""

DEADLOCK = """\
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

Java stack information for the threads listed above:
===================================================
"Thread-1":
        at com.example.LockB.call(LockB.java:10)
        - waiting to lock <0x00000000bbbb> (a java.lang.Object)
"Thread-0":
        at com.example.LockA.call(LockA.java:10)
        - waiting to lock <0x00000000aaaa> (a java.lang.Object)
Found 1 deadlock.
"""


def test_parses_jdk17_thread_headers_states_frames_and_locks() -> None:
    summary = parse_thread_dump(JSTACK.splitlines())

    assert summary.thread_count == 3
    first, second, reference = summary.threads
    assert first.name == "pricing-exec-1"
    assert first.java_id == "31"
    assert first.nid == "0x1a2c"
    assert first.state == "RUNNABLE"
    assert first.line_start == 4
    assert [frame.method for frame in first.frames] == ["recalculate", "quote"]
    assert first.frames[0].class_name == "com.example.pricing.PricingService"
    assert first.frames[0].file == "PricingService.java"
    assert first.frames[0].line == 88
    assert first.frames[1].frame_index == 1
    assert first.lock_events == ["- locked <0x00000000d001> (a java.lang.Object)"]

    assert second.state == "WAITING"
    assert second.frames[0].file == "Native Method"
    assert second.frames[0].line is None
    assert second.lock_events[0].startswith("- parking to wait for")

    assert reference.daemon is True
    assert reference.frames[0].class_name == "java.lang.Object"
    assert "JNI global refs" not in " ".join(first.lock_events)


def test_parses_jdk8_thread_header_state_when_state_line_missing() -> None:
    text = [
        '"main" #1 prio=5 os_prio=0 tid=0x1 nid=0x1 waiting on condition [0x0]',
        "   java.lang.Thread.State: TIMED_WAITING (sleeping)",
    ]
    summary = parse_thread_dump(text)
    assert summary.threads[0].state == "TIMED_WAITING"


def test_parses_deadlock_section_and_marks_threads() -> None:
    summary = parse_thread_dump(DEADLOCK.splitlines())

    assert len(summary.deadlocks) == 1
    deadlock = summary.deadlocks[0]
    assert set(deadlock.threads) == {"Thread-0", "Thread-1"}
    assert set(deadlock.lock_ids) == {"0x00000000bbbb", "0x00000000aaaa"}
    assert deadlock.line_start == 15
    assert deadlock.line_end == 32
    assert all(thread.deadlock_related for thread in summary.threads)
    assert summary.warnings == []


def test_empty_and_unparseable_inputs_are_reported() -> None:
    empty = parse_thread_dump([])
    assert empty.threads == []
    assert "thread dump is empty" in empty.warnings

    no_threads = parse_thread_dump(["Full thread dump", "JNI global refs: 1"])
    assert no_threads.threads == []
    assert "no parsable thread headers found" in no_threads.warnings


def test_unparseable_deadlock_section_warns() -> None:
    summary = parse_thread_dump(
        [
            "Found one Java-level deadlock:",
            "=============================",
            "Found 1 deadlock.",
        ]
    )

    assert len(summary.deadlocks) == 1
    assert summary.deadlocks[0].threads == []
    assert "deadlock section could not be parsed" in summary.warnings


def test_lock_events_are_bounded() -> None:
    lines = ['"main" #1 tid=0x1 nid=0x1 runnable']
    lines.extend(
        f"        - waiting to lock <0x{index:04x}> (a java.lang.Object)"
        for index in range(6)
    )
    summary = parse_thread_dump(lines)
    assert len(summary.threads[0].lock_events) == 4


def test_long_values_are_bounded_and_deterministic() -> None:
    long_name = "n" * 2000
    long_class = ".".join(["a" * 100] * 10) + ".run"
    lines = [
        f'"{long_name}" #1 tid=0x1 nid=0x1 runnable',
        f"        at {long_class}(Foo.java:1)",
    ]
    first = parse_thread_dump(lines)
    second = parse_thread_dump(lines)

    assert first == second
    assert len(first.threads[0].name) <= 512
    assert len(first.threads[0].frames[0].class_name) <= 512


def test_frames_are_bounded_with_warning() -> None:
    lines = ['"main" #1 tid=0x1 nid=0x1 runnable']
    lines.extend(
        f"        at com.example.Foo.method{i}(Foo.java:{i})" for i in range(10)
    )
    summary = parse_thread_dump(lines)
    assert len(summary.threads[0].frames) == 8
    assert any("truncated" in warning for warning in summary.warnings)


def test_thread_count_is_bounded(monkeypatch) -> None:
    from tracemind.artifacts.parsers import thread_dump as module

    monkeypatch.setattr(module, "MAX_THREADS", 2)
    lines: list[str] = []
    for index in range(3):
        lines.append(f'"t{index}" # {index} tid=0x{index} nid=0x{index} runnable')
    summary = parse_thread_dump(lines)
    assert summary.thread_count == 2
    assert summary.truncated is True
    assert any("truncated" in warning for warning in summary.warnings)
