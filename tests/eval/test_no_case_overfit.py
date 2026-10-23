"""Guard against case ids and expected answers leaking into runtime code."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers import ROOT

_SRC = ROOT / "src" / "tracemind"
_RUNTIME_DIRS = (
    _SRC / "diagnosis",
    _SRC / "tools",
    _SRC / "indexing",
    _SRC / "log_analysis",
    _SRC / "verification",
    _SRC / "artifacts",
)
_FORBIDDEN_TOKENS = (
    "v03-c1",
    "v03-c2",
    "v03-c3",
    "missing-row",
    "duplicate-callback",
    "mapper-stub",
    "PaymentNotifier",
    "minimal-order-service",
    "OrderMapper",
    "OrderService",
    "10086",
    "expected_top_cause",
    "expected_evidence_refs",
    "already PAID",
    "重复回调",
    "默认方法",
    "retry probe",
    "fixtures/",
    "v04-j1",
    "v04-j2",
    "v04-jvm",
    "cpu-high",
    "memory-oom",
    "PricingService",
    "PricingController",
    "pricing-exec-1",
    "recalculate",
    "ReportCache",
    "ReportService",
    "ReportController",
    "ReportEntry",
    "unbounded-cache",
    "184000",
    "1150000",
    "966000000",
    "expected_jvm_tools",
    "expected_refutations",
    "expected_artifacts",
)


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for directory in _RUNTIME_DIRS:
        assert directory.is_dir(), f"runtime directory is missing: {directory}"
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".j2", ".txt", ".md"}:
                continue
            files.append(path)
    return files


@pytest.mark.parametrize(
    "token",
    _FORBIDDEN_TOKENS,
    ids=_FORBIDDEN_TOKENS,
)
def test_runtime_has_no_case_specific_tokens(token: str) -> None:
    """No runtime, prompt, tool, or verification module may name a case answer."""
    offenders = [
        path.relative_to(ROOT)
        for path in _runtime_files()
        if token in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not offenders, (
        f"case-specific token {token!r} leaked into runtime files: {offenders}"
    )


def test_runtime_does_not_read_expected_or_mock_fixtures() -> None:
    """The runtime must not load test expectations or mock scripts."""
    suspicious: list[tuple[Path, str]] = []
    for path in _runtime_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("fixtures", "expected/", "mock/", "mock_script"):
            if marker in text:
                suspicious.append((path.relative_to(ROOT), marker))
    assert not suspicious, (
        f"runtime reads test-only data or expectations: {suspicious}"
    )


def test_scan_covers_the_runtime_packages() -> None:
    """Keep the overfit scan honest if package layout changes."""
    relative = {
        path.relative_to(_SRC).parts[0] for path in _runtime_files()
    }
    assert relative == {
        "diagnosis",
        "tools",
        "indexing",
        "log_analysis",
        "verification",
        "artifacts",
    }
    assert len(_runtime_files()) >= 20
