"""Tests for settings loading."""

from __future__ import annotations

from openbourse.config import Settings, get_settings, reset_settings_cache


def test_defaults_use_stubs() -> None:
    settings = Settings(_env_file=None)
    assert settings.use_stubs is True


def test_get_settings_caches(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENBOURSE_LOG_LEVEL", "DEBUG")
    a = get_settings()
    b = get_settings()
    assert a is b


def test_reset_settings_cache_picks_up_new_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENBOURSE_LOG_LEVEL", "INFO")
    reset_settings_cache()
    a = get_settings()
    assert a.log_level == "INFO"
    monkeypatch.setenv("OPENBOURSE_LOG_LEVEL", "DEBUG")
    reset_settings_cache()
    b = get_settings()
    assert b.log_level == "DEBUG"
