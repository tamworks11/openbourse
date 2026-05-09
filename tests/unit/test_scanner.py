"""Tests for the concern scanner — stub behaviour and parser/validator."""

from __future__ import annotations

from openbourse.providers.scanner import (
    StubConcernScanner,
    _build_findings,
    _normalize_whitespace,
    _parse_scan_json,
)


class TestStubConcernScanner:
    async def test_returns_unknown_for_every_concern(self) -> None:
        scanner = StubConcernScanner()
        findings = await scanner.scan(
            ticker="X", filing_text="anything", concerns=["Concern A", "Concern B"]
        )
        assert [f.concern for f in findings] == ["Concern A", "Concern B"]
        assert all(f.status == "unknown" for f in findings)

    async def test_empty_concern_list_returns_empty(self) -> None:
        scanner = StubConcernScanner()
        assert await scanner.scan(ticker="X", filing_text="", concerns=[]) == []


class TestParseScanJson:
    def test_strips_markdown_fences(self) -> None:
        assert _parse_scan_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_handles_preamble(self) -> None:
        assert _parse_scan_json('Here is the result: {"a": 1}') == {"a": 1}

    def test_returns_empty_on_invalid(self) -> None:
        assert _parse_scan_json("not json") == {}


class TestBuildFindings:
    def test_validates_quote_against_filing(self) -> None:
        filing = "Our top 3 customers represent 38% of revenue in fiscal 2025."
        parsed = {
            "Customer concentration": {
                "status": "flagged",
                "quote": "top 3 customers represent 38% of revenue",
            },
        }
        findings = _build_findings(
            parsed, ["Customer concentration"], filing_text=filing
        )
        assert findings[0].status == "flagged"
        # Quote was a real substring; should be preserved.
        assert "38%" in findings[0].note

    def test_drops_fabricated_quote(self) -> None:
        filing = "Real text in the filing."
        parsed = {
            "Concern": {
                "status": "flagged",
                "quote": "This text was never in the filing.",
            },
        }
        findings = _build_findings(parsed, ["Concern"], filing_text=filing)
        # Status preserved, but the fabricated note is blanked.
        assert findings[0].status == "flagged"
        assert findings[0].note == ""

    def test_quote_match_is_whitespace_tolerant(self) -> None:
        filing = "Customer  concentration\nis a material risk.\nWe rely heavily."
        parsed = {
            "Concern": {
                "status": "flagged",
                "quote": "Customer concentration is a material risk.",
            },
        }
        findings = _build_findings(parsed, ["Concern"], filing_text=filing)
        # Filing has double-space + newline, quote is single-spaced; both
        # normalize to the same string so the quote is accepted.
        assert findings[0].note != ""

    def test_missing_concern_defaults_to_unknown(self) -> None:
        findings = _build_findings(
            {}, ["Concern A"], filing_text="any text"
        )
        assert findings[0].status == "unknown"
        assert findings[0].note == ""

    def test_invalid_status_falls_back_to_unknown(self) -> None:
        parsed = {"Concern": {"status": "uncertain", "quote": ""}}
        findings = _build_findings(parsed, ["Concern"], filing_text="any")
        assert findings[0].status == "unknown"


class TestNormalizeWhitespace:
    def test_collapses_runs(self) -> None:
        assert _normalize_whitespace("a   b\n\n  c") == "a b c"

    def test_strips_edges(self) -> None:
        assert _normalize_whitespace("  a b  ") == "a b"
