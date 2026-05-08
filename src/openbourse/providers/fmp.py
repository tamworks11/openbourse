"""Financial Modeling Prep (FMP) fundamentals provider.

Targets FMP's modern ``/stable`` API (with ``?symbol=X`` query strings) so
the provider works on the free Starter tier. Historical key-metrics and
ratios are paid endpoints, so we recompute the four headline ratios
client-side from the free statement endpoints:

* gross_margin_pct = grossProfit / revenue (per quarter)
* revenue_growth_pct = YoY (this quarter vs the same quarter four periods ago)
* net_debt_to_ebitda = (totalDebt - cash) / trailing-4-quarter EBITDA
* fcf_yield_pct = trailing-4-quarter freeCashFlow / market cap

The stub returns fixture data loaded from ``src/openbourse/data/seed.json``
so contributors can run the app without an API key.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from importlib import resources
from typing import Any

import httpx

from openbourse.domain import FundamentalsSnapshot

FMP_BASE_URL = "https://financialmodelingprep.com/stable"
# Free-tier FMP caps every statement endpoint at 5 rows total. We default to
# annual data (one period = one year) and request `limit + lookback_pad`
# rows; with annual the pad is 1, so a default ``limit=4`` leaves us at 5
# rows requested — exactly the free-tier ceiling. Paid users can override.
HISTORY_DEFAULT_PERIOD = "annual"
HISTORY_DEFAULT_LIMIT = 4
FMP_FREE_TIER_ROW_CAP = 5
LOOKBACK_PAD_BY_PERIOD = {"annual": 1, "quarter": 4}


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
        """Return the current TTM snapshot via free-tier endpoints.

        Uses ``/profile`` (market cap, identity), ``/key-metrics-ttm``
        (net debt / EBITDA, FCF yield), ``/ratios-ttm`` (gross margin), and
        a small slice of ``/income-statement`` to compute YoY revenue growth
        from the latest period against the same period a year ago.
        """
        ticker = ticker.upper()
        profile, km_ttm, rt_ttm, income = await asyncio.gather(
            self._get("/profile", symbol=ticker),
            self._get("/key-metrics-ttm", symbol=ticker),
            self._get("/ratios-ttm", symbol=ticker),
            self._safe_get(
                "/income-statement",
                symbol=ticker,
                period="annual",
                limit=2,
            ),
        )
        return _parse_current_fundamentals(ticker, profile, km_ttm, rt_ttm, income)

    async def history(
        self,
        ticker: str,
        *,
        limit: int = HISTORY_DEFAULT_LIMIT,
        period: str = HISTORY_DEFAULT_PERIOD,
    ) -> list[FundamentalsSnapshot]:
        """Return ``limit`` snapshots at the given period, computed from raw statements.

        Defaults to ``period="annual"``, ``limit=5`` so the call fits inside
        FMP's free-tier limit of 5 rows per endpoint and the resulting chart
        spans 4 years (5 minus a 1-year YoY lookback).

        Pass ``period="quarter"`` on a paid plan for finer granularity, in
        which case ``limit`` should be at least 5 to leave a 4-quarter
        lookback for YoY/TTM rolls.

        Partial endpoint failures degrade gracefully — on free tier
        ``/enterprise-values`` may 402 even at allowed limits, and the
        affected metric simply reads as zero on the chart instead of
        crashing the whole call.
        """
        ticker = ticker.upper()
        pad = LOOKBACK_PAD_BY_PERIOD.get(period, 4)
        rows = limit + pad
        income, balance, cashflow, enterprise = await asyncio.gather(
            self._safe_get("/income-statement", symbol=ticker, period=period, limit=rows),
            self._safe_get("/balance-sheet-statement", symbol=ticker, period=period, limit=rows),
            self._safe_get("/cash-flow-statement", symbol=ticker, period=period, limit=rows),
            self._safe_get("/enterprise-values", symbol=ticker, period=period, limit=rows),
        )
        return _parse_history(
            ticker, income, balance, cashflow, enterprise, limit=limit, lookback_pad=pad
        )

    async def _safe_get(self, path: str, **extra_params: str | int) -> Any:
        """``_get`` wrapper that returns ``[]`` instead of raising on HTTP errors."""
        try:
            return await self._get(path, **extra_params)
        except httpx.HTTPStatusError:
            return []

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, **extra_params: str | int) -> Any:
        """Issue an authenticated GET, merging ``apikey`` with extra query params."""
        params: dict[str, str | int] = {"apikey": self._api_key}
        params.update(extra_params)
        response = await self._client.get(f"{self._base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()


# --- Parsers -----------------------------------------------------------------


def _parse_current_fundamentals(
    ticker: str,
    profile: Any,
    km_ttm: Any,
    rt_ttm: Any,
    income: Any,
) -> FundamentalsSnapshot:
    """Build the current-snapshot from FMP's TTM endpoints + recent income."""
    profile_row = profile[0] if isinstance(profile, list) and profile else {}
    km_row = km_ttm[0] if isinstance(km_ttm, list) and km_ttm else {}
    rt_row = rt_ttm[0] if isinstance(rt_ttm, list) and rt_ttm else {}

    # Prefer profile.marketCap; fall back to key-metrics-ttm.marketCap.
    market_cap = float(profile_row.get("marketCap") or km_row.get("marketCap") or 0.0)
    price = float(profile_row.get("price") or 0.0) or None

    # fetch() asks for annual income data, so consecutive rows are years apart;
    # lookback=1 yields a true YoY growth figure.
    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=date.today(),
        market_cap_usd=market_cap,
        revenue_growth_pct=_latest_yoy_growth(income, lookback=1),
        gross_margin_pct=float(rt_row.get("grossProfitMarginTTM") or 0.0) * 100,
        net_debt_to_ebitda=float(km_row.get("netDebtToEBITDATTM") or 0.0),
        fcf_yield_pct=float(km_row.get("freeCashFlowYieldTTM") or 0.0) * 100,
        price_usd=price,
        revenue_ttm_usd=None,
        ebitda_ttm_usd=None,
    )


