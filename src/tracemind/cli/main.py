"""TraceMind command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console

from tracemind import __version__
from tracemind.core.errors import JavaIndexError, LLMConfigError, LogParseError
from tracemind.diagnosis.budget import Budget
from tracemind.diagnosis.report import build_report
from tracemind.diagnosis.runtime import DiagnosisRuntime
from tracemind.diagnosis.state import RuntimeState
from tracemind.indexing.java_index import TreeSitterJavaIndex
from tracemind.llm.config import (
    LLMSettings,
    load_project_env,
    require_api_key,
    resolve_settings,
)
from tracemind.llm.deepseek import DeepSeekProvider
from tracemind.llm.mock import MockProvider
from tracemind.llm.provider import LLMProvider, LLMProviderError
from tracemind.log_analysis.parser import LogParser
from tracemind.storage.run_store import RunStore

app = typer.Typer(
    name="tracemind",
    help="Local-first, evidence-driven Java incident localization agent.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    """Print the package version and exit."""
    if value:
        typer.echo(f"tracemind {__version__}")
        raise typer.Exit()


def _fail(message: str, code: int = 1) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=code)


def _build_provider(
    provider_name: str,
    mock_script: Path | None,
    settings: LLMSettings | None,
) -> tuple[LLMProvider, str]:
    if provider_name == "mock":
        script = mock_script or Path("fixtures/mock/basic_plan.json")
        try:
            return MockProvider.from_script(script), "script"
        except LLMProviderError as exc:
            _fail(f"mock provider error: {exc}", code=1)
    if provider_name == "deepseek":
        if settings is None:
            _fail("DeepSeek settings are unavailable", code=2)
        return (
            DeepSeekProvider(
                model=settings.model,
                base_url=settings.base_url,
                api_key_env=settings.api_key_env,
                max_tokens=settings.max_tokens,
                timeout=settings.timeout_seconds,
                max_retries=settings.max_retries,
            ),
            settings.model,
        )
    _fail(f"unsupported provider: {provider_name}", code=2)


def _exit_code(result, report) -> int:
    if result.state is RuntimeState.FAILED:
        return 1
    if result.state is RuntimeState.STOPPED_BUDGET:
        return 4
    if report.status == "insufficient_data":
        return 3
    return 0


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """TraceMind command-line interface."""


@app.command()
def diagnose(
    log: Path = typer.Option(
        ...,
        "--log",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to a log file.",
    ),
    repo: Path = typer.Option(
        ...,
        "--repo",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Path to a Java repository.",
    ),
    service: str = typer.Option(..., "--service", help="Service name."),
    provider: str = typer.Option(
        "mock",
        "--provider",
        help="LLM provider to use: mock or deepseek.",
    ),
    mock_script: Path | None = typer.Option(
        None,
        "--mock-script",
        help="Path to a mock response script (provider=mock).",
    ),
    output_dir: Path = typer.Option(
        Path(".tracemind/runs"),
        "--output-dir",
        help="Directory for run artifacts.",
    ),
    max_iterations: int = typer.Option(
        6,
        "--max-iterations",
        help="Maximum planning iterations.",
    ),
    max_tool_calls: int = typer.Option(
        8,
        "--max-tool-calls",
        help="Maximum tool calls.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="LLM model override (default: deepseek-flash).",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="OpenAI-compatible base URL override.",
    ),
    llm_timeout: float | None = typer.Option(
        None,
        "--llm-timeout",
        help="Per-request LLM timeout in seconds.",
    ),
    llm_max_retries: int | None = typer.Option(
        None,
        "--llm-max-retries",
        help="Maximum transient LLM retries (0-2).",
    ),
    llm_max_tokens: int | None = typer.Option(
        None,
        "--llm-max-tokens",
        help="Maximum completion tokens.",
    ),
    max_repair_attempts: int | None = typer.Option(
        None,
        "--max-repair-attempts",
        help="Maximum plan repair attempts (0-5).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print a machine-readable summary instead of rich text.",
    ),
) -> None:
    """Diagnose a Java incident from a log file and a local repository."""
    provider_name = provider.lower()
    settings: LLMSettings | None = None

    if provider_name == "deepseek":
        try:
            load_project_env()
            settings = resolve_settings(
                model=model,
                base_url=base_url,
                timeout=llm_timeout,
                max_tokens=llm_max_tokens,
                max_retries=llm_max_retries,
                repair_attempts=max_repair_attempts,
            )
            require_api_key(settings)
        except LLMConfigError as exc:
            _fail(str(exc), code=2)

    llm, model_label = _build_provider(provider_name, mock_script, settings)

    try:
        parsed_log = LogParser().parse(log)
    except LogParseError as exc:
        _fail(f"log parsing failed: {exc}", code=1)

    java_index = TreeSitterJavaIndex()
    try:
        index_stats = java_index.index(repo)
    except JavaIndexError as exc:
        _fail(f"repository indexing failed: {exc}", code=1)

    if index_stats.errors:
        console.print(
            f"[yellow]index warnings: {len(index_stats.errors)} file(s)[/yellow]"
        )

    runtime = DiagnosisRuntime(repo_root=repo)
    try:
        result = runtime.run(
            parsed_log,
            java_index,
            service,
            llm,
            Budget(
                max_iterations=max_iterations,
                max_tool_calls=max_tool_calls,
            ),
        )
    except Exception as exc:  # keep CLI failures explicit and bounded
        _fail(f"diagnosis failed: {exc}", code=1)

    try:
        report = build_report(result, parsed_log, repo)
        run_meta = {
            "run_id": result.run_id,
            "incident_id": result.incident_id,
            "service": result.service,
            "provider": provider_name,
            "model": model_label,
            "llm": {
                "provider": provider_name,
                "model": model_label,
                **(
                    settings.public_config()
                    if settings is not None
                    else {}
                ),
            },
            "log_path": str(log),
            "repo_path": str(repo),
            "state": result.state.value,
            "stop_reason": result.stop_reason.value,
            "budget_usage": result.budget_usage,
            "index": {
                "files": index_stats.files_indexed,
                "symbols": index_stats.symbols_indexed,
                "errors": len(index_stats.errors),
            },
        }
        run_dir = RunStore(output_dir).write(result, report, run_meta)
    except OSError as exc:
        _fail(f"failed to write run artifacts: {exc}", code=1)

    report_path = run_dir / "report.md"
    exit_code = _exit_code(result, report)

    if json_output:
        summary = {
            "run_id": result.run_id,
            "incident_id": result.incident_id,
            "status": report.status,
            "provider": provider_name,
            "model": model_label,
            "stop_reason": result.stop_reason.value,
            "evidence_count": len(result.evidence),
            "tool_calls": len(result.tool_calls),
            "report_path": str(report_path),
            "run_dir": str(run_dir),
        }
        typer.echo(json.dumps(summary, ensure_ascii=False))
    else:
        console.print(f"[bold]TraceMind[/bold] run={result.run_id}")
        console.print(f"Status: [bold]{report.status}[/bold]")
        if report.root_causes:
            console.print(
                f"Top candidate: {report.root_causes[0].statement}",
                markup=False,
            )
        else:
            console.print("Top candidate: (none)")
        console.print(
            f"Evidence: {len(result.evidence)} | "
            f"Tool calls: {len(result.tool_calls)}"
        )
        console.print(
            "Validation: "
            f"citations={report.validation.citations_valid}, "
            f"evidence_ids={report.validation.evidence_ids_valid}, "
            f"status={report.validation.status_consistent}"
        )
        console.print(f"Report: {report_path}")
        console.print(f"Run dir: {run_dir}")

    if exit_code:
        raise typer.Exit(code=exit_code)
