"""Data providers — fundamentals, filings, AI briefs.

Real provider implementations may call external APIs. Each module also ships
a ``Stub*Provider`` returning fixture data so the application runs end-to-end
without API keys.

The :func:`build_providers` factory selects between real and stubbed
implementations based on :class:`openbourse.config.Settings`.
"""

from openbourse.providers.base import (
    BriefProvider,
    Filing,
    FilingsProvider,
    FundamentalsProvider,
    Providers,
)
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider
from openbourse.providers.registry import build_providers

__all__ = [
    "BriefProvider",
    "ClaudeBriefProvider",
    "EdgarFilingsProvider",
    "Filing",
    "FilingsProvider",
    "FmpFundamentalsProvider",
    "FundamentalsProvider",
    "Providers",
    "StubBriefProvider",
    "StubFilingsProvider",
    "StubFundamentalsProvider",
    "build_providers",
]
