"""Application configuration loaded from environment variables.

All settings are prefixed with ``OPENBOURSE_`` and may be supplied via a local
``.env`` file. See ``.env.example`` in the repo root for the canonical list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="OPENBOURSE_",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://openbourse:openbourse@localhost:5432/openbourse",
        description="Async SQLAlchemy URL. Use sqlite+aiosqlite:///:memory: for tests.",
    )

    fmp_api_key: SecretStr | None = None
    edgar_user_agent: str = "openbourse contact@example.com"
    claude_api_key: SecretStr | None = None
    claude_model: str = "claude-sonnet-4-6"

    use_stubs: bool = Field(
        default=True,
        description="When true, providers return fixture data instead of calling external APIs.",
    )

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings — useful in tests that mutate the environment."""

    get_settings.cache_clear()
