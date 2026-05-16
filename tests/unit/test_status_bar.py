"""Tests for the StatusBar widget — the DB-sync freshness marker."""

from __future__ import annotations

from datetime import UTC, datetime

from openbourse.providers.base import Providers
from openbourse.tui.widgets import StatusBar
from openbourse.tui.widgets.status_bar import _weekday_seconds


class TestWeekdaySeconds:
    def test_counts_full_span_within_one_weekday(self) -> None:
        # Wednesday 2026-05-13, 10:00 -> 13:00 = 3 hours.
        start = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
        end = datetime(2026, 5, 13, 13, 0, tzinfo=UTC)
        assert _weekday_seconds(start, end) == 3 * 3600

    def test_excludes_weekend_time(self) -> None:
        # Friday 22:00 -> Monday 00:30. Only Fri 22:00-24:00 (2h) and
        # Mon 00:00-00:30 (0.5h) count; Sat + Sun are dropped.
        start = datetime(2026, 5, 15, 22, 0, tzinfo=UTC)  # Friday
        end = datetime(2026, 5, 18, 0, 30, tzinfo=UTC)  # Monday
        assert _weekday_seconds(start, end) == 2.5 * 3600

    def test_returns_zero_when_end_not_after_start(self) -> None:
        moment = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
        assert _weekday_seconds(moment, moment) == 0.0
        assert _weekday_seconds(moment, moment.replace(hour=9)) == 0.0


class TestDbSyncMarker:
    def test_marker_is_red_when_never_synced(self, stub_providers: Providers) -> None:
        bar = StatusBar(stub_providers)
        marker = bar._db_sync_marker(datetime(2026, 5, 13, 12, 0, tzinfo=UTC))
        assert "never synced" in marker
        assert "[red]" in marker

    def test_marker_is_green_when_fresh(self, stub_providers: Providers) -> None:
        synced = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)  # Wednesday
        bar = StatusBar(stub_providers, last_synced_at=synced)
        # One hour later — within the 2h threshold.
        marker = bar._db_sync_marker(datetime(2026, 5, 13, 11, 0, tzinfo=UTC))
        assert "[green]" in marker
        assert "[yellow]" not in marker
        assert "[red]" not in marker
        assert "2026-05-13 10:00 UTC" in marker

    def test_marker_turns_yellow_when_over_two_hours_stale(self, stub_providers: Providers) -> None:
        synced = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)  # Wednesday
        bar = StatusBar(stub_providers, last_synced_at=synced)
        # Three weekday hours later — past the 2h threshold.
        marker = bar._db_sync_marker(datetime(2026, 5, 13, 13, 0, tzinfo=UTC))
        assert "[yellow]" in marker
        assert "2026-05-13 10:00 UTC" in marker

    def test_marker_stays_green_over_a_weekend(self, stub_providers: Providers) -> None:
        # Synced Friday 23:00; now Sunday noon. Raw gap is ~37h, but the
        # weekend doesn't count — only Fri 23:00-24:00 (1h) does.
        synced = datetime(2026, 5, 15, 23, 0, tzinfo=UTC)  # Friday
        bar = StatusBar(stub_providers, last_synced_at=synced)
        marker = bar._db_sync_marker(datetime(2026, 5, 17, 12, 0, tzinfo=UTC))  # Sunday
        assert "[green]" in marker

    def test_marker_yellow_on_monday_when_weekend_sync_went_stale(
        self, stub_providers: Providers
    ) -> None:
        # Synced Friday 23:00; now Monday 02:00. Fri 1h + Mon 2h = 3h > 2h.
        synced = datetime(2026, 5, 15, 23, 0, tzinfo=UTC)  # Friday
        bar = StatusBar(stub_providers, last_synced_at=synced)
        marker = bar._db_sync_marker(datetime(2026, 5, 18, 2, 0, tzinfo=UTC))  # Monday
        assert "[yellow]" in marker

    def test_update_db_synced_changes_the_recorded_time(self, stub_providers: Providers) -> None:
        bar = StatusBar(stub_providers)
        assert "never synced" in bar._db_sync_marker(datetime(2026, 5, 13, 12, 0, tzinfo=UTC))
        bar.update_db_synced(datetime(2026, 5, 13, 11, 30, tzinfo=UTC))
        marker = bar._db_sync_marker(datetime(2026, 5, 13, 12, 0, tzinfo=UTC))
        assert "2026-05-13 11:30 UTC" in marker
        assert "[green]" in marker


class TestStatusBarLayout:
    """The status bar must render across two rows. A single row can't fit
    the DB-sync marker without truncating it — this test guards against a
    regression back to the cramped single-row layout."""

    def test_compose_yields_two_rows(self, stub_providers: Providers) -> None:
        from textual.containers import Horizontal

        bar = StatusBar(stub_providers)
        rows = list(bar.compose())
        assert len(rows) == 2
        assert all(isinstance(r, Horizontal) for r in rows)

    def test_db_sync_marker_lives_on_its_own_row(self, stub_providers: Providers) -> None:
        # Row 2's left segment is dedicated to the DB-sync marker, so it
        # has the full 1fr width to itself and can't be clipped by the
        # identity text the way it was when both shared row 1.
        synced = datetime(2026, 5, 13, 10, 0, tzinfo=UTC)
        bar = StatusBar(stub_providers, last_synced_at=synced)
        bar._refresh_text()
        row2_left = bar._row2_left.renderable
        assert "DB synced" in str(row2_left)
        # The identity row must NOT carry the DB marker.
        assert "DB synced" not in str(bar._row1_left.renderable)
