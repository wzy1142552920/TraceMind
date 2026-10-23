"""Best-effort secret redaction for artifact excerpts."""

from __future__ import annotations

from tracemind.artifacts import redact_text


def test_password_assignment_is_redacted() -> None:
    redacted, categories = redact_text("db password=s3cr3t; retry=1")
    assert "s3cr3t" not in redacted
    assert "password=[REDACTED]" in redacted
    assert categories == ["password"]


def test_token_and_json_values_are_redacted() -> None:
    redacted, categories = redact_text(
        '{"token": "abc.def", "api_key": "key-123", "name": "visible"}'
    )
    assert "abc.def" not in redacted
    assert "key-123" not in redacted
    assert "visible" in redacted
    assert categories == ["api_key", "token"]


def test_authorization_bearer_is_redacted() -> None:
    redacted, categories = redact_text(
        "Authorization: Bearer eyJhbGciOi.test-token"
    )
    assert "eyJhbGciOi" not in redacted
    assert "Authorization: Bearer [REDACTED]" in redacted
    assert categories == ["authorization"]


def test_plain_bearer_token_is_redacted() -> None:
    redacted, categories = redact_text("header bearer abc.def.ghi")
    assert "abc.def.ghi" not in redacted
    assert categories == ["authorization"]


def test_no_secret_leaves_text_unchanged() -> None:
    text = "pricing-recalc threads are RUNNABLE"
    redacted, categories = redact_text(text)
    assert redacted == text
    assert categories == []


def test_empty_text() -> None:
    assert redact_text("") == ("", [])
