import os
from unittest.mock import MagicMock, patch

import pytest

from app.ai import crew
from app.core.settings import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _with(settings: Settings):
    return patch.object(crew, "get_settings", return_value=settings)


def test_no_model():
    with _with(_settings(llm_model=None)), pytest.raises(crew.CrewUnavailable) as exc:
        crew._require_llm()
    assert "LLM_MODEL" in str(exc.value)


def test_model_without_key():
    with (
        _with(_settings(llm_model="gemini/gemini-3.5-flash")),
        pytest.raises(crew.CrewUnavailable) as exc,
    ):
        crew._require_llm()
    assert "GEMINI_API_KEY" in str(exc.value)


def test_key_exported():
    settings = _settings(llm_model="gemini/gemini-3.5-flash", gemini_api_key="k-123")
    with _with(settings):
        assert crew._require_llm() == "gemini/gemini-3.5-flash"
    assert os.environ["GEMINI_API_KEY"] == "k-123"


def test_gemini_both_vars():
    settings = _settings(llm_model="gemini/gemini-3.5-flash", gemini_api_key="k-123")
    with _with(settings):
        crew._require_llm()
    assert os.environ["GEMINI_API_KEY"] == "k-123"
    assert os.environ["GOOGLE_API_KEY"] == "k-123"


def test_key_overrides_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "someone-elses-key")
    settings = _settings(llm_model="gemini/gemini-3.5-flash", gemini_api_key="ours")
    with _with(settings):
        crew._require_llm()
    assert os.environ["GOOGLE_API_KEY"] == "ours"
    assert os.environ["GEMINI_API_KEY"] == "ours"


def test_env_key_untouched(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-the-task-role")
    settings = _settings(llm_model="gemini/gemini-3.5-flash", gemini_api_key=None)
    with _with(settings):
        crew._require_llm()
    assert os.environ["GEMINI_API_KEY"] == "from-the-task-role"


def test_openai_key():
    settings = _settings(llm_model="openai/gpt-4o-mini", openai_api_key="sk-x")
    with _with(settings):
        crew._require_llm()
    assert os.environ["OPENAI_API_KEY"] == "sk-x"
    assert "GEMINI_API_KEY" not in os.environ


def test_unknown_provider():
    with _with(_settings(llm_model="ollama/llama3")):
        assert crew._require_llm() == "ollama/llama3"


@pytest.mark.parametrize(
    "message",
    [
        "503 UNAVAILABLE. This model is currently experiencing high demand.",
        "429 rate limit exceeded",
        "The model is overloaded, try again",
    ],
)
def test_transient_failures_are_retryable(message):
    assert crew._is_retryable(RuntimeError(message))


@pytest.mark.parametrize(
    "message",
    ["401 invalid api key", "404 model not found", "malformed request payload"],
)
def test_permanent_failures_are_not_retried(message):
    assert not crew._is_retryable(RuntimeError(message))


def test_busy_model_retried():
    busy = RuntimeError("503 UNAVAILABLE high demand")
    crew_obj = MagicMock()
    crew_obj.kickoff.side_effect = [busy, busy, "the brief"]

    with patch.object(crew.time, "sleep") as slept:
        assert crew._kickoff_with_retry(crew_obj, "gemini/x") == "the brief"

    assert crew_obj.kickoff.call_count == 3
    assert [c.args[0] for c in slept.call_args_list] == [4.0, 8.0]


def test_bad_key_not_retried():
    crew_obj = MagicMock()
    crew_obj.kickoff.side_effect = RuntimeError("401 invalid api key")

    with patch.object(crew.time, "sleep") as slept, pytest.raises(RuntimeError):
        crew._kickoff_with_retry(crew_obj, "gemini/x")

    assert crew_obj.kickoff.call_count == 1
    slept.assert_not_called()


def test_retries_bounded():
    crew_obj = MagicMock()
    crew_obj.kickoff.side_effect = RuntimeError("503 high demand")

    with patch.object(crew.time, "sleep"), pytest.raises(RuntimeError):
        crew._kickoff_with_retry(crew_obj, "gemini/x")

    assert crew_obj.kickoff.call_count == crew.MAX_ATTEMPTS


def test_crewai_quiet(monkeypatch):
    for name in crew._QUIET_DEFAULTS:
        monkeypatch.delenv(name, raising=False)
    crew._silence_crewai_prompts()
    assert os.environ["CREWAI_TRACING_ENABLED"] == "false"
    assert os.environ["OTEL_SDK_DISABLED"] == "true"


def test_tracing_opt_in(monkeypatch):
    monkeypatch.setenv("CREWAI_TRACING_ENABLED", "true")
    crew._silence_crewai_prompts()
    assert os.environ["CREWAI_TRACING_ENABLED"] == "true"