def _parse_history(
    ticker: str,
    income: Any,
    balance: Any,
    cashflow: Any,
    enterprise: Any,
    *,
    limit: int,
    lookback_pad: int = 4,
) -> list[FundamentalsSnapshot]:
    """Compute per-period snapshots from raw statement endpoints.

    Joins all four endpoints by ``date``. Periods without ``lookback_pad``
    prior periods of income data are dropped (no YoY/TTM comparable).
    Returns empty list if ``income`` is malformed or empty.

    For ``lookback_pad=4`` (quarterly), EBITDA and FCF are summed over the
    trailing four quarters to produce a TTM rolling figure. For
    ``lookback_pad=1`` (annual), the period's own value is already
    annualised so no rolling is needed.
    """
    if not isinstance(income, list) or len(income) < lookback_pad + 1:
        return []

    income_rows = sorted(
        (r for r in income if isinstance(r, dict) and "date" in r),
        key=lambda r: r["date"],
    )
    balance_by_date = _index_by_date(balance)
    cashflow_by_date = _index_by_date(cashflow)
    enterprise_by_date = _index_by_date(enterprise)

    snapshots: list[FundamentalsSnapshot] = []
    for i, row in enumerate(income_rows):
        if i < lookback_pad:
            continue
        date_str = row["date"]
        try:
            as_of = date.fromisoformat(date_str)
        except ValueError:  # pragma: no cover - malformed FMP date
            continue

        cur_rev = _f(row.get("revenue"))
        prev_rev = _f(income_rows[i - lookback_pad].get("revenue"))
        rev_growth_pct = ((cur_rev / prev_rev) - 1) * 100 if prev_rev > 0 else 0.0

        gross_profit = _f(row.get("grossProfit"))
        gross_margin_pct = (gross_profit / cur_rev) * 100 if cur_rev > 0 else 0.0

        rolled_ebitda, rolled_fcf = _trailing_aggregates(
            income_rows, cashflow_by_date, i, lookback_pad
        )

        bal = balance_by_date.get(date_str, {})
        net_debt = _f(bal.get("totalDebt")) - _f(bal.get("cashAndCashEquivalents"))
        net_debt_to_ebitda = (net_debt / rolled_ebitda) if rolled_ebitda > 0 else 0.0

        ev_row = enterprise_by_date.get(date_str, {})
        market_cap = _f(ev_row.get("marketCapitalization"))
        fcf_yield_pct = (rolled_fcf / market_cap) * 100 if market_cap > 0 else 0.0
        price = _f(ev_row.get("stockPrice")) or None

        snapshots.append(
            FundamentalsSnapshot(
                ticker=ticker,
                as_of=as_of,
                market_cap_usd=market_cap,
                revenue_growth_pct=rev_growth_pct,
                gross_margin_pct=gross_margin_pct,
                net_debt_to_ebitda=net_debt_to_ebitda,
                fcf_yield_pct=fcf_yield_pct,
                price_usd=price,
                revenue_ttm_usd=None,
                ebitda_ttm_usd=rolled_ebitda or None,
            )
        )

    snapshots.sort(key=lambda s: s.as_of)
    if limit and len(snapshots) > limit:
        snapshots = snapshots[-limit:]
    return snapshots


