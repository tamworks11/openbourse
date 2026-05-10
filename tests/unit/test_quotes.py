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
