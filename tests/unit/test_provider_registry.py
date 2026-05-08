"""Tests for the provider registry / factory."""

from __future__ import annotations

from pydantic import SecretStr

from openbourse.config import Settings
from openbourse.providers import build_providers
from openbourse.providers.claude import ClaudeBriefProvider, StubBriefProvider
from openbourse.providers.edgar import EdgarFilingsProvider, StubFilingsProvider
from openbourse.providers.fmp import FmpFundamentalsProvider, StubFundamentalsProvider


def test_default_settings_returns_stubs() -> None:
    settings = Settings(use_stubs=True)
    providers = build_providers(settings)
    assert providers.using_stubs is True
    assert providers.fundamentals_mode == "stub"
    assert providers.filings_mode == "stub"
    assert providers.brief_mode == "stub"
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert isinstance(providers.filings, StubFilingsProvider)
    assert isinstance(providers.brief, StubBriefProvider)


def test_all_real_when_every_credential_set() -> None:
    settings = Settings(
        use_stubs=False,
        fmp_api_key=SecretStr("fake-fmp-key"),
        claude_api_key=SecretStr("fake-claude-key"),
        edgar_user_agent="test contact@example.com",
    )
    providers = build_providers(settings)
    assert providers.all_live is True
    assert isinstance(providers.fundamentals, FmpFundamentalsProvider)
    assert isinstance(providers.filings, EdgarFilingsProvider)
    assert isinstance(providers.brief, ClaudeBriefProvider)


def test_partial_credentials_mix_live_and_stub() -> None:
    """FMP key set, Claude missing → live FMP, stub Claude. The realistic flow."""
    settings = Settings(
        use_stubs=False,
        fmp_api_key=SecretStr("fake-fmp-key"),
        edgar_user_agent="test contact@example.com",
        # claude_api_key intentionally absent
    )
    providers = build_providers(settings)
    assert providers.fundamentals_mode == "live"
    assert providers.filings_mode == "live"
    assert providers.brief_mode == "stub"
    assert isinstance(providers.fundamentals, FmpFundamentalsProvider)
    assert isinstance(providers.brief, StubBriefProvider)


def test_no_credentials_falls_back_to_all_stubs() -> None:
    # Explicit ``None`` overrides any value Pydantic would otherwise read from
    # the contributor's ``.env`` file.
    settings = Settings(
        use_stubs=False,
        edgar_user_agent="no-email",
        fmp_api_key=None,
        claude_api_key=None,
    )
    providers = build_providers(settings)
    assert providers.using_stubs is True
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert isinstance(providers.filings, StubFilingsProvider)
    assert isinstance(providers.brief, StubBriefProvider)
