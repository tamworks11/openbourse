"""Tests for the Item 1A. Risk Factors extractor."""

from __future__ import annotations

from openbourse.screening.risk_factors import extract_risk_factors, html_to_text

# A minimal stand-in for a 10-K. Real filings sprawl across hundreds of
# tags; the extractor only cares about the heading text after stripping.
SAMPLE_10K_HTML = """
<html>
<body>
<p>Table of Contents</p>
<p><b>Item 1A. Risk Factors</b> ........... 12</p>
<p>Item 1B. Unresolved Staff Comments .... 30</p>
<h2>Item 1. Business</h2>
<p>We sell widgets to enterprise customers globally.</p>
<h2>Item 1A. Risk Factors</h2>
<p>The following risks could materially affect our business.</p>
<p>Customer concentration: our top 3 customers represent 38% of revenue.</p>
<p>Stock-based compensation totaled 14% of revenue in fiscal 2025.</p>
<h2>Item 1B. Unresolved Staff Comments</h2>
<p>None.</p>
<h2>Item 2. Properties</h2>
<p>Our headquarters are in San Jose, California.</p>
</body>
</html>
"""


class TestHtmlToText:
    def test_strips_tags(self) -> None:
        assert "<p>" not in html_to_text(SAMPLE_10K_HTML)
        assert "widgets" in html_to_text(SAMPLE_10K_HTML)

    def test_drops_script_blocks(self) -> None:
        text = html_to_text("<html><body><p>Hi</p><script>alert(1)</script></body></html>")
        assert "alert" not in text
        assert "Hi" in text

    def test_empty_input_returns_empty(self) -> None:
        assert html_to_text("") == ""
        assert html_to_text("   ") == ""


class TestExtractRiskFactors:
    def test_returns_only_item_1a_section(self) -> None:
        section = extract_risk_factors(SAMPLE_10K_HTML)
        assert "concentration" in section
        assert "Stock-based compensation" in section
        # Should not include subsequent sections.
        assert "Properties" not in section
        assert "San Jose" not in section
        # Should not include the Item 1 (Business) section.
        assert "widgets" not in section

    def test_skips_table_of_contents_entry(self) -> None:
        # The TOC entry mentions "Item 1A. Risk Factors" but the actual
        # heading is what matters — we should land at the second match.
        section = extract_risk_factors(SAMPLE_10K_HTML)
        assert section.startswith("The following risks")

    def test_falls_back_to_full_text_when_heading_missing(self) -> None:
        text = "no heading here. just some risk-y prose about the business."
        assert extract_risk_factors(text) == text

    def test_handles_pretokenized_text_input(self) -> None:
        text = (
            "Item 1A. Risk Factors\n"
            "Real risk content here.\n"
            "Item 1B. Unresolved Staff Comments\n"
            "None."
        )
        section = extract_risk_factors(text)
        assert "Real risk content" in section
        assert "Unresolved" not in section

    def test_handles_cybersecurity_end_marker(self) -> None:
        # Post-2023 filers sometimes use Item 1C for Cybersecurity.
        text = "Item 1A. Risk Factors\nRisk content.\nItem 1C. Cybersecurity\nCyber stuff."
        section = extract_risk_factors(text)
        assert "Risk content" in section
        assert "Cyber stuff" not in section

    def test_empty_input_returns_empty(self) -> None:
        assert extract_risk_factors("") == ""
