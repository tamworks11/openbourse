"""Tests for the docker-compose pre-market sync scheduler.

``scripts/market_sync_scheduler.py`` is a standalone script, not part of
the installed package, so it's loaded by path here.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest

_SCHEDULER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "market_sync_scheduler.py"


def _load_scheduler() -> ModuleType:
    spec = importlib.util.spec_from_file_location("market_sync_scheduler", _SCHEDULER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scheduler = _load_scheduler()
ET = scheduler.ET


class TestNextRun:
    def test_same_day_when_before_target(self) -> None:
        # Wednesday 08:00 ET -> the 09:00 ET run later that day.
        now = datetime(2026, 5, 13, 8, 0, tzinfo=ET)
        run = scheduler.next_run(now)
        assert run == datetime(2026, 5, 13, 9, 0, tzinfo=ET)

    def test_rolls_to_next_day_when_past_target(self) -> None:
        # Wednesday 10:00 ET -> Thursday 09:00 ET.
        now = datetime(2026, 5, 13, 10, 0, tzinfo=ET)
        run = scheduler.next_run(now)
        assert run == datetime(2026, 5, 14, 9, 0, tzinfo=ET)

    def test_rolls_forward_when_exactly_at_target(self) -> None:
        # Exactly 09:00 counts as "past" — next run is the following day.
        now = datetime(2026, 5, 13, 9, 0, tzinfo=ET)
        run = scheduler.next_run(now)
        assert run == datetime(2026, 5, 14, 9, 0, tzinfo=ET)

    def test_friday_afternoon_skips_to_monday(self) -> None:
        now = datetime(2026, 5, 15, 14, 0, tzinfo=ET)  # Friday
        run = scheduler.next_run(now)
        assert run == datetime(2026, 5, 18, 9, 0, tzinfo=ET)  # Monday

    @pytest.mark.parametrize(
        "weekend_day",
        [
            datetime(2026, 5, 16, 8, 0, tzinfo=ET),  # Saturday
            datetime(2026, 5, 17, 8, 0, tzinfo=ET),  # Sunday
        ],
    )
    def test_weekend_skips_to_monday(self, weekend_day: datetime) -> None:
        run = scheduler.next_run(weekend_day)
        assert run == datetime(2026, 5, 18, 9, 0, tzinfo=ET)

    def test_honours_custom_hour_and_minute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENBOURSE_SYNC_HOUR", "6")
        monkeypatch.setenv("OPENBOURSE_SYNC_MINUTE", "30")
        now = datetime(2026, 5, 13, 5, 0, tzinfo=ET)
        run = scheduler.next_run(now)
        assert run == datetime(2026, 5, 13, 6, 30, tzinfo=ET)


class TestRunTimeEnv:
    def test_defaults_to_nine_oclock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENBOURSE_SYNC_HOUR", raising=False)
        monkeypatch.delenv("OPENBOURSE_SYNC_MINUTE", raising=False)
        assert scheduler._run_hour() == 9
        assert scheduler._run_minute() == 0

    def test_reads_overrides_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENBOURSE_SYNC_HOUR", "7")
        monkeypatch.setenv("OPENBOURSE_SYNC_MINUTE", "45")
        assert scheduler._run_hour() == 7
        assert scheduler._run_minute() == 45
