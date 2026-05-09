"""Factory selecting concrete providers based on settings.

Two layers of selection:

1. ``settings.use_stubs`` is the master kill-switch. When true, every
   provider is the stub variant — used by the test suite to avoid network.

2. Otherwise:
   * **Fundamentals** is chosen by ``settings.fundamentals_provider``:
     ``"yfinance"`` (default, free, no key), ``"fmp"`` (requires key),
     or ``"stub"``.
   * **Filings** goes live when the EDGAR User-Agent contains an email,
     otherwise stub.
   * **Brief** goes live when a Claude API key is present, otherwise stub.

This per-provider mix-and-match is deliberate — a missing Claude key
shouldn't disable an otherwise-working FMP/yfinance setup.
"""

from __future__ import annotations

from openbourse.config import Settings, get_settings
from openbourse.providers.base import (
    BriefProvider,
    ConcernScanner,
    FilingsProvider,
    FundamentalsProvider,
    Providers,
)
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider
from openbourse.providers.scanner import ClaudeConcernScanner, StubConcernScanner
from openbourse.providers.yfinance import YfinanceFundamentalsProvider


def build_providers(settings: Settings | None = None) -> Providers:
    """Construct the provider bundle, dispatching by settings.

    See module docstring for the selection rules.
    """
    settings = settings or get_settings()

    if settings.use_stubs:
        return Providers(
            fundamentals=StubFundamentalsProvider(),
            filings=StubFilingsProvider(),
            brief=StubBriefProvider(),
            scanner=StubConcernScanner(),
            fundamentals_mode="stub",
            filings_mode="stub",
            brief_mode="stub",
            scanner_mode="stub",
        )

    fundamentals, fundamentals_mode = _build_fundamentals(settings)
    filings, filings_mode = _build_filings(settings)
    brief, brief_mode = _build_brief(settings)
    scanner, scanner_mode = _build_scanner(settings)

    return Providers(
        fundamentals=fundamentals,
        filings=filings,
        brief=brief,
        scanner=scanner,
        fundamentals_mode=fundamentals_mode,
        filings_mode=filings_mode,
        brief_mode=brief_mode,
        scanner_mode=scanner_mode,
    )


def _build_fundamentals(settings: Settings) -> tuple[FundamentalsProvider, str]:
    """Pick a fundamentals provider based on ``settings.fundamentals_provider``.

    Falls back to the stub if the requested provider can't be constructed
    (e.g. ``fmp`` without an API key).
    """
    choice = (settings.fundamentals_provider or "yfinance").lower()

    provider: FundamentalsProvider
    if choice == "stub":
        provider = StubFundamentalsProvider()
        return provider, "stub"

    if choice == "fmp":
        fmp_key = settings.fmp_api_key.get_secret_value() if settings.fmp_api_key else ""
        if fmp_key:
            provider = FmpFundamentalsProvider(fmp_key)
            return provider, "fmp"
        provider = StubFundamentalsProvider()
        return provider, "stub"

    # Default: yfinance. No credentials required.
    provider = YfinanceFundamentalsProvider()
    return provider, "yfinance"


def _build_filings(settings: Settings) -> tuple[FilingsProvider, str]:
    """EDGAR live when the configured User-Agent contains an email."""
    if "@" in settings.edgar_user_agent:
        return EdgarFilingsProvider(settings.edgar_user_agent), "live"
    return StubFilingsProvider(), "stub"


def _build_brief(settings: Settings) -> tuple[BriefProvider, str]:
    """Claude live when a key is set, otherwise the deterministic stub."""
    claude_key = settings.claude_api_key.get_secret_value() if settings.claude_api_key else ""
    if claude_key:
        return (
            ClaudeBriefProvider(claude_key, model=settings.claude_model),
            "live",
        )
    return StubBriefProvider(), "stub"


def _build_scanner(settings: Settings) -> tuple[ConcernScanner, str]:
    """Concern scanner shares the Claude key with the brief provider."""
    claude_key = settings.claude_api_key.get_secret_value() if settings.claude_api_key else ""
    if claude_key:
        return (
            ClaudeConcernScanner(claude_key, model=settings.claude_model),
            "live",
        )
    return StubConcernScanner(), "stub"
