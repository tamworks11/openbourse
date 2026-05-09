"""Yahoo Finance fundamentals provider via the ``yfinance`` library.

Trade-offs vs FMP:

* **Free and unlimited** — no API key, no daily quota. Covers ~150,000
  tickers including ADRs and international listings.
* **No SLA** — yfinance scrapes Yahoo's unofficial endpoints; Yahoo can
  change them without notice and yfinance breaks until the maintainer
  catches up. Acceptable for personal research, not for anything
  commercial.
* **No point-in-time accuracy** — Yahoo applies restatements
  retroactively. Fine for current screening, wrong for backtests.

Implementation notes:

* ``yfinance.Ticker(...).info`` is the single attribute that hits Yahoo;
  it's blocking I/O so we run it in a worker thread via
  :func:`asyncio.to_thread` to keep the event loop free.
* TTM ratios (gross margin, revenue growth, FCF yield) come straight out
  of the ``info`` dict — no manual computation needed for the snapshot.
* History uses the annual statement DataFrames (4-5 years) and computes
  the same four headline ratios per year. Historical market cap is
  estimated as ``close_price * current_shares_outstanding`` because
  Yahoo's per-period shares-outstanding history requires extra calls;
  for stable share counts this is close enough to drive the chart trend.
"""

from __future__ import annotations

import asyncio
import warnings
from datetime import date
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import yfinance as yf  # type: ignore[import-untyped]

from openbourse.domain import FundamentalsSnapshot

HISTORY_LOOKBACK_PAD = 1  # annual period → YoY needs 1 prior year


class YfinanceFundamentalsProvider:
    """Yahoo Finance client. Free, unlimited (in practice), no SLA."""

    def __init__(self, *, history_period: str = "6y", price_interval: str = "1mo") -> None:
        self._history_period = history_period
        self._price_interval = price_interval

    async def fetch(self, ticker: str) -> FundamentalsSnapshot:
        """Pull the current TTM snapshot from ``yfinance.Ticker.info``."""
        ticker = ticker.upper()
        info = await asyncio.to_thread(_get_info, ticker)
        if not info:
            raise KeyError(
                f"Yahoo Finance returned no data for {ticker} — ticker may be "
                f"invalid, delisted, or temporarily blocked"
            )
        return _parse_info(ticker, info)

    async def history(self, ticker: str, *, limit: int = 4) -> list[FundamentalsSnapshot]:
        """Return up to ``limit`` annual snapshots computed from Yahoo statements.

        Yahoo's free annual data goes back ~4-5 years. After dropping the
        oldest year (used as the YoY comparable), the chart shows 3-4 points.
        """
        ticker = ticker.upper()
        bundle = await asyncio.to_thread(
            _fetch_history_bundle, ticker, self._history_period, self._price_interval
        )
        return _parse_annual_history(ticker, bundle, limit=limit)


# --- Blocking I/O helpers (called via asyncio.to_thread) ---------------------


def _get_info(ticker: str) -> dict[str, Any] | None:
    """Run ``yf.Ticker(ticker).info`` and return a dict (or None on failure).

    Yahoo returns a stub dict for unknown tickers; we treat anything missing
    a ``symbol`` *and* ``shortName`` as unknown.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            info = yf.Ticker(ticker).info
        if not info:
            return None
        if "symbol" not in info and "shortName" not in info:
            return None
        return dict(info)
    except Exception:  # yfinance raises a wide variety; treat all as "unknown"
        return None


def _fetch_history_bundle(ticker: str, history_period: str, price_interval: str) -> dict[str, Any]:
    """Pull every statement plus a price history we'll need to estimate market cap."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        t = yf.Ticker(ticker)
        return {
            "income": t.income_stmt,
            "balance": t.balance_sheet,
            "cashflow": t.cashflow,
            "info": t.info,
            "prices": t.history(period=history_period, interval=price_interval),
        }


# --- Pure parsers -------------------------------------------------------------


def _parse_info(ticker: str, info: dict[str, Any]) -> FundamentalsSnapshot:
    """Compose a FundamentalsSnapshot from yfinance's ``info`` dict."""
    market_cap = float(info.get("marketCap") or 0.0)
    price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0) or None

    # yfinance returns ratio fields as decimals: 0.354 means 35.4%.
    gross_margin_pct = float(info.get("grossMargins") or 0.0) * 100
    revenue_growth_pct = float(info.get("revenueGrowth") or 0.0) * 100

    total_debt = float(info.get("totalDebt") or 0.0)
    total_cash = float(info.get("totalCash") or 0.0)
    ebitda = float(info.get("ebitda") or 0.0)
    nd_to_ebitda = ((total_debt - total_cash) / ebitda) if ebitda > 0 else 0.0

    fcf = float(info.get("freeCashflow") or 0.0)
    fcf_yield_pct = (fcf / market_cap * 100) if market_cap > 0 else 0.0

    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=date.today(),
        market_cap_usd=market_cap,
        revenue_growth_pct=revenue_growth_pct,
        gross_margin_pct=gross_margin_pct,
        net_debt_to_ebitda=nd_to_ebitda,
        fcf_yield_pct=fcf_yield_pct,
        price_usd=price,
        revenue_ttm_usd=float(info.get("totalRevenue") or 0.0) or None,
        ebitda_ttm_usd=ebitda or None,
    )


