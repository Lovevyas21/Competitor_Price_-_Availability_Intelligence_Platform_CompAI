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

    database_url_override: str | None = None

    redis_url: str = "redis://localhost:6379/0"

    bronze_backend: Literal["local", "s3"] = "local"
    bronze_local_path: str = "./data/bronze"
    deadletter_local_path: str = "./data/deadletter"
    bronze_s3_bucket: str | None = None
    bronze_s3_endpoint_url: str | None = None

    port: int = 8000

    bestbuy_api_key: str | None = None
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    digikey_client_id: str | None = None
    digikey_client_secret: str | None = None

    llm_model: str | None = None

    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    llm_thinking: bool = False
    llm_max_output_tokens: int = 1200

    llm_single_call: bool = True

    llm_cache_ttl_seconds: int = 86_400

    llm_requests_per_minute: float = 10.0
    llm_daily_request_limit: int = 200

    slack_webhook_url: str | None = None

    alert_email_to: str | None = None
    alert_email_from: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = 15.0

    ses_region: str | None = None
    api_key: str | None = None
    api_title: str = "Competitor Price Intelligence API"

    showcase_enabled: bool | None = None

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
        return bool(self.database_url_override)

    @property
    def alembic_url(self) -> str:
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
