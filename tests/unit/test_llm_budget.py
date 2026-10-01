"""LLM cost controls.

Written for a free-tier key, where the failure mode is not an exception but a quiet
downgrade: every one of these controls, if it stops working, still produces a brief. The
deterministic renderer stands in and the system looks healthy while the allowance drains
or the narration silently stops happening.

The measured baseline these tests protect, on `gemini-3.5-flash` with the real facts
payload: 12,473 tokens over 3 requests before, 2,422 tokens over 1 request after.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai import cache, llm
from app.core.settings import Settings
from app.ingestion.ratelimit import QuotaExhausted, RateLimited, SourceLimits


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# thinking config -- the single biggest saving
def test_thinking_is_disabled_by_default():
    """Regression: CrewAI auto-enables reasoning for every Gemini >= 2.5.

    Omitting the parameter does not mean "provider default", it means "on". Turning it
    off requires passing a config rather than leaving one out -- which is why the
    LiteLLM-style `thinking={"type": "disabled"}` did nothing: accepted, ignored, and
    3,338 reasoning tokens still on the bill.
    """
    config = llm._gemini_thinking_config(enabled=False)
    assert config is not None
    assert config.include_thoughts is False
    assert config.thinking_budget == 0


def test_thinking_can_be_turned_back_on():
    assert llm._gemini_thinking_config(enabled=True).include_thoughts is True


def test_build_llm_passes_the_gemini_thinking_parameter():
    fake_llm = MagicMock()
    with patch.dict("sys.modules", {"crewai": MagicMock(LLM=fake_llm)}):
        llm.build_llm("gemini/gemini-3.5-flash", _settings())
    kwargs = fake_llm.call_args.kwargs
    assert kwargs["thinking_config"].thinking_budget == 0
    assert kwargs["max_tokens"] == 1200


def test_non_gemini_models_get_no_thinking_config():
    """The parameter is Gemini-specific; sending it elsewhere is at best ignored."""
    fake_llm = MagicMock()
    with patch.dict("sys.modules", {"crewai": MagicMock(LLM=fake_llm)}):
        llm.build_llm("openai/gpt-4o-mini", _settings())
    assert "thinking_config" not in fake_llm.call_args.kwargs


def test_output_cap_is_configurable():
    fake_llm = MagicMock()
    with patch.dict("sys.modules", {"crewai": MagicMock(LLM=fake_llm)}):
        llm.build_llm("gemini/x", _settings(llm_max_output_tokens=400))
    assert fake_llm.call_args.kwargs["max_tokens"] == 400


# budget
def test_budget_is_registered_from_settings():
    limits = llm.configure_budget(_settings(llm_requests_per_minute=6, llm_daily_request_limit=50))
    assert limits.daily_quota == 50
    assert limits.requests_per_minute == 6


def test_a_whole_run_is_reserved_up_front():
    """Three calls are claimed together, not one at a time.

    A crew that stops after its second call because the quota ran out has spent budget
    on a brief nobody receives.
    """
    limiter = MagicMock()
    limiter.consume_daily.return_value = 3
    with patch.object(llm, "get_rate_limiter", return_value=limiter):
        llm.reserve(3, _settings())
    limiter.acquire.assert_called_once_with(llm.LLM_SOURCE, tokens=3)
    limiter.consume_daily.assert_called_once_with(llm.LLM_SOURCE, count=3)


def test_exhausted_daily_allowance_refuses_the_run():
    limiter = MagicMock()
    limiter.consume_daily.side_effect = QuotaExhausted("llm", 200)
    with (
        patch.object(llm, "get_rate_limiter", return_value=limiter),
        pytest.raises(llm.BudgetExhausted) as exc,
    ):
        llm.reserve(1, _settings())
    assert "daily allowance" in str(exc.value)


def test_rate_limit_refuses_the_run_with_a_retry_hint():
    limiter = MagicMock()
    limiter.acquire.side_effect = RateLimited("llm", 12.0)
    with (
        patch.object(llm, "get_rate_limiter", return_value=limiter),
        pytest.raises(llm.BudgetExhausted) as exc,
    ):
        llm.reserve(1, _settings())
    assert "12s" in str(exc.value)


def test_limits_can_be_registered_at_runtime():
    from app.ingestion import ratelimit

    ratelimit.register_limits("llm-test", SourceLimits(requests_per_minute=1, daily_quota=2))
    assert ratelimit.limits_for("llm-test").daily_quota == 2


# narration cache
class _Facts:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


def test_same_facts_produce_the_same_fingerprint():
    a = _Facts({"undercuts": 108, "products": 3932})
    b = _Facts({"products": 3932, "undercuts": 108})  # same facts, different order
    assert cache.facts_fingerprint(a, "m") == cache.facts_fingerprint(b, "m")


def test_a_changed_price_changes_the_fingerprint():
    a = _Facts({"undercuts": 108})
    b = _Facts({"undercuts": 109})
    assert cache.facts_fingerprint(a, "m") != cache.facts_fingerprint(b, "m")


def test_the_model_is_part_of_the_key():
    """Switching models is meant to change the prose, not serve the old model's output."""
    facts = _Facts({"undercuts": 108})
    assert cache.facts_fingerprint(facts, "gemini/a") != cache.facts_fingerprint(facts, "gemini/b")


