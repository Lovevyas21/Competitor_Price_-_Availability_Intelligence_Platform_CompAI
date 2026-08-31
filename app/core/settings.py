"""Application settings, loaded from environment / .env (pydantic-settings)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    postgres_user: str = "cpi"
    postgres_password: str = "cpi_local_dev"
    postgres_db: str = "cpi"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    db_connect_timeout_seconds: int = 10

    # Full connection URL, overriding the parts above. Managed providers (Neon, Supabase,
    # RDS) hand out one string, so this is how a hosted database is wired in without
    # picking the URL apart. Leave unset to use the local docker-compose Postgres.
    database_url_override: str | None = None

    redis_url: str = "redis://localhost:6379/0"

    # Bronze raw-payload storage. "local" for dev; "s3" once AWS lands (phase 6).
    bronze_backend: Literal["local", "s3"] = "local"
    bronze_local_path: str = "./data/bronze"
    deadletter_local_path: str = "./data/deadletter"
    bronze_s3_bucket: str | None = None

    # Source credentials -- all optional, keyless sources ignore them.
    bestbuy_api_key: str | None = None
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    digikey_client_id: str | None = None
    digikey_client_secret: str | None = None

    # --- alerting / serving ---
    slack_webhook_url: str | None = None
    api_key: str | None = None
    api_title: str = "Competitor Price Intelligence API"

    http_timeout_seconds: float = Field(default=20.0, gt=0)

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self._normalise_url(self.database_url_override)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @staticmethod
    def _normalise_url(url: str) -> str:
        """Make a provider-supplied URL usable by SQLAlchemy + psycopg 3.

        Providers hand out `postgres://` or `postgresql://`, both of which SQLAlchemy
        routes to psycopg2. This project uses psycopg 3, so the driver is pinned
        explicitly rather than relying on whatever happens to be installed.
        """
        for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
            if url.startswith(prefix):
                return url
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        return url

    @property
    def is_managed_database(self) -> bool:
        """True when pointing at a hosted database rather than local compose."""
        return self.database_url_override is not None

    @property
    def alembic_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
