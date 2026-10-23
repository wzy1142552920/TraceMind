"""Bounded, best-effort redaction for artifact excerpts and tool output."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_SECRET_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api[_-]?key",
    "access[_-]?key",
    "credential",
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<key>\"?(?:"
    + "|".join(_SECRET_KEYS)
    + r")\"?)(?P<sep>\s*[:=]\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)(?P<prefix>\"?authorization\"?\s*[:=]\s*)"
    r"(?:(?P<scheme>bearer|basic)\s+)?"
    r"(?P<value>\"[^\"]*\"|'[^']*'|\S+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/-]+=*)")

_CATEGORY_BY_KEY = {
    "password": "password",
    "passwd": "password",
    "pwd": "password",
    "secret": "secret",
    "token": "token",
    "apikey": "api_key",
    "api_key": "api_key",
    "api-key": "api_key",
    "accesskey": "access_key",
    "access_key": "access_key",
    "access-key": "access_key",
    "credential": "credential",
    "authorization": "authorization",
}


def redact_text(text: str) -> tuple[str, list[str]]:
    """Replace common secret assignments and return the matched categories.

    This is a defense-in-depth measure, not a guarantee that every possible
    secret format is removed.
    """
    if not text:
        return text, []

    categories: set[str] = set()

    def replace_authorization(match: re.Match[str]) -> str:
        categories.add("authorization")
        scheme = match.group("scheme")
        scheme_prefix = f"{scheme} " if scheme else ""
        return f"{match.group('prefix')}{scheme_prefix}{REDACTED}"

    redacted = _AUTHORIZATION_RE.sub(replace_authorization, text)

    def replace_bearer(match: re.Match[str]) -> str:
        categories.add("authorization")
        return f"{match.group(1)}{REDACTED}"

    redacted = _BEARER_RE.sub(replace_bearer, redacted)

    def replace_assignment(match: re.Match[str]) -> str:
        raw_key = match.group("key").strip("\"'").lower()
        normalized = raw_key.replace("-", "_")
        categories.add(_CATEGORY_BY_KEY.get(normalized, normalized))
        return f"{match.group('key')}{match.group('sep')}{REDACTED}"

    redacted = _ASSIGNMENT_RE.sub(replace_assignment, redacted)
    return redacted, sorted(categories)
