"""Java stack-trace parsing helpers."""

from __future__ import annotations

import re

from tracemind.core.models import StackFrame

_EXCEPTION_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_$][\w$.]*(?:Exception|Error|Throwable))"
    r"(?::\s*(?P<message>.*))?\s*$"
)

_REFLECTION_PREFIXES = (
    "jdk.internal.reflect.",
    "java.lang.reflect.",
    "sun.reflect.",
)
_REFLECTION_MARKERS = ("$$EnhancerBy", "$$FastClassBy", "$Proxy")


def parse_exception_line(line: str) -> tuple[str, str | None] | None:
    """Parse ``com.example.FooException: message`` into a type and message."""
    match = _EXCEPTION_RE.match(line)
    if match is None:
        return None
    message = match.group("message")
    if message is not None:
        message = message.strip() or None
    return match.group("type"), message


def parse_frame(line: str) -> StackFrame | None:
    """Parse a Java ``at ...`` stack frame; return None for non-frame lines."""
    text = line.strip()
    if not text.startswith("at "):
        return None

    body = text[3:].strip()
    if "(" in body and body.endswith(")"):
        qualified, location = body[:-1].split("(", 1)
    else:
        qualified, location = body, ""

    class_path, separator, method_name = qualified.strip().rpartition(".")
    if not separator or not class_path or not method_name:
        return None

    class_name = class_path.rsplit("/", 1)[-1]
    file_name, line_number, is_native = _parse_location(location)
    return StackFrame(
        class_name=class_name,
        method_name=method_name,
        file_name=file_name,
        line_number=line_number,
        is_native=is_native,
        is_reflection=is_reflection_class(class_name),
        raw=text,
    )


def is_reflection_class(class_name: str) -> bool:
    """Return True for common reflection/proxy frame classes."""
    if class_name.startswith(_REFLECTION_PREFIXES):
        return True
    return any(marker in class_name for marker in _REFLECTION_MARKERS)


def _parse_location(location: str) -> tuple[str | None, int | None, bool]:
    loc = location.strip()
    if not loc:
        return None, None, False

    lower = loc.lower()
    if lower == "native method":
        return None, None, True
    if lower == "unknown source":
        return None, None, False

    file_name = loc
    line_number: int | None = None
    if ":" in loc:
        maybe_file, maybe_line = loc.rsplit(":", 1)
        if maybe_line.isdigit():
            file_name = maybe_file
            line_number = int(maybe_line)
    return (file_name.strip() or None), line_number, False