def _trailing_aggregates(
    income_rows: list[dict[str, Any]],
    cashflow_by_date: dict[str, dict[str, Any]],
    i: int,
    lookback_pad: int,
) -> tuple[float, float]:
    """Return (EBITDA, FCF) summed across the trailing window ending at ``i``.

    For quarterly data (``lookback_pad>=4``) we sum 4 quarters → TTM. For
    annual data (``lookback_pad==1``) the period itself is already annual,
    so we just take its single value.
    """
    window = range(i - 3, i + 1) if lookback_pad >= 4 else range(i, i + 1)
    ebitda = sum(_f(income_rows[j].get("ebitda")) for j in window)
    fcf = sum(
        _f(cashflow_by_date.get(income_rows[j]["date"], {}).get("freeCashFlow")) for j in window
    )
    return ebitda, fcf


def _latest_yoy_growth(income: Any, *, lookback: int = 1) -> float:
    """Return revenue growth of the latest period vs ``lookback`` periods earlier.

    For annual data ``lookback=1`` is YoY. For quarterly data ``lookback=4`` is
    the same-quarter-prior-year YoY. Returns 0.0 if there aren't enough rows
    or the prior revenue is non-positive.
    """
    if not isinstance(income, list) or len(income) < lookback + 1:
        return 0.0
    rows = sorted(
        (r for r in income if isinstance(r, dict) and "date" in r),
        key=lambda r: r["date"],
    )
    if len(rows) < lookback + 1:
        return 0.0
    cur = _f(rows[-1].get("revenue"))
    prev = _f(rows[-(lookback + 1)].get("revenue"))
    return ((cur / prev) - 1) * 100 if prev > 0 else 0.0


def _index_by_date(rows: Any) -> dict[str, dict[str, Any]]:
    """Build a ``{date: row}`` lookup from a list payload, tolerating bad shapes."""
    if not isinstance(rows, list):
        return {}
    return {r["date"]: r for r in rows if isinstance(r, dict) and "date" in r}


def _f(value: Any) -> float:
    """Coerce ``value`` to ``float``, treating None / non-numerics as 0.0."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- Stub provider -----------------------------------------------------------


class StubFundamentalsProvider:
    """Returns fixture fundamentals from the bundled seed dataset.

    Tickers not present in the fixture raise :class:`KeyError` from
    :meth:`fetch`; :meth:`history` returns an empty list to mirror the
    real-provider contract.
    """

    def __init__(
        self,
        fixture: dict[str, FundamentalsSnapshot] | None = None,
        history_fixture: dict[str, list[FundamentalsSnapshot]] | None = None,
    ) -> None:
        self._fixture = fixture or _load_default_fixture()
        self._history_fixture = history_fixture or _load_default_history_fixture()

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Return the fixture snapshot for ``ticker`` or raise :class:`KeyError`."""
        ticker = ticker.upper()
        try:
            return self._fixture[ticker]
        except KeyError as exc:
            raise KeyError(f"No fixture fundamentals for {ticker}") from exc

    async def history(self, ticker: str, *, limit: int = 8) -> list[FundamentalsSnapshot]:
        """Return up to ``limit`` historical snapshots from the seed fixture."""
        snaps = self._history_fixture.get(ticker.upper(), [])
        return snaps[-limit:] if limit else list(snaps)

    @property
    def tickers(self) -> tuple[str, ...]:
        """Tuple of every ticker known to this stub, sorted alphabetically."""
        return tuple(sorted(self._fixture))


def _load_default_fixture() -> dict[str, FundamentalsSnapshot]:
    """Latest snapshot per ticker from the bundled seed."""
    history = _load_default_history_fixture()
    return {ticker: snaps[-1] for ticker, snaps in history.items() if snaps}


def _load_default_history_fixture() -> dict[str, list[FundamentalsSnapshot]]:
    """Full per-ticker history from the bundled seed, ascending by ``as_of``."""
    raw = json.loads(resources.files("openbourse.data").joinpath("seed.json").read_text())
    history: dict[str, list[FundamentalsSnapshot]] = {}
    for entry in raw["fundamentals"]:
        snap = FundamentalsSnapshot(
            ticker=entry["ticker"],
            as_of=date.fromisoformat(entry["as_of"]),
            market_cap_usd=float(entry["market_cap_usd"]),
            revenue_growth_pct=float(entry["revenue_growth_pct"]),
            gross_margin_pct=float(entry["gross_margin_pct"]),
            net_debt_to_ebitda=float(entry["net_debt_to_ebitda"]),
            fcf_yield_pct=float(entry["fcf_yield_pct"]),
            price_usd=entry.get("price_usd"),
            revenue_ttm_usd=entry.get("revenue_ttm_usd"),
            ebitda_ttm_usd=entry.get("ebitda_ttm_usd"),
        )
        history.setdefault(snap.ticker, []).append(snap)
    for snaps in history.values():
        snaps.sort(key=lambda s: s.as_of)
    return history
