"""Factory selecting real or stubbed providers based on settings.

Per-provider fallback: when ``use_stubs`` is false, each provider is
constructed live *if* its credential is present, and stubbed otherwise.
This means a working FMP setup keeps working even when the Claude key is
empty — the brief provider just falls back to the deterministic stub.
"""

from __future__ import annotations

from openbourse.config import Settings, get_settings
from openbourse.providers.base import (
    BriefProvider,
    FilingsProvider,
    FundamentalsProvider,
    Providers,
)
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider


def build_providers(settings: Settings | None = None) -> Providers:
    """Construct the provider bundle.

    When ``settings.use_stubs`` is true (the default) every provider is a
    stub. Otherwise each provider is built live where its credential is
    available and stubbed where it isn't, so contributors can flip on FMP
    without also needing Claude or vice-versa.
    """
    settings = settings or get_settings()

    if settings.use_stubs:
        return Providers(
            fundamentals=StubFundamentalsProvider(),
            filings=StubFilingsProvider(),
            brief=StubBriefProvider(),
            fundamentals_mode="stub",
            filings_mode="stub",
            brief_mode="stub",
        )

    fmp_key = settings.fmp_api_key.get_secret_value() if settings.fmp_api_key else ""
    claude_key = settings.claude_api_key.get_secret_value() if settings.claude_api_key else ""
    edgar_ua = settings.edgar_user_agent

    fundamentals: FundamentalsProvider
    fundamentals_mode: str
    if fmp_key:
        fundamentals = FmpFundamentalsProvider(fmp_key)
        fundamentals_mode = "live"
    else:
        fundamentals = StubFundamentalsProvider()
        fundamentals_mode = "stub"

    filings: FilingsProvider
    filings_mode: str
    if "@" in edgar_ua:
        filings = EdgarFilingsProvider(edgar_ua)
        filings_mode = "live"
    else:
        filings = StubFilingsProvider()
        filings_mode = "stub"

    brief: BriefProvider
    brief_mode: str
    if claude_key:
        brief = ClaudeBriefProvider(claude_key, model=settings.claude_model)
        brief_mode = "live"
    else:
        brief = StubBriefProvider()
        brief_mode = "stub"

    return Providers(
        fundamentals=fundamentals,
        filings=filings,
        brief=brief,
        fundamentals_mode=fundamentals_mode,
        filings_mode=filings_mode,
        brief_mode=brief_mode,
    )