def test_cache_returns_a_previous_narration():
    client = MagicMock()
    client.get.return_value = "# Brief"
    with patch.object(cache, "_client", return_value=client):
        assert cache.get("fp", _settings()) == "# Brief"


def test_an_unreachable_cache_is_a_miss_not_an_error():
    """A cache that breaks must cost a request, never an exception."""
    with patch.object(cache, "_client", side_effect=OSError("redis down")):
        assert cache.get("fp", _settings()) is None
        cache.put("fp", "body", _settings())  # must not raise


def test_caching_can_be_switched_off():
    client = MagicMock()
    with patch.object(cache, "_client", return_value=client):
        assert cache.get("fp", _settings(llm_cache_ttl_seconds=0)) is None
        cache.put("fp", "b", _settings(llm_cache_ttl_seconds=0))
    client.get.assert_not_called()
    client.setex.assert_not_called()


def test_cached_body_is_stored_with_the_configured_ttl():
    client = MagicMock()
    with patch.object(cache, "_client", return_value=client):
        cache.put("fp", "body", _settings(llm_cache_ttl_seconds=3600))
    args = client.setex.call_args.args
    assert args[0].endswith("fp")
    assert args[1] == 3600


# the cache short-circuit in generate_brief
def test_a_cache_hit_never_reaches_the_model():
    """The saving that matters most: a brief regenerated on unchanged facts is free."""
    from app.ai import brief

    facts = MagicMock()
    facts.all_numbers.return_value = {108.0}

    with (
        patch.object(brief, "collect_weekly_facts", return_value=facts),
        patch.object(brief, "render_markdown", return_value="# deterministic"),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.cache.facts_fingerprint", return_value="fp"),
        patch("app.ai.cache.get", return_value="# 108 undercuts"),
        patch("app.ai.crew.narrate_with_crew") as narrate,
    ):
        result = brief.generate_brief(MagicMock(), use_llm=True)

    assert result.source == "llm-cached"
    narrate.assert_not_called()


def test_a_cache_hit_that_no_longer_validates_is_not_served():
    """A hit is re-checked against the guard, not trusted because it is cached."""
    from app.ai import brief

    facts = MagicMock()
    facts.all_numbers.return_value = {1.0}

    with (
        patch.object(brief, "collect_weekly_facts", return_value=facts),
        patch.object(brief, "render_markdown", return_value="# deterministic"),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.cache.facts_fingerprint", return_value="fp"),
        patch("app.ai.cache.get", return_value="a brief citing 999 which is not a fact"),
        patch("app.ai.crew.narrate_with_crew", return_value="# 1 thing") as narrate,
        patch("app.ai.cache.put"),
    ):
        result = brief.generate_brief(MagicMock(), use_llm=True)

    narrate.assert_called_once()
    assert result.source == "llm"


def test_a_refused_budget_falls_back_rather_than_failing():
    """Running out of allowance yields a plainer brief, not an error."""
    from app.ai import brief

    facts = MagicMock()
    facts.all_numbers.return_value = set()

    with (
        patch.object(brief, "collect_weekly_facts", return_value=facts),
        patch.object(brief, "render_markdown", return_value="# deterministic"),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.cache.facts_fingerprint", return_value="fp"),
        patch("app.ai.cache.get", return_value=None),
        patch(
            "app.ai.crew.narrate_with_crew",
            side_effect=llm.BudgetExhausted("daily allowance spent"),
        ),
    ):
        result = brief.generate_brief(MagicMock(), use_llm=True)

    assert result.source == "deterministic"
    assert result.body == "# deterministic"


def test_only_guard_passing_output_is_cached():
    """Caching a rejected brief means paying once for a bad answer and serving it all day."""
    from app.ai import brief

    facts = MagicMock()
    facts.all_numbers.return_value = {1.0}

    with (
        patch.object(brief, "collect_weekly_facts", return_value=facts),
        patch.object(brief, "render_markdown", return_value="# deterministic"),
        patch("app.ai.crew._require_llm", return_value="gemini/x"),
        patch("app.ai.cache.facts_fingerprint", return_value="fp"),
        patch("app.ai.cache.get", return_value=None),
        patch("app.ai.crew.narrate_with_crew", return_value="invented figure 4242"),
        patch("app.ai.cache.put") as put,
    ):
        result = brief.generate_brief(MagicMock(), use_llm=True)

    assert result.source == "deterministic"
    put.assert_not_called()
