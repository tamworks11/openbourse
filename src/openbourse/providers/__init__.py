"""Data providers — fundamentals, filings, AI briefs.

Real provider implementations may call external APIs. Each module also ships
a ``Stub*Provider`` returning fixture data so the application runs end-to-end
without API keys.

The :func:`build_providers` factory selects between real and stubbed
implementations based on :class:`openbourse.config.Settings`.
"""

from openbourse.providers.base import (
    BriefProvider,
    ConcernScanner,
    Filing,
    FilingsProvider,
    FundamentalsProvider,
    Providers,
    QuoteProvider,
)
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider
from openbourse.providers.quotes import (
    FmpQuoteProvider,
    StubQuoteProvider,
    YfinanceQuoteProvider,
)
from openbourse.providers.registry import build_providers
from openbourse.providers.scanner import ClaudeConcernScanner, StubConcernScanner
from openbourse.providers.yfinance import YfinanceFundamentalsProvider

__all__ = [
    "BriefProvider",
    "ClaudeBriefProvider",
    "ClaudeConcernScanner",
    "ConcernScanner",
    "EdgarFilingsProvider",
    "Filing",
    "FilingsProvider",
    "FmpFundamentalsProvider",
    "FmpQuoteProvider",
    "FundamentalsProvider",
    "Providers",
    "QuoteProvider",
    "StubBriefProvider",
    "StubConcernScanner",
    "StubFilingsProvider",
    "StubFundamentalsProvider",
    "StubQuoteProvider",
    "YfinanceFundamentalsProvider",
    "YfinanceQuoteProvider",
    "build_providers",
]
