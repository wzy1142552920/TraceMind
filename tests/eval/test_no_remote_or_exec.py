"""Static checks that TraceMind never collects JVM data or executes commands."""

from __future__ import annotations

import re
from pathlib import Path

from helpers import ROOT

_SRC = ROOT / "src" / "tracemind"
_PY_FILES = tuple(sorted(_SRC.rglob("*.py")))
_FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+"
    r"(subprocess|socket|requests|httpx|aiohttp|ftplib|telnetlib|smtplib|"
    r"xmlrpc|http\.client|urllib\.request|multiprocessing)\b",
    re.MULTILINE,
)
_FORBIDDEN_EXEC_RE = re.compile(
    r"\b(?:subprocess\.(?:Popen|run|call|check_call|check_output)|"
    r"os\.(?:system|popen|execv|execve|spawnv|spawnl)|"
    r"os\.fork|pty\.spawn|ctypes\.CDLL)\b"
)
_JVM_COLLECT_RE = re.compile(
    r"(?:subprocess|os\.(?:system|popen)|Popen)[^\n]*"
    r"(?:jstack|jcmd|jmap|jfr|jattach)",
    re.IGNORECASE,
)


def _files() -> list[Path]:
    assert _PY_FILES, "source tree is missing Python modules"
    return list(_PY_FILES)


def test_source_has_no_process_or_network_clients() -> None:
    """Only the LLM provider may use the network; no process APIs are allowed."""
    offenders: list[tuple[str, str]] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN_IMPORT_RE.finditer(text):
            offenders.append((str(path.relative_to(ROOT)), match.group(0)))
        for match in _FORBIDDEN_EXEC_RE.finditer(text):
            offenders.append((str(path.relative_to(ROOT)), match.group(0)))
    assert not offenders, f"network/process APIs found: {offenders}"


def test_source_never_executes_jvm_collection_tools() -> None:
    """jstack/jcmd/jmap may be parsed as text but never invoked."""
    offenders: list[tuple[str, str]] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for match in _JVM_COLLECT_RE.finditer(text):
            offenders.append((str(path.relative_to(ROOT)), match.group(0)))
    assert not offenders, f"JVM collection commands found: {offenders}"


def test_jvm_tools_are_read_only_over_artifacts() -> None:
    """The JVM tool module only reads validated bundles."""
    path = _SRC / "tools" / "jvm.py"
    text = path.read_text(encoding="utf-8")
    for marker in (
        "subprocess",
        "os.system",
        "os.popen",
        "socket",
        "write_text",
        "write_bytes",
        "os.remove",
        "unlink(",
    ):
        assert marker not in text, (
            f"JVM tools must remain read-only; found {marker!r}"
        )
    assert "ArtifactBundle" in text
    assert "parse_thread_dump" in text
    assert "parse_gc_log" in text
    assert "parse_heap_histogram" in text


def test_jvm_tools_require_artifacts_for_registration() -> None:
    """Tools are conditional on bundle kinds, not globally available."""
    path = _SRC / "tools" / "jvm.py"
    text = path.read_text(encoding="utf-8")
    assert "def register_jvm_tools(" in text
    assert "if has_dump:" in text
    assert "if has_dump and has_cpu:" in text
    assert "if ArtifactKind.GC_LOG in kinds:" in text
    assert "if ArtifactKind.HEAP_HISTOGRAM in kinds:" in text
