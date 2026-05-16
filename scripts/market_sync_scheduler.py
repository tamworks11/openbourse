#!/usr/bin/env python3
"""Pre-market universe sync scheduler.

Runs inside the docker-compose ``scheduler`` service. Sleeps until shortly
before the US equity market opens (09:30 America/New_York), runs
``bourse universe sync`` to refresh the database with the latest data, then
loops. Weekends are skipped. US market holidays are not — a sync on a
holiday is harmless, it just re-fetches the same figures.

Timing is anchored to ``America/New_York`` regardless of the host's
timezone, so "09:00 ET" stays 30 minutes before the open through DST
shifts and wherever the machine happens to live.

Configurable via environment variables (see ``.env.example``):

* ``OPENBOURSE_SYNC_HOUR``   — hour (ET, 24h clock) to run. Default ``9``.
* ``OPENBOURSE_SYNC_MINUTE`` — minute (ET) to run. Default ``0``.

All output is timestamped and unbuffered so ``docker compose logs
scheduler`` shows it live.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _run_hour() -> int:
    """Hour (ET) to run the sync, from ``OPENBOURSE_SYNC_HOUR`` (default 9)."""
    return int(os.environ.get("OPENBOURSE_SYNC_HOUR", "9"))


def _run_minute() -> int:
    """Minute (ET) to run the sync, from ``OPENBOURSE_SYNC_MINUTE`` (default 0)."""
    return int(os.environ.get("OPENBOURSE_SYNC_MINUTE", "0"))


def log(message: str) -> None:
    """Print a timestamped line to stdout (captured by ``docker compose logs``)."""
    print(f"[scheduler {datetime.now(ET):%Y-%m-%d %H:%M:%S %Z}] {message}", flush=True)


def next_run(now: datetime) -> datetime:
    """Return the next weekday run time strictly after ``now`` (both ET-aware)."""
    target = now.replace(hour=_run_hour(), minute=_run_minute(), second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    while target.weekday() >= 5:  # Sat=5, Sun=6 — markets closed
        target += timedelta(days=1)
    return target


def _bourse(*args: str) -> int:
    """Invoke the ``bourse`` CLI as a subprocess; return its exit code."""
    return subprocess.run([sys.executable, "-m", "openbourse", *args], check=False).returncode


def run_sync() -> int:
    """Run ``bourse universe sync``; return its exit code."""
    log("running `bourse universe sync`")
    return _bourse("universe", "sync")


def main() -> None:
    """Apply pending migrations once, then sync on every weekday schedule tick."""
    log(f"started — sync scheduled for {_run_hour():02d}:{_run_minute():02d} ET on weekdays")

    # Apply any pending Alembic migrations once at startup so the very first
    # sync can't fail on a missing table (e.g. `sync_runs`).
    log("running `bourse db migrate`")
    if _bourse("db", "migrate") != 0:
        log("WARNING: `db migrate` failed — the first sync may not record")

    while True:
        now = datetime.now(ET)
        target = next_run(now)
        wait_seconds = (target - now).total_seconds()
        log(f"next sync at {target:%Y-%m-%d %H:%M %Z} (in {wait_seconds / 3600:.1f}h)")
        time.sleep(wait_seconds)

        code = run_sync()
        log(f"sync finished (exit code {code})")
        # Step past the target minute so the loop can't re-trigger on a
        # sync that fails instantly.
        time.sleep(60)


if __name__ == "__main__":
    main()
