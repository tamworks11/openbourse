"""Tests for the parser logic inside the real (non-stub) providers."""

from __future__ import annotations

from datetime import date

from openbourse.providers.edgar import _parse_submissions


def test_fmp_current_fundamentals_tolerates_missing_payload() -> None:
    snap = _parse_current_fundamentals("XYZ", [], [], [], [])
    assert snap.ticker == "XYZ"
    assert snap.market_cap_usd == 0.0


def test_edgar_parser_extracts_filings() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K"],
                "filingDate": ["2026-04-22", "2026-03-15"],
                "accessionNumber": ["0000813672-26-000017", "0000813672-26-000016"],
                "primaryDocument": ["cdns-q1.htm", "cdns-8k.htm"],
                "primaryDocDescription": ["Quarterly report", "Material event"],
            }
        }
    }
    filings = _parse_submissions("0000813672", payload, limit=10)
    assert len(filings) == 2
    assert filings[0].form_type == "10-Q"
    assert filings[0].filed_at == date(2026, 4, 22)
    assert "813672" in filings[0].url
    assert filings[0].accession_number == "0000813672-26-000017"


def test_edgar_parser_respects_limit() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["10-Q"] * 5,
                "filingDate": ["2026-04-22"] * 5,
                "accessionNumber": [f"0000813672-26-{i:06d}" for i in range(5)],
                "primaryDocument": ["x.htm"] * 5,
                "primaryDocDescription": ["Quarterly"] * 5,
            }
        }
    }
    assert len(_parse_submissions("0000813672", payload, limit=3)) == 3


def test_edgar_parser_handles_empty_payload() -> None:
    assert _parse_submissions("0000000001", {}, limit=5) == []


# --- FMP historical parser ----------------------------------------------------

from openbourse.providers.fmp import (  # noqa: E402
    _latest_yoy_growth,
    _parse_current_fundamentals,
    _parse_history,
)


def _income(date_str: str, revenue: float, gross: float = 0.0, ebitda: float = 0.0) -> dict:
    return {"date": date_str, "revenue": revenue, "grossProfit": gross, "ebitda": ebitda}


def test_fmp_yoy_growth_quarterly_lookback_four() -> None:
    income = [
        _income("2024-09-30", 1_000_000_000),
        _income("2024-12-31", 1_050_000_000),
        _income("2025-03-31", 1_080_000_000),
        _income("2025-06-30", 1_100_000_000),
        _income("2025-09-30", 1_184_000_000),  # +18.4% YoY vs 2024-Q3
    ]
    assert round(_latest_yoy_growth(income, lookback=4), 1) == 18.4


def test_fmp_yoy_growth_annual_lookback_one() -> None:
    income = [
        _income("2024-12-31", 1_000_000_000),
        _income("2025-12-31", 1_184_000_000),  # +18.4% YoY
    ]
    assert round(_latest_yoy_growth(income, lookback=1), 1) == 18.4


def test_fmp_yoy_growth_returns_zero_with_too_few_rows() -> None:
    assert _latest_yoy_growth([_income("2025-01-01", 100)], lookback=1) == 0.0


def test_fmp_yoy_growth_returns_zero_with_zero_prior_revenue() -> None:
    income = [_income("2024-01-01", 0), _income("2025-01-01", 100)]
    assert _latest_yoy_growth(income, lookback=1) == 0.0


def test_fmp_history_parser_computes_ratios_from_raw_statements() -> None:
    income = [
        _income(f"2025-{m:02d}-01", 1_000_000_000, gross=600_000_000, ebitda=400_000_000)
        for m in (3, 6, 9, 12)
    ] + [
        _income("2026-03-01", 1_200_000_000, gross=750_000_000, ebitda=480_000_000),
    ]
    balance = [
        {"date": "2026-03-01", "totalDebt": 1_000_000_000, "cashAndCashEquivalents": 200_000_000},
    ]
    cashflow = [
        {"date": d, "freeCashFlow": 100_000_000}
        for d in ("2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01", "2026-03-01")
    ]
    enterprise = [
        {
            "date": "2026-03-01",
            "marketCapitalization": 50_000_000_000,
            "stockPrice": 123.45,
        }
    ]

    history = _parse_history("X", income, balance, cashflow, enterprise, limit=8)
    assert len(history) == 1
    snap = history[0]
    # gross_margin = 750M / 1.2B = 62.5%
    assert round(snap.gross_margin_pct, 1) == 62.5
    # rev growth: 1.2B / 1.0B = +20%
    assert round(snap.revenue_growth_pct, 1) == 20.0
    # net debt = 1B - 200M = 800M;
    # TTM EBITDA = sum(quarters i-3..i) = 400M + 400M + 400M + 480M = 1.68B
    # → net_debt / ebitda = 800M / 1.68B = 0.476
    assert round(snap.net_debt_to_ebitda, 2) == 0.48
    # TTM FCF = 4 * 100M = 400M; market cap = 50B → 0.8%
    assert round(snap.fcf_yield_pct, 2) == 0.8
    assert snap.price_usd == 123.45


def test_fmp_history_parser_returns_empty_on_short_payload() -> None:
    # < 5 quarters of income → no YoY comparable available.
    assert _parse_history("X", [], [], [], [], limit=8) == []
    assert _parse_history("X", [_income("2025-01-01", 100)], [], [], [], limit=8) == []


def test_fmp_history_parser_returns_empty_on_error_payload() -> None:
    # FMP returns {"Error Message": ...} on plan-tier rejections.
    assert _parse_history("X", {"Error Message": "denied"}, [], [], [], limit=8) == []


def test_fmp_history_parser_respects_limit() -> None:
    income = [_income(f"2024-{m:02d}-01", 1_000_000_000, ebitda=1) for m in range(1, 13)] + [
        _income(f"2025-{m:02d}-01", 1_100_000_000 * m / 10, ebitda=1) for m in range(1, 13)
    ]
    history = _parse_history("X", income, [], [], [], limit=4)
    assert len(history) <= 4


def test_fmp_current_fundamentals_parser() -> None:
    profile = [
        {
            "marketCap": 627_847_920_000,
            "price": 124.92,
            "symbol": "INTC",
            "companyName": "Intel",
        },
    ]
    km_ttm = [
        {
            "marketCap": 627_847_920_000,
            "freeCashFlowYieldTTM": -0.005,
            "netDebtToEBITDATTM": 2.44,
        }
    ]
    rt_ttm = [{"grossProfitMarginTTM": 0.354}]
    # Annual income statement: two rows, year-over-year.
    income = [
        _income("2024-12-28", 47_000_000_000),
        _income("2025-12-28", 50_385_000_000),  # +7.2% YoY
    ]
    snap = _parse_current_fundamentals("INTC", profile, km_ttm, rt_ttm, income)
    assert snap.ticker == "INTC"
    assert snap.market_cap_usd == 627_847_920_000
    assert round(snap.gross_margin_pct, 1) == 35.4
    assert round(snap.net_debt_to_ebitda, 2) == 2.44
    assert round(snap.fcf_yield_pct, 2) == -0.5
    assert round(snap.revenue_growth_pct, 1) == 7.2
    assert snap.price_usd == 124.92
