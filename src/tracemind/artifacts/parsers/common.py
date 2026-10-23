"""Shared, bounded helpers for JVM text parsers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from tracemind.artifacts.redaction import redact_text

MAX_TEXT_LENGTH = 512
MAX_WARNINGS = 20
_SIZE_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[KMG])?(?:B)?$",
    re.IGNORECASE,
)
_UNIT_TO_MB = {
    None: 1.0 / (1024.0 * 1024.0),
    "B": 1.0 / (1024.0 * 1024.0),
    "K": 1.0 / 1024.0,
    "M": 1.0,
    "G": 1024.0,
}


def truncate_text(text: str, limit: int = MAX_TEXT_LENGTH) -> str:
    """Return a single-line bounded excerpt suitable for evidence content."""
    collapsed = " ".join(text.split())
    redacted, _ = redact_text(collapsed)
    if len(redacted) <= limit:
        return redacted
    return redacted[: max(0, limit - 3)] + "..."


def add_warning(warnings: list[str], message: str) -> None:
    """Append a warning once, keeping the total bounded."""
    if message in warnings or len(warnings) >= MAX_WARNINGS:
        return
    warnings.append(message)


def parse_size_mb(value: str) -> float | None:
    """Parse a JVM size such as 512M, 512K, 1G, or a raw byte count."""
    match = _SIZE_RE.fullmatch(value.strip())
    if match is None:
        return None
    unit = match.group("unit")
    normalized_unit = unit.upper() if unit else None
    multiplier = _UNIT_TO_MB.get(normalized_unit)
    if multiplier is None:
        return None
    return round(float(match.group("value")) * multiplier, 3)


def nid_from_tid(tid: int) -> str:
    """Convert a decimal thread id to the lowercase hexadecimal nid form."""
    return f"0x{tid:x}"


def normalize_nid(value: str | None) -> str | None:
    """Normalize 0x1a2c/1A2C/0x01a2c to 0x1a2c for matching."""
    if value is None:
        return None
    cleaned = value.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    cleaned = cleaned.lstrip("0") or "0"
    try:
        return f"0x{int(cleaned, 16):x}"
    except ValueError:
        return None


def clean_control_characters(text: str) -> str:
    """Replace control characters that would make report text unreadable."""
    return "".join(
        " " if unicodedata.category(char).startswith("C") else char
        for char in text
    )


def unique_in_order(values: Iterable[str]) -> list[str]:
    """Deduplicate strings while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
