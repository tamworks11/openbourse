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

from openbourse.domain import (
    FundamentalsSnapshot,
    Instrument,
    ValuationBand,
    ValuationSnapshot,
)

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

        All four endpoints are wrapped in ``_safe_get`` so a 402 on a
        plan-restricted ticker produces a clean ``KeyError`` instead of an
        un-typed httpx stack trace. ``KeyError`` is what
        :func:`openbourse.screening.lookup.lookup_candidate` translates into
        a user-facing :class:`TickerLookupError`.
        """
        ticker = ticker.upper()
        profile, km_ttm, rt_ttm, income = await asyncio.gather(
            self._safe_get("/profile", symbol=ticker),
            self._safe_get("/key-metrics-ttm", symbol=ticker),
            self._safe_get("/ratios-ttm", symbol=ticker),
            self._safe_get(
                "/income-statement",
                symbol=ticker,
                period="annual",
                limit=2,
            ),
        )

        # Empty profile means the ticker is either unknown or gated behind a
        # higher FMP tier — either way we can't show useful fundamentals.
        if not (isinstance(profile, list) and profile):
            raise KeyError(
                f"FMP returned no profile for {ticker} — ticker may be invalid "
                f"or restricted on your FMP plan tier"
            )

        # Profile alone gives us market cap and identity, but the screen needs
        # at least one ratio source. If both TTM endpoints came back empty,
        # surface a tier-specific message rather than a snapshot full of zeros.
        km_empty = not (isinstance(km_ttm, list) and km_ttm)
        rt_empty = not (isinstance(rt_ttm, list) and rt_ttm)
        if km_empty and rt_empty:
            raise KeyError(
                f"FMP profile available for {ticker} but TTM ratios are "
                f"restricted on your FMP plan tier (got 402 on both "
                f"/key-metrics-ttm and /ratios-ttm)"
            )

        return _parse_current_fundamentals(ticker, profile, km_ttm, rt_ttm, income)

    async def price_history(
        self, ticker: str, *, period: str = "3y", interval: str = "1d"
    ) -> list[tuple[date, float]]:
        """Pull EOD prices via ``/historical-price-eod/full``.

        Translates yfinance-style ``period`` (``3y``) into the ``from``/``to``
        date pair FMP expects. Returns an empty list on plan-tier 402s
        rather than raising — keeps the brief screen rendering even when
        prices aren't available.
        """
        from datetime import timedelta

        ticker = ticker.upper()
        days = _period_to_days(period)
        end = date.today()
        start = end - timedelta(days=days)
        payload = await self._safe_get(
            "/historical-price-eod/full",
            symbol=ticker,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(payload, list):
            return []
        return _parse_fmp_prices(payload)

    async def metadata(self, ticker: str) -> Instrument:
        """Pull identity metadata + business description from FMP's ``/profile``."""
        ticker = ticker.upper()
        profile = await self._safe_get("/profile", symbol=ticker)
        if not (isinstance(profile, list) and profile):
            raise KeyError(f"FMP returned no profile for {ticker}")
        row = profile[0]
        return Instrument(
            ticker=ticker,
            name=str(row.get("companyName") or ticker),
            sector=row.get("sector"),
            exchange=row.get("exchange"),
            cik=row.get("cik"),
            business_summary=row.get("description"),
        )

    async def valuation(self, ticker: str) -> ValuationSnapshot:
        """Pull current + historical valuation multiples from FMP.

        Current values come from ``/key-metrics-ttm`` and ``/ratios-ttm``
        (both free-tier). Historical bands come from ``/historical-key-metrics``
        which is paid; on free tier it 402s and we return current-only
        bands. The brief screen renders gracefully either way.
        """
        ticker = ticker.upper()
        km_ttm, hist = await asyncio.gather(
            self._safe_get("/key-metrics-ttm", symbol=ticker),
            self._safe_get("/historical-key-metrics", symbol=ticker, period="annual", limit=5),
        )
        return _parse_fmp_valuation(ticker, km_ttm, hist)

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


