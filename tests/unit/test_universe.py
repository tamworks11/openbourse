"""Tests for the universe module: loaders, ingest pipeline, summary stats."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from openbourse.providers.base import Providers
from openbourse.universe import (
    DEFAULT_BUNDLED_LIST,
    IngestSummary,
    ingest_tickers,
    load_bundled_list,
    load_tickers,
)


class TestLoaders:
    def test_load_bundled_default_list(self) -> None:
        tickers = load_bundled_list()
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert len(tickers) > 50  # popular_us is meaty

    def test_load_bundled_named_list(self) -> None:
        assert load_bundled_list(DEFAULT_BUNDLED_LIST) == load_bundled_list()

    def test_load_unknown_bundled_list_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_bundled_list("does_not_exist")

    def test_load_tickers_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "my.txt"
        path.write_text("AAPL\nmsft  # lowercase\n# comment\n\nGOOG\nAAPL  # dupe\n")
        assert load_tickers(path) == ["AAPL", "MSFT", "GOOG"]

    def test_load_tickers_strips_inline_comments(self, tmp_path: Path) -> None:
        path = tmp_path / "x.txt"
        path.write_text("AAPL # a note about Apple\nMSFT\n")
        assert load_tickers(path) == ["AAPL", "MSFT"]

    def test_load_tickers_dedupes_preserving_order(self, tmp_path: Path) -> None:
        path = tmp_path / "dupes.txt"
        path.write_text("ZZZ\nAAA\nZZZ\nBBB\nAAA\n")
        assert load_tickers(path) == ["ZZZ", "AAA", "BBB"]


class TestIngestSummary:
    def test_success_rate_handles_zero_total(self) -> None:
        s = IngestSummary()
        assert s.success_rate == 0.0

    def test_success_rate_computes_fraction(self) -> None:
        s = IngestSummary(total=10, ingested=7, failed=[("X", "err")] * 3)
        assert s.success_rate == 0.7


class TestIngestPipeline:
    async def test_ingest_persists_known_tickers(
        self, sqlite_engine: AsyncEngine, stub_providers: Providers
    ) -> None:
        factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        summary = await ingest_tickers(
            ["CDNS", "VEEV"],
            stub_providers,
            factory,
            rate_limit_seconds=0.0,
        )
        assert summary.total == 2
        assert summary.ingested == 2
        assert summary.failed == []

        # Verify the rows actually landed in the DB.
        from openbourse.db.repositories import (
            FundamentalsRepository,
            InstrumentRepository,
        )

        async with factory() as session:
            instruments = await InstrumentRepository(session).list_all()
            tickers = {inst.ticker for inst in instruments}
            pairs = await FundamentalsRepository(session).latest_for_all()

        assert {"CDNS", "VEEV"}.issubset(tickers)
        assert len(pairs) == 2
        # Stub metadata fixture supplies real names from seed.json.
        cdns = next(inst for inst in instruments if inst.ticker == "CDNS")
        assert cdns.name == "Cadence Design Systems"

    async def test_ingest_records_failures_without_stopping(
        self, sqlite_engine: AsyncEngine, stub_providers: Providers
    ) -> None:
        factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        summary = await ingest_tickers(
            ["CDNS", "ZZZZ", "VEEV"],
            stub_providers,
            factory,
            rate_limit_seconds=0.0,
        )
        assert summary.ingested == 2
        assert len(summary.failed) == 1
        failed_ticker, _ = summary.failed[0]
        assert failed_ticker == "ZZZZ"

    async def test_ingest_skip_fresh(
        self, sqlite_engine: AsyncEngine, stub_providers: Providers
    ) -> None:
        factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        # First pass populates the DB.
        await ingest_tickers(["CDNS"], stub_providers, factory, rate_limit_seconds=0.0)
        # Second pass should skip because the snapshot is fresh.
        summary = await ingest_tickers(
            ["CDNS"],
            stub_providers,
            factory,
            rate_limit_seconds=0.0,
            stale_after_days=365,
        )
        assert summary.skipped_fresh == 1
        assert summary.ingested == 0

    async def test_ingest_with_history_persists_multiple_snapshots(
        self, sqlite_engine: AsyncEngine, stub_providers: Providers
    ) -> None:
        factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        await ingest_tickers(
            ["CDNS"],
            stub_providers,
            factory,
            with_history=True,
            rate_limit_seconds=0.0,
        )
        from openbourse.db.repositories import FundamentalsRepository

        async with factory() as session:
            history = await FundamentalsRepository(session).history_for_ticker("CDNS")
        # Stub seeds 8 historical quarters for CDNS.
        assert len(history) >= 8

    async def test_ingest_supports_custom_progress_callback(
        self, sqlite_engine: AsyncEngine, stub_providers: Providers
    ) -> None:
        factory = async_sessionmaker(sqlite_engine, expire_on_commit=False)
        seen: list[tuple[str, int, int]] = []

        def _capture(ticker: str, idx: int, total: int) -> None:
            seen.append((ticker, idx, total))

        await ingest_tickers(
            ["CDNS", "VEEV", "ANET"],
            stub_providers,
            factory,
            rate_limit_seconds=0.0,
            progress=_capture,
        )
        assert [t for t, _, _ in seen] == ["CDNS", "VEEV", "ANET"]
        assert seen[0][2] == 3  # total


class TestSources:
    def test_normalize_ticker_handles_class_share_separators(self) -> None:
        from openbourse.universe.sources import _normalize_ticker

        assert _normalize_ticker("BRK.B") == "BRK-B"
        assert _normalize_ticker("BF.B") == "BF-B"
        assert _normalize_ticker("AAPL") == "AAPL"
        assert _normalize_ticker(" msft ") == "MSFT"

    def test_dedupe_preserving_order_drops_blanks(self) -> None:
        from openbourse.universe.sources import _dedupe_preserving_order

        assert _dedupe_preserving_order(["AAPL", "", "MSFT", "AAPL", "nan", "GOOG"]) == [
            "AAPL",
            "MSFT",
            "GOOG",
        ]

    def test_known_sources_includes_indices(self) -> None:
        from openbourse.universe import KNOWN_SOURCES

        for name in ("sp500", "nasdaq100", "dow30", "russell1000", "russell2000", "russell3000"):
            assert name in KNOWN_SOURCES
        sp500 = KNOWN_SOURCES["sp500"]
        assert sp500.name == "sp500"
        assert "wikipedia" in sp500.url.lower()
        assert callable(sp500.fetch)

        russell2000 = KNOWN_SOURCES["russell2000"]
        assert "ishares" in russell2000.url.lower()
        assert "IWM" in russell2000.url

    def test_fetch_source_unknown_raises(self) -> None:
        from openbourse.universe.sources import fetch_source

        with pytest.raises(KeyError, match="unknown source"):
            fetch_source("does-not-exist")

    def test_fetch_wikipedia_table_picks_first_table_with_matching_column(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fetcher should skip noise tables and find the constituents."""
        import pandas as pd

        from openbourse.universe import sources

        # Looks like a real page: a small noise table first, then the real
        # constituents table second, then more noise.
        noise_top = pd.DataFrame({"Year": list(range(5)), "Change": [0] * 5})
        constituents = pd.DataFrame(
            {
                "Symbol": [f"T{i}" for i in range(30)] + ["BRK.B", "AAPL"],
                "Security": ["x"] * 32,
            }
        )
        noise_bottom = pd.DataFrame({"Footnote": ["a", "b"]})

        class _StubResponse:
            text = "<html />"

            def raise_for_status(self) -> None:
                return None

        monkeypatch.setattr(sources.httpx, "get", lambda *a, **kw: _StubResponse())
        monkeypatch.setattr(
            sources.pd, "read_html", lambda html: [noise_top, constituents, noise_bottom]
        )

        tickers = sources._fetch_wikipedia_table("https://example.com/x", ("Symbol", "Ticker"))
        assert tickers[-2:] == ["BRK-B", "AAPL"]
        assert len(tickers) == 32

    def test_fetch_wikipedia_table_tries_alternate_column_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pages that label the column ``Ticker`` rather than ``Symbol`` still parse."""
        import pandas as pd

        from openbourse.universe import sources

        df = pd.DataFrame({"Ticker": [f"T{i}" for i in range(25)], "Company": ["x"] * 25})

        class _StubResponse:
            text = "<html />"

            def raise_for_status(self) -> None:
                return None

        monkeypatch.setattr(sources.httpx, "get", lambda *a, **kw: _StubResponse())
        monkeypatch.setattr(sources.pd, "read_html", lambda html: [df])

        tickers = sources._fetch_wikipedia_table("https://example.com/x", ("Symbol", "Ticker"))
        assert len(tickers) == 25

    def test_truncate_summary_returns_short_strings_unchanged(self) -> None:
        from openbourse.tui.screens.screener import _truncate_summary

        text = "Apple makes phones."
        assert _truncate_summary(text) == text

    def test_truncate_summary_breaks_at_sentence_boundary_when_possible(self) -> None:
        from openbourse.tui.screens.screener import _truncate_summary

        long = (
            "Newmont engages in the production and exploration of gold. "
            "It also explores for copper, silver, zinc, lead, and "
            "molybdenum properties across multiple continents and operates "
            "mines in North America, South America, Australia, and Africa. "
            "The company was founded in 1916 and is headquartered in Denver."
        )
        out = _truncate_summary(long, max_chars=120)
        assert out.endswith(".")
        assert len(out) <= 120
        assert "exploration of gold" in out

    def test_truncate_summary_falls_back_to_ellipsis_without_sentence(self) -> None:
        from openbourse.tui.screens.screener import _truncate_summary

        # No period — must hard-truncate.
        text = "x" * 500
        out = _truncate_summary(text, max_chars=100)
        assert out.endswith("…")
        assert len(out) <= 101

    def test_fetch_wikipedia_table_raises_when_no_table_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openbourse.universe import sources

        class _StubResponse:
            text = "<html />"

            def raise_for_status(self) -> None:
                return None

        monkeypatch.setattr(sources.httpx, "get", lambda *a, **kw: _StubResponse())
        monkeypatch.setattr(sources.pd, "read_html", lambda html: [])

        with pytest.raises(RuntimeError, match="Wikipedia layout changed"):
            sources._fetch_wikipedia_table("https://example.com/x", ("Symbol",))

    def test_parse_ishares_csv_extracts_equity_tickers(self) -> None:
        from openbourse.universe.sources import _parse_ishares_csv

        # iShares CSVs start with metadata rows, then a holdings table.
        csv = (
            "Fund Holdings as of,Mar 31 2026\n"
            "Inception Date,May 22 2000\n"
            "Shares Outstanding,250000000\n"
            "Stock,-,-\n"
            "\n"
            "Ticker,Name,Sector,Asset Class,Market Value,Weight (%)\n"
            "AAPL,Apple Inc,Technology,Equity,1000000,5.0\n"
            "MSFT,Microsoft Corp,Technology,Equity,950000,4.8\n"
            "BRK.B,Berkshire Hathaway B,Financials,Equity,500000,2.5\n"
            "USD,US Dollar,-,Cash and/or Derivatives,10000,0.1\n"
            "AAPL,duplicate row,Technology,Equity,0,0\n"
        )
        tickers = _parse_ishares_csv(csv, "IWM")
        # Cash filtered out; BRK.B normalised to BRK-B; dupes deduped.
        assert tickers == ["AAPL", "MSFT", "BRK-B"]

    def test_parse_ishares_csv_raises_when_header_missing(self) -> None:
        from openbourse.universe.sources import _parse_ishares_csv

        # No "Ticker," header anywhere — layout has changed.
        csv = "Fund Holdings as of,...\nNAV,10\n"
        with pytest.raises(RuntimeError, match="iShares CSV layout changed"):
            _parse_ishares_csv(csv, "IWM")
