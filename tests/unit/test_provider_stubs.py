"""Tests for the stubbed provider implementations."""

from __future__ import annotations

import pytest

from openbourse.domain import FundamentalsSnapshot, Instrument
from openbourse.providers.claude import StubBriefProvider
from openbourse.providers.edgar import StubFilingsProvider
from openbourse.providers.fmp import StubFundamentalsProvider


class TestStubFundamentalsProvider:
    async def test_known_ticker_returns_snapshot(self) -> None:
        provider = StubFundamentalsProvider()
        snap = await provider.fetch("CDNS")
        assert snap.ticker == "CDNS"
        assert snap.market_cap_usd > 0

    async def test_unknown_ticker_raises(self) -> None:
        provider = StubFundamentalsProvider()
        with pytest.raises(KeyError):
            await provider.fetch("ZZZZ")

    async def test_lookup_is_case_insensitive(self) -> None:
        provider = StubFundamentalsProvider()
        upper = await provider.fetch("CDNS")
        lower = await provider.fetch("cdns")
        assert upper == lower

    def test_tickers_property_lists_fixture(self) -> None:
        provider = StubFundamentalsProvider()
        assert "CDNS" in provider.tickers
        assert "VEEV" in provider.tickers

    async def test_history_returns_quarterly_series(self) -> None:
        provider = StubFundamentalsProvider()
        history = await provider.history("CDNS", limit=8)
        assert len(history) >= 1
        # Ascending by date.
        assert all(history[i].as_of <= history[i + 1].as_of for i in range(len(history) - 1))

    async def test_history_respects_limit(self) -> None:
        provider = StubFundamentalsProvider()
        capped = await provider.history("CDNS", limit=3)
        assert len(capped) <= 3

    async def test_history_for_unknown_ticker_is_empty(self) -> None:
        provider = StubFundamentalsProvider()
        assert await provider.history("ZZZZ") == []


class TestStubFilingsProvider:
    async def test_returns_filings_for_known_cik(self) -> None:
        provider = StubFilingsProvider()
        filings = await provider.recent_filings("0000813672", limit=5)
        assert len(filings) >= 1
        assert all(f.form_type for f in filings)

    async def test_unknown_cik_returns_empty(self) -> None:
        provider = StubFilingsProvider()
        filings = await provider.recent_filings("9999999999")
        assert filings == []

    async def test_unpadded_cik_is_normalized(self) -> None:
        provider = StubFilingsProvider()
        a = await provider.recent_filings("813672")
        b = await provider.recent_filings("0000813672")
        assert a == b

    async def test_limit_caps_results(self) -> None:
        provider = StubFilingsProvider()
        filings = await provider.recent_filings("0000813672", limit=1)
        assert len(filings) <= 1


class TestStubBriefProvider:
    async def test_brief_has_three_sections(
        self, sample_instrument: Instrument, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        provider = StubBriefProvider()
        brief = await provider.write_brief(sample_instrument, sample_snapshot)
        assert brief.ticker == sample_instrument.ticker
        assert brief.summary
        assert len(brief.bull) >= 1
        assert len(brief.bear) >= 1
        assert len(brief.risks) >= 1
        assert brief.model.startswith("stub-")

    async def test_brief_includes_filing_when_provided(
        self, sample_instrument: Instrument, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        from datetime import date

        from openbourse.providers.base import Filing

        filings = [
            Filing(
                cik="0000813672",
                form_type="10-K",
                filed_at=date(2026, 2, 1),
                accession_number="x",
                url="https://sec.gov/x",
                title="Annual report",
            )
        ]
        brief = await StubBriefProvider().write_brief(sample_instrument, sample_snapshot, filings)
        # Filing context lands in the risks section (last entry, by design).
        assert any("10-K" in r for r in brief.risks)

    async def test_brief_returns_concern_finding_per_request(
        self, sample_instrument: Instrument, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        custom = ["High SBC", "Customer concentration"]
        brief = await StubBriefProvider().write_brief(
            sample_instrument, sample_snapshot, concerns=custom
        )
        assert [f.concern for f in brief.concerns] == custom
        assert all(f.status == "unknown" for f in brief.concerns)

    async def test_brief_uses_default_concerns_when_omitted(
        self, sample_instrument: Instrument, sample_snapshot: FundamentalsSnapshot
    ) -> None:
        from openbourse.screening.concerns import DEFAULT_CONCERNS

        brief = await StubBriefProvider().write_brief(sample_instrument, sample_snapshot)
        assert tuple(f.concern for f in brief.concerns) == DEFAULT_CONCERNS
