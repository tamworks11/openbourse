"""Tests for the parser logic inside the real (non-stub) providers."""

from __future__ import annotations

from datetime import date

from openbourse.providers.edgar import _parse_submissions
from openbourse.providers.fmp import _parse_fundamentals


def test_fmp_parser_handles_full_payload() -> None:
    profile = [{"mktCap": 78_200_000_000}]
    metrics = [
        {
            "revenueGrowth": 0.184,
            "grossProfitMarginTTM": 0.891,
            "netDebtToEBITDATTM": 0.2,
            "freeCashFlowYieldTTM": 0.028,
            "revenueTTM": 4_000_000_000,
            "ebitdaTTM": 1_500_000_000,
        }
    ]
    snap = _parse_fundamentals("CDNS", profile, metrics)
    assert snap.ticker == "CDNS"
    assert snap.market_cap_usd == 78_200_000_000
    assert round(snap.revenue_growth_pct, 1) == 18.4
    assert round(snap.gross_margin_pct, 1) == 89.1
    assert round(snap.fcf_yield_pct, 1) == 2.8


def test_fmp_parser_tolerates_missing_payload() -> None:
    snap = _parse_fundamentals("XYZ", [], [])
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
