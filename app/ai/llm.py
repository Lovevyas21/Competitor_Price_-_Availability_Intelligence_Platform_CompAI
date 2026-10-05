from __future__ import annotations

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.ingestion.ratelimit import (
    QuotaExhausted,
    RateLimited,
    SourceLimits,
    get_rate_limiter,
    register_limits,
)

log = get_logger(__name__)

LLM_SOURCE = "llm"


class BudgetExhausted(RuntimeError):
    pass


def configure_budget(settings: Settings | None = None) -> SourceLimits:
    s = settings or get_settings()
    limits = SourceLimits(
        requests_per_minute=s.llm_requests_per_minute,
        burst=max(1, int(s.llm_requests_per_minute / 2)),
        daily_quota=s.llm_daily_request_limit,
    )
    register_limits(LLM_SOURCE, limits)
    return limits


def reserve(requests: int, settings: Settings | None = None) -> None:
    s = settings or get_settings()
    configure_budget(s)
    limiter = get_rate_limiter()

    try:
        limiter.acquire(LLM_SOURCE, tokens=requests)
        used = limiter.consume_daily(LLM_SOURCE, count=requests)
    except RateLimited as exc:
        raise BudgetExhausted(f"LLM rate limit reached; retry in {exc.retry_after:.0f}s") from exc
    except QuotaExhausted as exc:
        raise BudgetExhausted(
            f"LLM daily allowance of {s.llm_daily_request_limit} requests is spent"
        ) from exc

    log.info(
        "llm.budget_reserved",
        requests=requests,
        used_today=used,
        daily_limit=s.llm_daily_request_limit,
    )


def budget_used_today() -> int:
    return get_rate_limiter().quota_used(LLM_SOURCE)


def _gemini_thinking_config(enabled: bool):
    try:
        from google.genai import types
    except ImportError:
        return None

    if enabled:
        return types.ThinkingConfig(include_thoughts=True)
    return types.ThinkingConfig(include_thoughts=False, thinking_budget=0)


def build_llm(model: str, settings: Settings | None = None):
    from crewai import LLM

    s = settings or get_settings()
    kwargs: dict = {"model": model, "max_tokens": s.llm_max_output_tokens}

    if model.startswith("gemini/"):
        config = _gemini_thinking_config(s.llm_thinking)
        if config is not None:
            kwargs["thinking_config"] = config

    return LLM(**kwargs)
