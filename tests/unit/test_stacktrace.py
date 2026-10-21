"""Unit tests for Java stack-trace parsing helpers."""

from __future__ import annotations

from tracemind.log_analysis.stacktrace import parse_exception_line, parse_frame


def test_parse_frame_with_file_and_line() -> None:
    frame = parse_frame(
        "    at com.example.order.OrderService.updateStatus(OrderService.java:24)"
    )

    assert frame is not None
    assert frame.class_name == "com.example.order.OrderService"
    assert frame.method_name == "updateStatus"
    assert frame.file_name == "OrderService.java"
    assert frame.line_number == 24
    assert frame.is_native is False
    assert frame.is_reflection is False


def test_parse_module_prefixed_frame() -> None:
    frame = parse_frame("    at java.base/java.lang.Thread.run(Thread.java:840)")

    assert frame is not None
    assert frame.class_name == "java.lang.Thread"
    assert frame.method_name == "run"
    assert frame.line_number == 840


def test_parse_native_frame() -> None:
    frame = parse_frame("    at java.base/java.lang.Thread.run(Native Method)")

    assert frame is not None
    assert frame.class_name == "java.lang.Thread"
    assert frame.file_name is None
    assert frame.line_number is None
    assert frame.is_native is True


def test_parse_unknown_source_frame() -> None:
    frame = parse_frame("    at com.example.Foo.bar(Unknown Source)")

    assert frame is not None
    assert frame.file_name is None
    assert frame.line_number is None
    assert frame.is_native is False


def test_parse_reflection_frame() -> None:
    frame = parse_frame(
        "    at jdk.internal.reflect.NativeMethodAccessorImpl.invoke0(Native Method)"
    )

    assert frame is not None
    assert frame.is_reflection is True


def test_parse_proxy_frame() -> None:
    frame = parse_frame(
        "    at com.example.Foo$$EnhancerBySpringCGLIB.bar(Foo.java:10)"
    )

    assert frame is not None
    assert frame.is_reflection is True


def test_parse_exception_line() -> None:
    parsed = parse_exception_line(
        "java.lang.IllegalStateException: update failed for orderId=10086"
    )

    assert parsed == ("java.lang.IllegalStateException", "update failed for orderId=10086")


def test_parse_exception_without_message() -> None:
    assert parse_exception_line("java.lang.IllegalStateException") == (
        "java.lang.IllegalStateException",
        None,
    )


def test_non_frame_and_non_exception_return_none() -> None:
    assert parse_frame("not a frame") is None
    assert parse_exception_line("not an exception") is None
