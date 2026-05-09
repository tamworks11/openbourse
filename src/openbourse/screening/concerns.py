"""Default list of investment-grade concerns to evaluate per candidate.

These are the kinds of issues experienced fundamental investors actively
look for: hidden dilution, accounting aggressiveness, governance problems,
demand concentration. Claude (or the stub) is asked to evaluate each one
against whatever it knows about the company plus the supplied filings.

Users can override the list by passing their own to ``write_brief``.
A future enhancement will let it be configured via a YAML file.
"""

from __future__ import annotations

DEFAULT_CONCERNS: tuple[str, ...] = (
    "Customer concentration (top customer >10% of revenue)",
    "Stock-based compensation as a meaningful share of revenue",
    "Insider selling or recent management departures",
    "Goodwill or intangible-asset impairment risk",
    "Aggressive non-GAAP accounting or earnings adjustments",
    "Supply-chain or geopolitical concentration risk",
    "Regulatory or antitrust scrutiny",
    "Working capital deterioration (DSO / inventory build-up)",
)
