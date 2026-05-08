"""Financial Modeling Prep (FMP) fundamentals provider.

The real implementation calls FMP's HTTP API. The stub returns fixture data
loaded from ``src/openbourse/data/seed.json`` so contributors can run the app
without an API key.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from typing import Any

import httpx

from openbourse.domain import FundamentalsSnapshot

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


class FmpFundamentalsProvider:
    """Real FMP client. Network access required."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = FMP_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("FMP API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Fetch profile + TTM key metrics from FMP and merge into one snapshot."""
        import asyncio

        ticker = ticker.upper()
        profile, key_metrics = await asyncio.gather(
            self._get(f"/profile/{ticker}"),
            self._get(f"/key-metrics-ttm/{ticker}"),
        )
        return _parse_fundamentals(ticker, profile, key_metrics)

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str) -> Any:
        """Issue an authenticated GET against the FMP base URL."""
        params = {"apikey": self._api_key}
        response = await self._client.get(f"{self._base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()


def _parse_fundamentals(ticker: str, profile: Any, key_metrics: Any) -> FundamentalsSnapshot:
    profile_row = profile[0] if isinstance(profile, list) and profile else {}
    metrics_row = key_metrics[0] if isinstance(key_metrics, list) and key_metrics else {}
    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=date.today(),
        market_cap_usd=float(profile_row.get("mktCap", 0.0)),
        revenue_growth_pct=float(metrics_row.get("revenueGrowth", 0.0)) * 100,
        gross_margin_pct=float(metrics_row.get("grossProfitMarginTTM", 0.0)) * 100,
        net_debt_to_ebitda=float(metrics_row.get("netDebtToEBITDATTM", 0.0)),
        fcf_yield_pct=float(metrics_row.get("freeCashFlowYieldTTM", 0.0)) * 100,
        revenue_ttm_usd=float(metrics_row.get("revenueTTM") or 0.0) or None,
        ebitda_ttm_usd=float(metrics_row.get("ebitdaTTM") or 0.0) or None,
    )


class StubFundamentalsProvider:
    """Returns fixture fundamentals from the bundled seed dataset.

    Tickers not present in the fixture raise :class:`KeyError`. Tests rely on
    this behaviour to assert that callers handle unknown tickers cleanly.
    """

    def __init__(self, fixture: dict[str, FundamentalsSnapshot] | None = None) -> None:
        self._fixture = fixture or _load_default_fixture()

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Return the fixture snapshot for ``ticker`` or raise :class:`KeyError`."""
        ticker = ticker.upper()
        try:
            return self._fixture[ticker]
        except KeyError as exc:
            raise KeyError(f"No fixture fundamentals for {ticker}") from exc

    @property
    def tickers(self) -> tuple[str, ...]:
        """Tuple of every ticker known to this stub, sorted alphabetically."""
        return tuple(sorted(self._fixture))


def _load_default_fixture() -> dict[str, FundamentalsSnapshot]:
    raw = json.loads(resources.files("openbourse.data").joinpath("seed.json").read_text())
    fixture: dict[str, FundamentalsSnapshot] = {}
    for entry in raw["fundamentals"]:
        snap = FundamentalsSnapshot(
            ticker=entry["ticker"],
            as_of=date.fromisoformat(entry["as_of"]),
            market_cap_usd=float(entry["market_cap_usd"]),
            revenue_growth_pct=float(entry["revenue_growth_pct"]),
            gross_margin_pct=float(entry["gross_margin_pct"]),
            net_debt_to_ebitda=float(entry["net_debt_to_ebitda"]),
            fcf_yield_pct=float(entry["fcf_yield_pct"]),
            revenue_ttm_usd=entry.get("revenue_ttm_usd"),
            ebitda_ttm_usd=entry.get("ebitda_ttm_usd"),
        )
        fixture[snap.ticker] = snap
    return fixture
