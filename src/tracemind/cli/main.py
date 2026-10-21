"""TraceMind command-line interface."""

from __future__ import annotations

import typer
from rich.console import Console

from tracemind import __version__

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
    log: str = typer.Option(..., "--log", help="Path to a log file."),
    repo: str = typer.Option(..., "--repo", help="Path to a Java repository."),
    service: str = typer.Option(..., "--service", help="Service name."),
    provider: str = typer.Option(
        "mock",
        "--provider",
        help="LLM provider to use: mock or deepseek.",
    ),
    mock_script: str | None = typer.Option(
        None,
        "--mock-script",
        help="Path to a mock response script (provider=mock).",
    ),
    output_dir: str = typer.Option(
        ".tracemind/runs",
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
) -> None:
    """Diagnose a Java incident from a log file and a local repository.

    T1 placeholder: the diagnosis loop is implemented in T7.
    """
    console.print("[yellow]diagnose is not implemented yet (T7).[/yellow]")
    raise typer.Exit(code=1)