def _parse_annual_history(
    ticker: str, bundle: dict[str, Any], *, limit: int
) -> list[FundamentalsSnapshot]:
    """Compute one snapshot per fiscal year-end from yfinance statement DataFrames."""
    income = bundle.get("income")
    balance = bundle.get("balance")
    cashflow = bundle.get("cashflow")
    info = bundle.get("info") or {}
    prices = bundle.get("prices")

    if income is None or income.empty:
        return []
    if len(income.columns) < HISTORY_LOOKBACK_PAD + 1:
        return []

    shares = float(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0)
    dates = sorted(income.columns)

    snapshots: list[FundamentalsSnapshot] = []
    for i, dt in enumerate(dates):
        if i < HISTORY_LOOKBACK_PAD:
            continue
        prev_dt = dates[i - HISTORY_LOOKBACK_PAD]
        as_of = _to_python_date(dt)

        cur_rev = _cell(income, "Total Revenue", dt)
        prev_rev = _cell(income, "Total Revenue", prev_dt)
        rev_growth = ((cur_rev / prev_rev) - 1) * 100 if prev_rev > 0 else 0.0

        gross_profit = _cell(income, "Gross Profit", dt)
        gross_margin = (gross_profit / cur_rev * 100) if cur_rev > 0 else 0.0

        ebitda = _cell(income, "EBITDA", dt)
        debt = _cell(balance, "Total Debt", dt)
        cash = _cell(balance, "Cash And Cash Equivalents", dt)
        nd_to_ebitda = ((debt - cash) / ebitda) if ebitda > 0 else 0.0

        fcf = _cell(cashflow, "Free Cash Flow", dt)
        # Estimate market cap as historical close * current shares outstanding.
        # Shares actually fluctuate a bit (buybacks, issuance) but for chart
        # trends this is well within the noise floor.
        close_at_dt = _close_near(prices, dt)
        market_cap = (close_at_dt * shares) if (close_at_dt > 0 and shares > 0) else 0.0
        fcf_yield = (fcf / market_cap * 100) if market_cap > 0 else 0.0

        snapshots.append(
            FundamentalsSnapshot(
                ticker=ticker,
                as_of=as_of,
                market_cap_usd=market_cap,
                revenue_growth_pct=rev_growth,
                gross_margin_pct=gross_margin,
                net_debt_to_ebitda=nd_to_ebitda,
                fcf_yield_pct=fcf_yield,
                price_usd=close_at_dt or None,
                revenue_ttm_usd=None,
                ebitda_ttm_usd=ebitda or None,
            )
        )

    if limit and len(snapshots) > limit:
        snapshots = snapshots[-limit:]
    return snapshots


# --- DataFrame helpers --------------------------------------------------------


def _cell(df: Any, row: str, col: Any) -> float:
    """Return ``df[col][row]`` as a float, gracefully handling missing/NaN."""
    if df is None or df.empty:
        return 0.0
    if col not in df.columns or row not in df.index:
        return 0.0
    try:
        val = float(df[col].loc[row])
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(val) else val


def _close_near(prices: Any, target: Any) -> float:
    """Return the ``Close`` price at-or-just-before ``target`` (a Timestamp)."""
    if prices is None or prices.empty or "Close" not in prices.columns:
        return 0.0
    target_ts = pd.Timestamp(target)
    if target_ts.tzinfo is None and prices.index.tzinfo is not None:
        target_ts = target_ts.tz_localize(prices.index.tzinfo)
    available = prices.index[prices.index <= target_ts]
    if len(available) == 0:
        return 0.0
    closest = available[-1]
    try:
        return float(prices["Close"].loc[closest])
    except (TypeError, ValueError, KeyError):
        return 0.0


def _to_python_date(value: Any) -> date:
    """Coerce a pandas Timestamp / numpy datetime / date into a stdlib date."""
    if hasattr(value, "date"):
        result = value.date()
        if isinstance(result, date):
            return result
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return date.today()  # pragma: no cover - defensive
