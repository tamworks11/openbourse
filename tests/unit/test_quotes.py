"""Tests for the quote provider stack."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from openbourse.providers.quotes import (
    StubQuoteProvider,
    _parse_fmp_quotes,
    _synthetic_price,
)


class TestStubQuoteProvider:
    async def test_returns_one_quote_per_ticker(self) -> None:
        provider = StubQuoteProvider()
        quotes = await provider.fetch_quotes(["AAPL", "MSFT", "CDNS"])
        assert set(quotes.keys()) == {"AAPL", "MSFT", "CDNS"}
        for ticker, quote in quotes.items():
            assert quote.ticker == ticker
            assert quote.price_usd > 0
            assert quote.fetched_at.tzinfo is not None

    async def test_empty_input_returns_empty(self) -> None:
        provider = StubQuoteProvider()
        assert await provider.fetch_quotes([]) == {}

    async def test_includes_a_deterministic_volume(self) -> None:
        provider = StubQuoteProvider()
        first = (await provider.fetch_quotes(["CDNS"]))["CDNS"].volume
        second = (await provider.fetch_quotes(["CDNS"]))["CDNS"].volume
        assert first is not None
        assert first == second
        assert 100_000 <= first <= 100_000 + 50_000_000

    async def test_populates_change_avg_volume_and_year_change(self) -> None:
        quote = (await StubQuoteProvider().fetch_quotes(["CDNS"]))["CDNS"]
        # Every quote-only field is present so the offline detail pane
        # renders real numbers instead of em-dashes.
        assert quote.previous_close is not None
        assert quote.avg_volume_3m is not None
        assert quote.year_change_pct is not None
        # change / change_pct are derived from price + previous_close.
        assert quote.change is not None
        assert quote.change_pct is not None
        assert -50.0 <= quote.year_change_pct <= 90.0

    async def test_price_is_deterministic_per_ticker(self) -> None:
        """Same ticker hits the same hash bucket → same price across calls."""
        provider = StubQuoteProvider()
        first = (await provider.fetch_quotes(["CDNS"]))["CDNS"].price_usd
        second = (await provider.fetch_quotes(["CDNS"]))["CDNS"].price_usd
        assert first == second

    async def test_distinct_tickers_get_distinct_prices(self) -> None:
        provider = StubQuoteProvider()
        quotes = await provider.fetch_quotes(["AAA", "BBB", "CCC"])
        prices = {q.price_usd for q in quotes.values()}
        # Hash collisions are theoretically possible but vanishingly rare
        # at 3 tickers x 50k buckets - the test would only flake on a real
        # collision, which is itself a useful signal.
        assert len(prices) == 3


class TestSyntheticPrice:
    @pytest.mark.parametrize("ticker", ["AAPL", "INTC", "CDNS", "VEEV"])
    def test_price_in_band(self, ticker: str) -> None:
        # Range is [10, 510) by construction.
        price = _synthetic_price(ticker)
        assert 10.0 <= price < 510.0

    def test_stable_across_runs(self) -> None:
        # Hash-based, so it's deterministic — no fixture pin needed.
        assert _synthetic_price("CDNS") == _synthetic_price("CDNS")


class TestParseFmpQuotes:
    def test_extracts_symbol_and_price(self) -> None:
        payload = [
            {"symbol": "AAPL", "price": 175.43, "volume": 12_345_678},
            {"symbol": "MSFT", "price": 412.10, "volume": 9_876_543},
        ]
        quotes = _parse_fmp_quotes(payload)
        assert quotes["AAPL"].price_usd == 175.43
        assert quotes["AAPL"].volume == 12_345_678
        assert quotes["MSFT"].price_usd == 412.10
        # fetched_at populated even when payload doesn't carry one.
        assert isinstance(quotes["AAPL"].fetched_at, datetime)
        assert quotes["AAPL"].fetched_at.tzinfo == UTC

    def test_drops_rows_with_zero_or_missing_price(self) -> None:
        payload = [
            {"symbol": "AAA", "price": 100.0},
            {"symbol": "BBB", "price": 0.0},  # dropped
            {"symbol": "CCC"},  # dropped — no price field
        ]
        quotes = _parse_fmp_quotes(payload)
        assert set(quotes.keys()) == {"AAA"}

    def test_drops_rows_without_symbol(self) -> None:
        payload = [{"price": 100.0}]  # no symbol key
        assert _parse_fmp_quotes(payload) == {}

    def test_returns_empty_for_non_list_payloads(self) -> None:
        # FMP error responses sometimes look like {"error": "..."} —
        # parser must not crash, just yield no quotes.
        assert _parse_fmp_quotes({"error": "bad symbol"}) == {}
        assert _parse_fmp_quotes(None) == {}

    def test_volume_optional(self) -> None:
        payload = [{"symbol": "AAA", "price": 100.0}]  # no volume
        assert _parse_fmp_quotes(payload)["AAA"].volume is None

    def test_garbage_volume_does_not_crash(self) -> None:
        payload = [{"symbol": "AAA", "price": 100.0, "volume": "not-a-number"}]
        assert _parse_fmp_quotes(payload)["AAA"].volume is None

    def test_extracts_previous_close_and_avg_volume(self) -> None:
        payload = [
            {
                "symbol": "AAPL",
                "price": 175.0,
                "previousClose": 170.0,
                "avgVolume": 55_000_000,
            }
        ]
        quote = _parse_fmp_quotes(payload)["AAPL"]
        assert quote.previous_close == 170.0
        assert quote.avg_volume_3m == 55_000_000
        # FMP's /quote endpoint carries no 52-week change.
        assert quote.year_change_pct is None

    def test_change_fields_default_to_none_when_absent(self) -> None:
        quote = _parse_fmp_quotes([{"symbol": "AAA", "price": 100.0}])["AAA"]
        assert quote.previous_close is None
        assert quote.avg_volume_3m is None
        assert quote.change is None
        assert quote.change_pct is None


class TestQuoteChangeProperties:
    def test_change_and_change_pct_computed_from_previous_close(self) -> None:
        quote = _parse_fmp_quotes([{"symbol": "AAA", "price": 102.0, "previousClose": 100.0}])[
            "AAA"
        ]
        assert quote.change == pytest.approx(2.0)
        assert quote.change_pct == pytest.approx(2.0)

    def test_negative_change(self) -> None:
        quote = _parse_fmp_quotes([{"symbol": "AAA", "price": 95.0, "previousClose": 100.0}])["AAA"]
        assert quote.change == pytest.approx(-5.0)
        assert quote.change_pct == pytest.approx(-5.0)

    def test_change_pct_is_none_when_previous_close_is_zero(self) -> None:
        # A zero baseline can't yield a percentage — guard against /0.
        quote = _parse_fmp_quotes([{"symbol": "AAA", "price": 95.0, "previousClose": 0.0}])["AAA"]
        assert quote.change_pct is None
