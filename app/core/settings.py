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

    # --- AI layer (phase 5) ---
    # Model id in litellm form, e.g. "gemini/gemini-2.0-flash" or "anthropic/claude-haiku-4-5".
    # Unset means the weekly brief renders deterministically -- no key, no cost, no
    # possibility of a fabricated number.
    llm_model: str | None = None

    # Provider credentials. LiteLLM (under CrewAI) reads these from the process
    # environment, not from here, so `app.ai.crew` exports whichever one the configured
    # model needs. They are declared as settings anyway so that `.env` stays the single
    # place credentials live, and so a missing key fails with a sentence rather than a
    # provider authentication error.
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- LLM cost control ---
    # Written for a free-tier key, where both requests per day and tokens are scarce.
    #
    # `llm_thinking` off is the single biggest saving: measured on gemini-3.5-flash, a
    # short narration prompt cost 796 tokens with reasoning enabled and 105 with it
    # disabled -- 697 of those tokens were "thoughts" -- for an equivalent answer. This
    # job narrates a closed set of pre-validated facts; there is nothing to reason out.
    llm_thinking: bool = False
    llm_max_output_tokens: int = 1200

    # One model call instead of three. The full crew (analyst -> interpreter -> writer)
    # sends the same facts payload three times for a brief the writer could produce
    # alone. Set false to run the full crew when quota is not the constraint.
    llm_single_call: bool = True

    # Skip the model entirely when the facts have not changed since the last brief.
    # A brief regenerated twice in a day is one that costs nothing the second time.
    llm_cache_ttl_seconds: int = 86_400

    # Hard ceilings, shared across workers via Redis. Free tiers are usually ~10 rpm;
    # the daily figure is deliberately well under any published cap.
    llm_requests_per_minute: float = 10.0
    llm_daily_request_limit: int = 200

    # --- alerting / serving ---
    # Nothing is delivered anywhere unless a channel is explicitly configured. An
    # unconfigured channel is skipped, so a fresh checkout cannot message anyone.
    slack_webhook_url: str | None = None

    # Email digest. Both a recipient list and a sender are required before anything sends.
    alert_email_to: str | None = None  # comma-separated
    alert_email_from: str | None = None

    # SMTP works with any relay, including Amazon SES's SMTP endpoint.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = 15.0

    # SES via the API instead of SMTP. On EC2 the instance role supplies credentials,
    # so only the region and a verified sender are needed. Takes precedence over SMTP.
    ses_region: str | None = None
    api_key: str | None = None
    api_title: str = "Competitor Price Intelligence API"

    # The walkthrough UI at /showcase. It reads real mart data and is deliberately not
    # behind the API key, so it defaults to dev only: leaving None means "on in dev, off
    # in prod". Set it true to serve it from a demo deployment on purpose.
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
