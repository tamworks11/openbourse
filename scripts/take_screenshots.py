"""Generate the SVG screenshots embedded in the README.

Boots the TUI, drives it through a few representative states (main
screener, brief screen with charts, filter editor modal), and writes each
one to ``docs/screenshots/`` as a vector SVG. GitHub renders these inline,
so they stay sharp at any zoom level and don't need to be regenerated when
fonts or themes shift.

Data sources differ by shot:

* ``screener.svg`` captures the **live database** when one is populated,
  so the README reflects a real ingested universe. It falls back to the
  bundled seed fixture when no DB is reachable (e.g. a fresh contributor
  clone), so the script never hard-fails.
* ``brief.svg`` and ``filter_editor.svg`` always use the bundled seed
  fixture — they stay deterministic and reproducible by anyone.

Run with::

    poetry run python scripts/take_screenshots.py

Idempotent — safe to re-run any time the UI changes.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

# Force stub mode so screenshots are deterministic regardless of the
# contributor's `.env`. Has to happen before any openbourse import that
# triggers settings caching.
os.environ["OPENBOURSE_USE_STUBS"] = "true"
os.environ.pop("OPENBOURSE_FMP_API_KEY", None)
os.environ.pop("OPENBOURSE_CLAUDE_API_KEY", None)

# ruff: noqa: E402  (imports follow env-var setup deliberately)
from openbourse import config

config.reset_settings_cache()

from openbourse.cli import _load_universe_and_history, _seed_history, _seed_universe
from openbourse.providers import build_providers
from openbourse.tui import BourseApp

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SIZE = (160, 70)  # wide enough for detail pane; tall enough for ROIC + valuation


async def _shoot_screener(out: Path) -> None:
    """Capture the main screener: stats, candidates table, detail pane.

    Pulls the universe from the live database so the screenshot shows a
    real ingested universe. ``_load_universe_and_history`` falls back to
    the bundled seed fixture when the DB is empty or unreachable, so this
    still works on a fresh clone — it just shows the 10 seed tickers then.
    """
    universe, history, last_synced_at = await _load_universe_and_history()
    app = BourseApp(
        providers=build_providers(),
        universe=universe,
        history=history,
        last_synced_at=last_synced_at,
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        # Move the cursor down so the detail pane lands on a row with
        # rich data rather than the top row.
        await pilot.press("down", "down")
        await pilot.pause()
        app.save_screenshot(str(out))


async def _shoot_brief(out: Path) -> None:
    """Capture the brief: fundamentals header, history charts, AI summary."""
    universe = _seed_universe()
    history = _seed_history()
    app = BourseApp(providers=build_providers(), universe=universe, history=history)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        # Press enter on the first row to push the brief screen.
        await pilot.press("enter")
        # The stub brief provider returns instantly, but the worker still
        # needs a tick to render. One pause keeps us robust to that.
        await pilot.pause()
        await pilot.pause()
        app.save_screenshot(str(out))


async def _shoot_filter_editor(out: Path) -> None:
    """Capture the filter editor modal — toggles + inputs per criterion."""
    universe = _seed_universe()
    history = _seed_history()
    app = BourseApp(providers=build_providers(), universe=universe, history=history)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()
        app.save_screenshot(str(out))


async def main() -> None:
    """Run every shooter in turn and report the size of each output file."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("screener.svg", _shoot_screener),
        ("brief.svg", _shoot_brief),
        ("filter_editor.svg", _shoot_filter_editor),
    ]
    for filename, fn in targets:
        path = OUT_DIR / filename
        await fn(path)
        size_kb = path.stat().st_size / 1024
        print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())
