"""Tests for the provider registry / factory."""

from __future__ import annotations

import pytest
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
    assert isinstance(providers.fundamentals, StubFundamentalsProvider)
    assert isinstance(providers.filings, StubFilingsProvider)
    assert isinstance(providers.brief, StubBriefProvider)


def test_real_providers_when_stubs_disabled() -> None:
    settings = Settings(
        use_stubs=False,
        fmp_api_key=SecretStr("fake-fmp-key"),
        claude_api_key=SecretStr("fake-claude-key"),
        edgar_user_agent="test contact@example.com",
    )
    providers = build_providers(settings)
    assert providers.using_stubs is False
    assert isinstance(providers.fundamentals, FmpFundamentalsProvider)
    assert isinstance(providers.filings, EdgarFilingsProvider)
    assert isinstance(providers.brief, ClaudeBriefProvider)


def test_missing_fmp_key_raises() -> None:
    settings = Settings(use_stubs=False, edgar_user_agent="x@y.z")
    with pytest.raises(ValueError, match="FMP"):
        build_providers(settings)


def test_invalid_edgar_user_agent_raises() -> None:
    settings = Settings(
        use_stubs=False,
        fmp_api_key=SecretStr("k"),
        claude_api_key=SecretStr("k"),
        edgar_user_agent="no-email",
    )
    with pytest.raises(ValueError, match="EDGAR"):
        build_providers(settings)
