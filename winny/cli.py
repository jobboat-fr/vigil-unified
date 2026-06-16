"""winny — assistant-only trading helper CLI.

All commands are stubbed in P0 scaffolding. Each one exits cleanly and points
to the spec section that defines its behaviour. Real implementations land in
PRs #2 onward per SPECS.md §15.11.
"""

from __future__ import annotations

import typer
from rich.console import Console

from winny import __version__

app = typer.Typer(
    name="winny",
    help="Winny Woo — assistant-only trading helper microservice. See SPECS.md.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _stub(spec_ref: str, extra: str = "") -> None:
    """Standard 'not implemented yet — see spec ref' response."""
    msg = f"[yellow]not implemented[/yellow] — see SPECS.md {spec_ref}"
    if extra:
        msg += f" ({extra})"
    console.print(msg)


@app.command()
def version() -> None:
    """Show the installed Winny version."""
    console.print(f"winny [cyan]{__version__}[/cyan]")


@app.command()
def init() -> None:
    """Initialize ~/.winny/ state, secrets, audit DB."""
    _stub("§15.2", "P0 scaffolding pending")


@app.command()
def secrets(
    action: str = typer.Argument(..., help="set | list | delete"),
    name: str | None = typer.Argument(None),
) -> None:
    """Manage secrets in the OS keyring per §7.3."""
    _stub("§7.3", f"secrets {action} {name or ''}")


@app.command()
def backtest(
    strategy: str = typer.Argument(
        ..., help="dotted module path, e.g. winny.strategies.buy_and_hold"
    ),
    symbols: str = typer.Option(..., "--symbols", "-s", help="comma-separated"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    gate: bool = typer.Option(False, "--gate", help="apply promotion-gate thresholds (§10.1)"),
) -> None:
    """Run a backtest per §3.3.3."""
    _stub("§3.3 + §10")


@app.command("dry-run")
def dry_run(
    strategy: str = typer.Argument(...),
    symbols: str = typer.Option(..., "--symbols", "-s"),
    hours: int = typer.Option(24, "--hours", help="duration"),
    gate: bool = typer.Option(False, "--gate"),
) -> None:
    """Run a strategy in dry-run mode per §3.3.3."""
    _stub("§3.3")


@app.command()
def replay(
    from_date: str = typer.Option(..., "--from"),
    to_date: str = typer.Option(..., "--to"),
    strategy: str | None = typer.Option(None, "--strategy"),
    llm: str = typer.Option("cached", "--llm", help="cached | live"),
) -> None:
    """Replay historical decisions per §14.5.1."""
    _stub("§14.5.1")


@app.command()
def anchor() -> None:
    """Write a daily audit-log anchor per §7.4."""
    _stub("§7.4")


@app.command("lint-strategy")
def lint_strategy(
    path: str = typer.Argument(..., help="path to a WinnyStrategy module"),
) -> None:
    """Lint a WinnyStrategy for lookahead and forbidden patterns per §14.3.4 + §10.1."""
    _stub("§14.3.4")


@app.command("walkforward")
def walkforward(
    strategy: str = typer.Argument(...),
    symbols: str = typer.Option(..., "--symbols", "-s"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
) -> None:
    """Walk-forward validation per §10.3."""
    _stub("§10.3")


if __name__ == "__main__":
    app()
