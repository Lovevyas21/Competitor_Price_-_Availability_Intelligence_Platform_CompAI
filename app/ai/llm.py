"""LLM construction and spend control.

Written against a free-tier key, where the scarce resources are requests per day and
tokens per request, and where exceeding either degrades the brief silently -- narration
falls back to the deterministic renderer, which looks like success.

Three levers, in order of how much they save:

1. **Reasoning off.** Measured on `gemini-3.5-flash`: a short narration prompt cost 796
   tokens with reasoning enabled and 105 with it disabled, for an equivalent answer --
   697 of those tokens were "thoughts". The crew narrates a closed, already-validated
   facts payload; there is no problem here to reason about, so this is close to free.

2. **One call instead of three.** The full crew sends the same facts payload to an
   analyst, an interpreter and a writer. That is three requests and three copies of the
   payload for a brief the writer can produce alone.

3. **A hard ceiling.** Rate and daily caps enforced through the same Redis-backed guards
   the ingestion sources use, so the limit holds across every worker rather than
   per-process.

An output cap sits underneath all three: a brief that will not be read past a page has no
business generating four.
"""

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

#: Source name the LLM spends under, in the shared rate-limit and quota keyspace.
LLM_SOURCE = "llm"


class BudgetExhausted(RuntimeError):
    """Raised when a call would exceed the configured LLM allowance."""


def configure_budget(settings: Settings | None = None) -> SourceLimits:
    """Register the configured allowance so the shared guards enforce it."""
    s = settings or get_settings()
    limits = SourceLimits(
        requests_per_minute=s.llm_requests_per_minute,
        burst=max(1, int(s.llm_requests_per_minute / 2)),
        daily_quota=s.llm_daily_request_limit,
    )
    register_limits(LLM_SOURCE, limits)
    return limits


def reserve(requests: int, settings: Settings | None = None) -> None:
    """Claim budget for the calls a run is about to make, or refuse the run.

    Reserved up front, for the whole run rather than per call. A three-call crew that
    stops after two because the quota ran out has spent budget on a brief nobody gets;
    better to decline while the deterministic renderer can still stand in cleanly.

    Refusal is not an error state. The caller falls back to the deterministic brief,
    which is the same output the system produces when no model is configured at all.
    """
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
    """Requests spent today, for reporting."""
    return get_rate_limiter().quota_used(LLM_SOURCE)


def _gemini_thinking_config(enabled: bool):
    """Gemini's thinking switch, or None when this build cannot express it.

    CrewAI **auto-enables** reasoning for every Gemini 2.5 or newer model: if no thinking
    config is supplied it inserts `ThinkingConfig(include_thoughts=True)` itself. So
    leaving the parameter alone does not mean "provider default", it means "on" -- and
    turning it off requires passing a config rather than omitting one.

    The parameter is `thinking_config` holding a google-genai object. The LiteLLM-style
    `thinking={"type": "disabled"}` is silently ignored here, which is the failure mode
    worth naming: it looks correct, raises nothing, and changes no behaviour.
    """
    try:
        from google.genai import types  # noqa: PLC0415
    except ImportError:  # pragma: no cover - provider extra not installed
        return None

    if enabled:
        return types.ThinkingConfig(include_thoughts=True)
    return types.ThinkingConfig(include_thoughts=False, thinking_budget=0)


def build_llm(model: str, settings: Settings | None = None):
    """Construct the CrewAI LLM with the cost controls applied.

    Passing an `LLM` object rather than a bare model string is what makes this possible:
    a string carries no configuration, so the provider's own defaults apply -- and on
    Gemini that default is reasoning enabled, which was most of the bill.
    """
    from crewai import LLM  # noqa: PLC0415 - optional dependency, imported at use

    s = settings or get_settings()
    kwargs: dict = {"model": model, "max_tokens": s.llm_max_output_tokens}

    if model.startswith("gemini/"):
        config = _gemini_thinking_config(s.llm_thinking)
        if config is not None:
            kwargs["thinking_config"] = config

    return LLM(**kwargs)