def _period_to_days(period: str) -> int:
    """Convert a yfinance-style period string (``3y``, ``5y``) to a day count."""
    period = period.strip().lower()
    if period.endswith("y"):
        return int(period[:-1] or "1") * 365
    if period.endswith("mo"):
        return int(period[:-2] or "1") * 30
    if period.endswith("d"):
        return int(period[:-1] or "1")
    return 365 * 3  # sensible default for unknown formats


def _parse_fmp_prices(payload: Any) -> list[tuple[date, float]]:
    """Project FMP's price rows into ``(date, close)`` tuples ascending by date."""
    out: list[tuple[date, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        date_str = row.get("date")
        close = row.get("close") or row.get("adjClose")
        if not date_str or close is None:
            continue
        try:
            out.append((date.fromisoformat(str(date_str)[:10]), float(close)))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda r: r[0])
    return out


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

    # Trailing P/E straight from key-metrics-ttm; drop non-positive values.
    pe_ttm = float(km_row.get("peRatioTTM") or 0.0)

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
        pe_ratio_ttm=pe_ttm if pe_ttm > 0 else None,
        # FMP's key-metrics-ttm exposes ROIC as a decimal (e.g. 0.18 for 18%).
        roic_pct=float(km_row.get("roicTTM") or 0.0) * 100,
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

        # ROIC = NOPAT / Invested Capital. NOPAT ~= operatingIncome * (1 - tax).
        # Invested Capital ~= totalDebt + totalEquity - cash.
        op_income = _f(row.get("operatingIncome"))
        tax_provision = _f(row.get("incomeTaxExpense"))
        pretax = _f(row.get("incomeBeforeTax"))
        equity = _f(bal.get("totalStockholdersEquity"))
        cash = _f(bal.get("cashAndCashEquivalents"))
        debt = _f(bal.get("totalDebt"))
        tax_rate = (tax_provision / pretax) if pretax > 0 else 0.21
        nopat = op_income * (1.0 - tax_rate) if op_income > 0 else 0.0
        invested_capital = max(0.0, debt + equity - cash)
        roic_pct = (nopat / invested_capital * 100) if invested_capital > 0 else 0.0

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
                roic_pct=roic_pct,
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
        metadata_fixture: dict[str, Instrument] | None = None,
    ) -> None:
        self._fixture = fixture or _load_default_fixture()
        self._history_fixture = history_fixture or _load_default_history_fixture()
        self._metadata_fixture = metadata_fixture or _load_default_metadata_fixture()

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Return the fixture snapshot for ``ticker`` or raise :class:`KeyError`."""
        ticker = ticker.upper()
        try:
            return self._fixture[ticker]
        except KeyError as exc:
            raise KeyError(f"unknown ticker: {ticker}") from exc

    async def history(self, ticker: str, *, limit: int = 8) -> list[FundamentalsSnapshot]:
        """Return up to ``limit`` historical snapshots from the seed fixture."""
        snaps = self._history_fixture.get(ticker.upper(), [])
        return snaps[-limit:] if limit else list(snaps)

    async def metadata(self, ticker: str) -> Instrument:
        """Return seeded instrument metadata or raise :class:`KeyError`."""
        ticker = ticker.upper()
        try:
            return self._metadata_fixture[ticker]
        except KeyError as exc:
            raise KeyError(f"unknown ticker: {ticker}") from exc

    async def valuation(self, ticker: str) -> ValuationSnapshot:
        """Return synthetic but plausible valuation bands for ``ticker``.

        Computes current multiples from the latest fixture snapshot and
        derives synthetic ±25% historical bands so the panel renders
        with a realistic-looking range in offline mode and screenshots.
        Real users get computed bands via the yfinance/FMP backends.
        """
        ticker = ticker.upper()
        snaps = self._history_fixture.get(ticker, [])
        if not snaps:
            return ValuationSnapshot(ticker=ticker, as_of=date.today())
        return _compute_stub_valuation(ticker, snaps)

    async def price_history(
        self, ticker: str, *, period: str = "3y", interval: str = "1d"
    ) -> list[tuple[date, float]]:
        """Return synthetic prices derived from the seeded snapshot history.

        Real daily data isn't bundled — it would balloon the seed file
        many-fold. Only the latest snapshot per ticker carries an explicit
        ``price_usd``, so we back-fill historical prices by multiplying
        each snapshot's market cap by the latest (price ÷ market cap)
        ratio. This assumes share count is roughly constant across the
        seed window, which is fine for the curated stub tickers and gives
        the chart widget realistic-looking shape for screenshots and
        offline demos. Real users get real daily data via yfinance/FMP.
        """
        snaps = self._history_fixture.get(ticker.upper(), [])
        if not snaps:
            return []

        # Anchor the synthetic series on the most recent snapshot that has
        # both a price and a positive market cap.
        anchor_price: float | None = None
        anchor_mcap: float = 0.0
        for s in reversed(snaps):
            if s.price_usd is not None and s.market_cap_usd > 0:
                anchor_price = s.price_usd
                anchor_mcap = s.market_cap_usd
                break
        if anchor_price is None:
            return [(s.as_of, s.price_usd) for s in snaps if s.price_usd is not None]
        ratio = anchor_price / anchor_mcap

        out: list[tuple[date, float]] = []
        for s in snaps:
            if s.price_usd is not None:
                out.append((s.as_of, s.price_usd))
            elif s.market_cap_usd > 0:
                out.append((s.as_of, s.market_cap_usd * ratio))
        return out

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
            # ROIC populated below once the per-ticker series is sorted —
            # the synthesizer uses position-in-history to add upward drift
            # for quality compounders, which can't happen until we know
            # the position.
            roic_pct=0.0,
        )
        history.setdefault(snap.ticker, []).append(snap)
    return _populate_synthetic_roic(history)


def _load_default_metadata_fixture() -> dict[str, Instrument]:
    """Per-ticker instrument metadata from the bundled seed."""
    raw = json.loads(resources.files("openbourse.data").joinpath("seed.json").read_text())
    out: dict[str, Instrument] = {}
    for entry in raw["instruments"]:
        out[entry["ticker"]] = Instrument(
            ticker=entry["ticker"],
            name=entry["name"],
            sector=entry.get("sector"),
            exchange=entry.get("exchange"),
            cik=entry.get("cik"),
        )
    return out


def _parse_fmp_valuation(ticker: str, km_ttm: Any, hist: Any) -> ValuationSnapshot:
    """Build a :class:`ValuationSnapshot` from FMP's TTM + historical endpoints.

    Current values are pulled from the first row of ``/key-metrics-ttm``;
    historical bands from ``/historical-key-metrics`` ascending by date.
    Each metric is independent — if FMP's free tier has hidden the
    historical endpoint behind a 402, current-only bands still render.
    """
    km_row = km_ttm[0] if isinstance(km_ttm, list) and km_ttm else {}
    current_pe = _f(km_row.get("peRatioTTM")) or None
    current_ev_ebitda = _f(km_row.get("enterpriseValueOverEBITDATTM")) or None
    current_ev_rev = _f(km_row.get("evToSalesTTM")) or None
    current_pfcf = _f(km_row.get("priceToFreeCashFlowsRatioTTM")) or None

    pe_hist: list[tuple[date, float]] = []
    ev_ebitda_hist: list[tuple[date, float]] = []
    ev_rev_hist: list[tuple[date, float]] = []
    pfcf_hist: list[tuple[date, float]] = []

    if isinstance(hist, list):
        for row in sorted(hist, key=lambda r: str(r.get("date", ""))):
            if not isinstance(row, dict):
                continue
            row_date_str = row.get("date")
            if not isinstance(row_date_str, str):
                continue
            try:
                row_date = date.fromisoformat(row_date_str[:10])
            except (TypeError, ValueError):
                continue

            pe = _f(row.get("peRatio")) or 0.0
            if pe > 0:
                pe_hist.append((row_date, pe))
            ev_ebitda = _f(row.get("enterpriseValueOverEBITDA")) or 0.0
            if ev_ebitda > 0:
                ev_ebitda_hist.append((row_date, ev_ebitda))
            ev_rev = _f(row.get("evToSales")) or 0.0
            if ev_rev > 0:
                ev_rev_hist.append((row_date, ev_rev))
            pfcf = _f(row.get("priceToFreeCashFlowsRatio")) or 0.0
            if pfcf > 0:
                pfcf_hist.append((row_date, pfcf))

    bands = (
        ValuationBand(label="P/E", current=current_pe, history=tuple(pe_hist)),
        ValuationBand(label="EV/EBITDA", current=current_ev_ebitda, history=tuple(ev_ebitda_hist)),
        ValuationBand(label="EV/Revenue", current=current_ev_rev, history=tuple(ev_rev_hist)),
        ValuationBand(label="P/FCF", current=current_pfcf, history=tuple(pfcf_hist)),
    )
    return ValuationSnapshot(ticker=ticker, as_of=date.today(), bands=bands)


def _compute_stub_valuation(ticker: str, snaps: list[FundamentalsSnapshot]) -> ValuationSnapshot:
    """Build a synthetic but plausible valuation snapshot for the stub.

    Uses the latest snapshot's market cap, FCF yield, and revenue/EBITDA
    to derive current multiples, then synthesises ±25% historical bands
    around each so the panel renders with a realistic-looking range in
    offline mode and screenshots.
    """
    latest = snaps[-1]
    bands: list[ValuationBand] = []

    # P/E doesn't have a clean derivation from the snapshot fields we
    # carry (no net income), so we approximate as 1 / FCF yield * a
    # plausible "FCF coverage" factor. Good enough for offline UX.
    pe_current: float | None = None
    if latest.fcf_yield_pct > 0:
        pe_current = 100.0 / latest.fcf_yield_pct * 1.2
    bands.append(_synthetic_band("P/E", pe_current, snaps, percent_window=0.25))

    ev_to_ebitda_current: float | None = None
    if latest.ebitda_ttm_usd and latest.ebitda_ttm_usd > 0:
        net_debt = latest.net_debt_to_ebitda * latest.ebitda_ttm_usd
        ev = latest.market_cap_usd + net_debt
        ev_to_ebitda_current = ev / latest.ebitda_ttm_usd
    bands.append(_synthetic_band("EV/EBITDA", ev_to_ebitda_current, snaps, percent_window=0.30))

    ev_to_rev_current: float | None = None
    if latest.revenue_ttm_usd and latest.revenue_ttm_usd > 0:
        net_debt = latest.net_debt_to_ebitda * (latest.ebitda_ttm_usd or 0)
        ev = latest.market_cap_usd + net_debt
        ev_to_rev_current = ev / latest.revenue_ttm_usd
    bands.append(_synthetic_band("EV/Revenue", ev_to_rev_current, snaps, percent_window=0.30))

    pfcf_current: float | None = None
    if latest.fcf_yield_pct > 0:
        pfcf_current = 100.0 / latest.fcf_yield_pct
    bands.append(_synthetic_band("P/FCF", pfcf_current, snaps, percent_window=0.30))

    return ValuationSnapshot(ticker=ticker, as_of=latest.as_of, bands=tuple(bands))


def _synthetic_band(
    label: str,
    current: float | None,
    snaps: list[FundamentalsSnapshot],
    *,
    percent_window: float,
) -> ValuationBand:
    """Build a band whose history oscillates ±``percent_window`` around current.

    Each historical point is anchored to a snapshot date, with the value
    sinusoidally varied so the resulting band has a realistic high/low/median
    spread without needing per-ticker fundamentals back-calculation.
    """
    if current is None or len(snaps) < 2:
        return ValuationBand(label=label, current=current)
    import math

    history: list[tuple[date, float]] = []
    for i, snap in enumerate(snaps):
        # Phase shifts each ticker's wave so different metrics aren't lockstep.
        phase = (hash(label) + i) % 7
        offset = math.sin((i + phase) * math.pi / 3) * percent_window
        history.append((snap.as_of, current * (1 + offset)))
    return ValuationBand(label=label, current=current, history=tuple(history))


def _populate_synthetic_roic(
    history: dict[str, list[FundamentalsSnapshot]],
) -> dict[str, list[FundamentalsSnapshot]]:
    """Sort each ticker's history and overwrite ``roic_pct`` with the year-aware synthesizer.

    Returns a fresh dict — the snapshots are frozen, so we use
    :func:`dataclasses.replace` to swap in the computed ROIC. Idempotent:
    calling this on a result of itself produces the same output.
    """
    from dataclasses import replace

    out: dict[str, list[FundamentalsSnapshot]] = {}
    for ticker, snaps in history.items():
        sorted_snaps = sorted(snaps, key=lambda s: s.as_of)
        out[ticker] = [
            replace(
                s,
                roic_pct=_synthetic_roic(s.gross_margin_pct, s.fcf_yield_pct, year_offset=i),
                # Keep a real P/E if one is present; otherwise synthesize.
                pe_ratio_ttm=s.pe_ratio_ttm or _synthetic_pe(s.gross_margin_pct),
            )
            for i, s in enumerate(sorted_snaps)
        ]
    return out


def _synthetic_pe(gross_margin_pct: float) -> float:
    """Derive a plausible trailing P/E for offline fixtures.

    Scales with gross margin so high-margin compounders carry richer
    multiples than low-margin names. Purely cosmetic — keeps the offline
    detail pane and screenshots from showing an em-dash for P/E.
    """
    return round(12.0 + gross_margin_pct * 0.45, 1)


def _synthetic_roic(
    gross_margin_pct: float,
    fcf_yield_pct: float,
    *,
    year_offset: int = 0,
) -> float:
    """Synthesise a plausible ROIC value for the bundled stub fixtures.

    Real ROIC is computed from operating income and invested capital;
    the seed file doesn't carry those, but gross margin and FCF yield
    correlate enough with capital efficiency to produce realistic-
    looking offline screenshots. Rough heuristic:

    * Quality compounders (high margin, healthy FCF) read ~25-40% ROIC.
    * Mediocre businesses (10-30% margin, weak FCF) read ~5-15%.
    * Capital-light cyclicals can register near-zero.

    ``year_offset`` is the snapshot's position in the ticker's sorted
    history (0 = oldest). Each step adds drift proportional to the
    quality signal — high-margin businesses see ROIC compound upward
    year over year, low-margin ones drift sideways or down. Defaults
    to 0 so callers that don't have ordering can still use the helper
    for a single static value.
    """
    # Bounded gross-margin contribution: caps at 50% of margin (so 80%
    # gross margin → ~40 ROIC) and floors at zero.
    margin_part = max(0.0, gross_margin_pct) * 0.5
    # FCF yield as a kicker: 5% FCF → +5 to ROIC.
    fcf_part = max(0.0, fcf_yield_pct)
    base = margin_part * 0.6 + fcf_part * 1.0

    # Year-over-year drift weighted by margin quality. A 90% gross margin
    # produces +1.2pp ROIC drift per year; a 10% gross margin produces
    # roughly flat. Negative for sub-30% margin businesses (margin pressure
    # eats invested-capital efficiency over time).
    quality = (gross_margin_pct - 30.0) / 100.0
    drift = year_offset * quality * 2.0
    return min(60.0, max(0.0, base + drift))
