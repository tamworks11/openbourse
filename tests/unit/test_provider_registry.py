"""Tests for the provider registry / factory."""

from __future__ import annotations

from pydantic import SecretStr

from openbourse.config import Settings
from openbourse.providers import build_providers
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider
from openbourse.providers.yfinance import YfinanceFundamentalsProvider


def test_use_stubs_master_switch_returns_all_stubs() -> None:
    settings = Settings(use_stubs=True)
    providers = build_providers(settings)
    assert providers.using_stubs is True
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert isinstance(providers.filings, StubFilingsProvider)
    assert isinstance(providers.brief, StubBriefProvider)


def test_default_fundamentals_provider_is_yfinance() -> None:
    settings = Settings(
        use_stubs=False,
        fundamentals_provider="yfinance",
        fmp_api_key=None,
        claude_api_key=None,
        edgar_user_agent="no-email",
    )
    providers = build_providers(settings)
    assert isinstance(providers.fundamentals, YfinanceFundamentalsProvider)
    assert providers.fundamentals_mode == "yfinance"


def test_fmp_selected_with_key_present() -> None:
    settings = Settings(
        use_stubs=False,
        fundamentals_provider="fmp",
        fmp_api_key=SecretStr("fake-fmp-key"),
        claude_api_key=SecretStr("fake-claude-key"),
        edgar_user_agent="test contact@example.com",
    )
    providers = build_providers(settings)
    assert isinstance(providers.fundamentals, FmpFundamentalsProvider)
    assert providers.fundamentals_mode == "fmp"
    assert isinstance(providers.filings, EdgarFilingsProvider)
    assert isinstance(providers.brief, ClaudeBriefProvider)


def test_fmp_selected_without_key_falls_back_to_stub() -> None:
    """Choosing fmp without supplying a key shouldn't crash — quietly degrade."""
    settings = Settings(
        use_stubs=False,
        fundamentals_provider="fmp",
        fmp_api_key=None,
        claude_api_key=None,
        edgar_user_agent="no-email",
    )
    providers = build_providers(settings)
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert providers.fundamentals_mode == "stub"


def test_stub_provider_when_explicitly_selected() -> None:
    settings = Settings(
        use_stubs=False,
        fundamentals_provider="stub",
        fmp_api_key=None,
        claude_api_key=None,
        edgar_user_agent="no-email",
    )
    providers = build_providers(settings)
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert providers.fundamentals_mode == "stub"


def test_partial_credentials_mix_live_and_stub() -> None:
    """yfinance fundamentals + EDGAR live + Claude stub — the common case."""
    settings = Settings(
        use_stubs=False,
        fundamentals_provider="yfinance",
        edgar_user_agent="test contact@example.com",
        claude_api_key=None,
    )
    providers = build_providers(settings)
    assert isinstance(providers.fundamentals, YfinanceFundamentalsProvider)
    assert providers.filings_mode == "live"
    assert providers.brief_mode == "stub"
    assert isinstance(providers.brief, StubBriefProvider)
