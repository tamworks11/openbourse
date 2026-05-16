"""Quote providers — latest price for a list of tickers, refreshed on a poll.

Three implementations:

* :class:`StubQuoteProvider` — synthetic prices keyed off the ticker for
  deterministic offline development and tests.
* :class:`YfinanceQuoteProvider` — uses ``yfinance.Ticker(t).fast_info``
  in parallel via ``asyncio.gather``. There's no batch endpoint upstream,
  so latency scales with the number of tickers.
* :class:`FmpQuoteProvider` — uses FMP's ``/stable/quote?symbols=A,B,C``
  comma-separated multi-symbol endpoint. One HTTP call regardless of
  ticker count.

All three implement :class:`~openbourse.providers.base.QuoteProvider` and
return a sparse dict — tickers without a quote are simply omitted, which
the caller treats as "no fresh data; keep the prior value".
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import UTC, datetime
from typing import Any

import httpx

from openbourse.domain import Quote


def _opt_float(value: Any) -> float | None:
    """Coerce ``value`` to a finite float, or ``None`` for missing/NaN/garbage."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _opt_int(value: Any) -> int | None:
    """Coerce ``value`` to an int, or ``None`` for missing/garbage values."""
    result = _opt_float(value)
    return int(result) if result is not None else None


class StubQuoteProvider:
    """Deterministic synthetic prices and volumes for offline development."""

    async def fetch_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        """Return one :class:`Quote` per ticker, deterministic per ticker."""
        now = datetime.now(UTC)
        return {
            t: Quote(
                ticker=t,
                price_usd=_synthetic_price(t),
                fetched_at=now,
                volume=_synthetic_volume(t),
                previous_close=_synthetic_previous_close(t),
                avg_volume_3m=_synthetic_avg_volume_3m(t),
                year_change_pct=_synthetic_year_change_pct(t),
            )
            for t in tickers
        }


def _hash_int(ticker: str, salt: str) -> int:
    """Derive a stable 32-bit-ish int from ``ticker`` and a ``salt`` label."""
    digest = hashlib.sha256(f"{ticker}-{salt}".encode()).hexdigest()
    return int(digest[:8], 16)


def _synthetic_price(ticker: str) -> float:
    """Hash the ticker to a stable, plausible-looking price in [10, 510]."""
    digest = hashlib.sha256(ticker.encode("utf-8")).hexdigest()
    return 10.0 + (int(digest[:8], 16) % 50_000) / 100.0


def _synthetic_volume(ticker: str) -> int:
    """Hash the ticker to a stable, plausible daily share volume [100K, ~50M]."""
    return 100_000 + _hash_int(ticker, "volume") % 50_000_000


def _synthetic_avg_volume_3m(ticker: str) -> int:
    """Hash the ticker to a stable trailing-3-month average volume [100K, ~60M]."""
    return 100_000 + _hash_int(ticker, "avgvol3m") % 60_000_000


def _synthetic_previous_close(ticker: str) -> float:
    """Derive a prior close near the synthetic price — a stable ±3% daily move."""
    move = (_hash_int(ticker, "prevclose") % 600 - 300) / 10_000.0
    return round(_synthetic_price(ticker) / (1 + move), 2)


def _synthetic_year_change_pct(ticker: str) -> float:
    """Hash the ticker to a stable 52-week change percent in [-50.0, +89.9]."""
    return round((_hash_int(ticker, "yearchg") % 1400 - 500) / 10.0, 1)


class YfinanceQuoteProvider:
    """Pulls per-ticker ``fast_info`` from Yahoo via ``yfinance`` in parallel.

    yfinance has no true batch endpoint; ``fast_info`` is the lightweight
    per-ticker quote payload (price + day range + volume). We dispatch the
    fetches concurrently with ``asyncio.gather``, with a per-call timeout
    so a single hung request can't stall the whole refresh.
    """

    def __init__(self, *, per_request_timeout: float = 5.0) -> None:
        self._per_request_timeout = per_request_timeout

    async def fetch_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        """Fetch each ticker's ``fast_info`` concurrently and project to Quotes."""
        if not tickers:
            return {}
        results = await asyncio.gather(
            *(self._fetch_one(t) for t in tickers),
            return_exceptions=True,
        )
        out: dict[str, Quote] = {}
        for ticker, result in zip(tickers, results, strict=False):
            if isinstance(result, Quote):
                out[ticker] = result
        return out

    async def _fetch_one(self, ticker: str) -> Quote | None:
        """Wrap a single ``fast_info`` call in a thread + timeout."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_yfinance_quote, ticker),
                timeout=self._per_request_timeout,
            )
        except (TimeoutError, OSError, ValueError, KeyError):
            return None


def _yfinance_quote(ticker: str) -> Quote | None:
    """Run a single ``fast_info`` call inside an asyncio worker thread."""
    import warnings

    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        info = yf.Ticker(ticker).fast_info
    price = float(getattr(info, "last_price", 0.0) or 0.0)
    if price <= 0:
        return None
    # Yahoo's year_change is a fraction (0.184 → +18.4%); express as a percent.
    year_change = _opt_float(getattr(info, "year_change", None))
    return Quote(
        ticker=ticker,
        price_usd=price,
        fetched_at=datetime.now(UTC),
        volume=_opt_int(getattr(info, "last_volume", None)),
        previous_close=_opt_float(getattr(info, "previous_close", None)),
        avg_volume_3m=_opt_int(getattr(info, "three_month_average_volume", None)),
        year_change_pct=year_change * 100 if year_change is not None else None,
    )


class FmpQuoteProvider:
    """Pulls all quotes in one call via FMP's batched ``/quote`` endpoint."""

    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        if not api_key:
            raise ValueError("FMP API key is required")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def fetch_quotes(self, tickers: list[str]) -> dict[str, Quote]:
        """Single HTTP call regardless of ticker count; sparse dict on success."""
        if not tickers:
            return {}
        symbols = ",".join(tickers)
        try:
            response = await self._client.get(
                f"{self.BASE_URL}/quote",
                params={"symbol": symbols, "apikey": self._api_key},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return {}
        return _parse_fmp_quotes(payload)

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider owns it."""
        if self._owns_client:
            await self._client.aclose()


def _parse_fmp_quotes(payload: Any) -> dict[str, Quote]:
    """Project FMP's ``/quote`` array into a ticker→Quote dict.

    FMP returns a list of ``{"symbol", "price", "volume", "previousClose",
    "avgVolume", ...}`` rows. Rows missing a positive price are dropped —
    caller treats as "no fresh data" rather than persisting a zero. The
    ``/quote`` endpoint exposes no 52-week change, so ``year_change_pct``
    is left ``None`` for FMP.
    """
    if not isinstance(payload, list):
        return {}
    now = datetime.now(UTC)
    out: dict[str, Quote] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            continue
        price = _opt_float(row.get("price"))
        if price is None or price <= 0:
            continue
        out[symbol] = Quote(
            ticker=symbol,
            price_usd=price,
            fetched_at=now,
            volume=_opt_int(row.get("volume")),
            previous_close=_opt_float(row.get("previousClose")),
            avg_volume_3m=_opt_int(row.get("avgVolume")),
            year_change_pct=None,
        )
    return out
