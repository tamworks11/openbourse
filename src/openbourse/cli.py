"""Typer CLI exposing the ``bourse`` command."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from openbourse import __version__
from openbourse.config import get_settings
from openbourse.db import (
    InstrumentRow,
    create_engine_from_url,
    get_session_factory,
)
from openbourse.db.repositories import FundamentalsRepository, InstrumentRepository
from openbourse.domain import FundamentalsSnapshot, Instrument
from openbourse.providers import build_providers
from openbourse.providers.fmp import StubFundamentalsProvider
from openbourse.screening import BUILTIN_SCREENS, ScreeningService

__all__ = ["app"]

app = typer.Typer(
    name="bourse",
    help="openbourse — terminal-first equity research workstation.",
    add_completion=False,
    no_args_is_help=True,
)
db_app = typer.Typer(help="Database lifecycle commands.")
screen_app = typer.Typer(help="Run and inspect screens without the TUI.")
app.add_typer(db_app, name="db")
app.add_typer(screen_app, name="screen")

console = Console()


@app.command()
def version() -> None:
    """Print the installed openbourse version."""
    console.print(f"openbourse {__version__}")


@app.command()
def run(
    screen_name: str = typer.Option(
        "quality_compounders", "--screen", "-s", help="Screen to launch with."
    ),
) -> None:
    """Launch the Textual TUI."""
    if screen_name not in BUILTIN_SCREENS:
        raise typer.BadParameter(f"Unknown screen {screen_name!r}")

    universe = asyncio.run(_load_universe_or_fixture())
    from openbourse.tui import BourseApp

    BourseApp(providers=build_providers(), universe=universe).run()


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply Alembic migrations to the configured database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_repo_root() / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
    console.print("[green]migrations applied[/green]")


@db_app.command("seed")
def db_seed() -> None:
    """Load the bundled seed dataset into the configured database."""
    asyncio.run(_seed())
    console.print("[green]seed loaded[/green]")


@screen_app.command("list")
def screen_list() -> None:
    """List built-in screens."""
    table = Table(title="Built-in screens", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("description")
    for name, defn in BUILTIN_SCREENS.items():
        table.add_row(name, defn.description)
    console.print(table)


@screen_app.command("run")
def screen_run(
    name: str = typer.Argument(..., help="Screen name (see `bourse screen list`)."),
    output: str = typer.Option("table", "--output", "-o", help="table | json"),
) -> None:
    """Run a screen against the database (or seed fixture) and print results."""
    if name not in BUILTIN_SCREENS:
        raise typer.BadParameter(f"Unknown screen {name!r}")

    universe = asyncio.run(_load_universe_or_fixture())
    result = ScreeningService().run(BUILTIN_SCREENS[name], universe)

    if output == "json":
        console.print_json(json.dumps(_result_to_dict(result), default=_json_default))
        return

    table = Table(title=f"{result.screen.name} — {result.filtered_count} candidates")
    table.add_column("#", justify="right")
    table.add_column("ticker", style="cyan")
    table.add_column("name")
    table.add_column("mkt cap", justify="right")
    table.add_column("rev gr", justify="right")
    table.add_column("gm", justify="right")
    table.add_column("fcf yld", justify="right")
    table.add_column("score", justify="right", style="bold")
    table.add_column("verdict")
    for i, c in enumerate(result.candidates, start=1):
        table.add_row(
            f"{i:02d}",
            c.instrument.ticker,
            c.instrument.name,
            f"${c.snapshot.market_cap_usd / 1e9:.1f}B",
            f"{c.snapshot.revenue_growth_pct:+.1f}%",
            f"{c.snapshot.gross_margin_pct:.1f}%",
            f"{c.snapshot.fcf_yield_pct:.1f}%",
            str(c.score),
            c.verdict.value,
        )
    console.print(table)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "screen": asdict(result.screen),
        "ran_at": result.ran_at,
        "universe_size": result.universe_size,
        "candidates": [
            {
                "instrument": asdict(c.instrument),
                "snapshot": asdict(c.snapshot),
                "score": c.score,
                "verdict": c.verdict.value,
            }
            for c in result.candidates
        ],
    }


async def _load_universe_or_fixture() -> list[tuple[Instrument, FundamentalsSnapshot]]:
    """Return ``(instrument, snapshot)`` pairs.

    Tries the configured database first. If the database is unreachable or
    empty, falls back to the bundled stub fixture so the app is usable
    out-of-the-box.
    """
    try:
        engine = create_engine_from_url(get_settings().database_url)
        factory = get_session_factory(engine)
        async with factory() as session:
            fund_repo = FundamentalsRepository(session)
            pairs = await fund_repo.latest_for_all()
        await engine.dispose()
        if pairs:
            return pairs
    except (OSError, RuntimeError) as exc:  # pragma: no cover - DB unreachable
        console.print(f"[yellow]falling back to stub fixture: {exc}[/yellow]", style="dim")
    except Exception as exc:  # pragma: no cover - any DB driver error
        console.print(f"[yellow]falling back to stub fixture: {exc}[/yellow]", style="dim")

    stub = StubFundamentalsProvider()
    instruments_payload = json.loads((Path(__file__).parent / "data" / "seed.json").read_text())[
        "instruments"
    ]
    instruments = [
        Instrument(
            ticker=row["ticker"],
            name=row["name"],
            sector=row.get("sector"),
            exchange=row.get("exchange"),
            cik=row.get("cik"),
        )
        for row in instruments_payload
    ]
    out: list[tuple[Instrument, FundamentalsSnapshot]] = []
    for inst in instruments:
        if inst.ticker in stub.tickers:
            out.append((inst, await stub.fetch(inst.ticker)))
    return out


async def _seed() -> None:
    settings = get_settings()
    engine = create_engine_from_url(settings.database_url)
    factory = get_session_factory(engine)
    payload = json.loads((Path(__file__).parent / "data" / "seed.json").read_text())
    try:
        async with factory() as session:
            instr_repo = InstrumentRepository(session)
            fund_repo = FundamentalsRepository(session)
            inst_rows: dict[str, InstrumentRow] = {}
            for entry in payload["instruments"]:
                row = await instr_repo.upsert(
                    Instrument(
                        ticker=entry["ticker"],
                        name=entry["name"],
                        sector=entry.get("sector"),
                        exchange=entry.get("exchange"),
                        cik=entry.get("cik"),
                    )
                )
                inst_rows[row.ticker] = row
            for entry in payload["fundamentals"]:
                inst_row = inst_rows.get(entry["ticker"])
                if inst_row is None:
                    continue
                snap = FundamentalsSnapshot(
                    ticker=entry["ticker"],
                    as_of=date.fromisoformat(entry["as_of"]),
                    market_cap_usd=float(entry["market_cap_usd"]),
                    revenue_growth_pct=float(entry["revenue_growth_pct"]),
                    gross_margin_pct=float(entry["gross_margin_pct"]),
                    net_debt_to_ebitda=float(entry["net_debt_to_ebitda"]),
                    fcf_yield_pct=float(entry["fcf_yield_pct"]),
                    revenue_ttm_usd=entry.get("revenue_ttm_usd"),
                    ebitda_ttm_usd=entry.get("ebitda_ttm_usd"),
                )
                await fund_repo.upsert(inst_row.id, snap)
            await session.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
