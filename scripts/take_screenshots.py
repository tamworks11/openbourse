"""Generate the SVG screenshots embedded in the README.

Boots the TUI with the bundled seed dataset, drives it through a few
representative states (main screener, brief screen with charts, filter
editor modal), and writes each one to ``docs/screenshots/`` as a vector
SVG. GitHub renders these inline, so they stay sharp at any zoom level
and don't need to be regenerated when fonts or themes shift.

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

from openbourse.cli import _seed_history, _seed_universe
from openbourse.providers import build_providers
from openbourse.tui import BourseApp

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SIZE = (160, 70)  # wide enough for detail pane; tall enough for ROIC + valuation


async def _shoot_screener(out: Path) -> None:
    """Capture the main screener: stats, candidates table, detail pane."""
    universe = _seed_universe()
    history = _seed_history()
    app = BourseApp(providers=build_providers(), universe=universe, history=history)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        # Move down a couple rows so the cursor highlight + detail pane
        # is on a row with rich data (CDNS sits at index 1 alphabetically
        # among the seeded compounders).
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
