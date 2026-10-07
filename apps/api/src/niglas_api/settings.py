"""Runtime settings for the API service."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from ``NIGLAS_`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="NIGLAS_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = "postgresql+asyncpg://niglas:niglas@localhost:5432/niglas"
    jwt_secret: SecretStr = SecretStr("change-me-local-development-only")
    jwt_issuer: str = "niglas-local"
    token_ttl_minutes: int = Field(default=60, gt=0, le=24 * 60)
    max_events_per_batch: int = Field(default=500, gt=0, le=10_000)


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings for dependency injection."""
    return Settings()
