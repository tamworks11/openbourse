"""Factory selecting real or stubbed providers based on settings."""

from __future__ import annotations

from openbourse.config import Settings, get_settings
from openbourse.providers.base import Providers
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider


def build_providers(settings: Settings | None = None) -> Providers:
    """Construct the provider bundle.

    When ``settings.use_stubs`` is true (the default) every provider is the
    stub variant. Otherwise real clients are wired up. Real clients require
    the corresponding credential and will raise :class:`ValueError` if it is
    missing.
    """

    settings = settings or get_settings()

    if settings.use_stubs:
        return Providers(
            fundamentals=StubFundamentalsProvider(),
            filings=StubFilingsProvider(),
            brief=StubBriefProvider(),
            using_stubs=True,
        )

    fmp_key = settings.fmp_api_key.get_secret_value() if settings.fmp_api_key else ""
    claude_key = settings.claude_api_key.get_secret_value() if settings.claude_api_key else ""

    return Providers(
        fundamentals=FmpFundamentalsProvider(fmp_key),
        filings=EdgarFilingsProvider(settings.edgar_user_agent),
        brief=ClaudeBriefProvider(claude_key, model=settings.claude_model),
        using_stubs=False,
    )
