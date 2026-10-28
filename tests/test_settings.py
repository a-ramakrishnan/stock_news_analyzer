from types import SimpleNamespace

import anthropic
import httpx
import pytest

from stock_news_analyzer import config
from stock_news_analyzer import settings_store as store
from stock_news_analyzer.agents import orchestrator as orch
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.llm import check_key
from stock_news_analyzer.models import Run


@pytest.fixture
def saved(session, test_database_url, monkeypatch):
    """Settings read from the test database."""
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "20")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    get_settings.cache_clear()
    return session


@pytest.mark.db
@pytest.mark.saved_settings
def test_saved_settings_take_the_place_of_env(saved):
    assert get_settings().llm_monthly_budget_usd == 20
    assert store.source(saved, "llm_monthly_budget_usd") == ".env"
    store.save(saved, "llm_monthly_budget_usd", "5")
    store.save(saved, "anthropic_api_key", "from-page")
    cfg = get_settings()
    assert cfg.llm_monthly_budget_usd == 5.0 and cfg.anthropic_api_key == "from-page"
    assert store.source(saved, "llm_monthly_budget_usd") == "Settings page"
    assert store.source(saved, "llm_model_triage") == "default"
    store.save(saved, "llm_monthly_budget_usd", 7.5)  # saved again: replaced
    assert get_settings().llm_monthly_budget_usd == 7.5
    store.remove(saved, "anthropic_api_key")
    assert get_settings().anthropic_api_key == "from-env"
    with pytest.raises(KeyError):
        store.save(saved, "database_url", "postgresql://elsewhere")


@pytest.mark.db
@pytest.mark.saved_settings
def test_saved_values_are_read_again_after_a_while(saved, monkeypatch):
    store.save(saved, "unusual_threshold", 2.5)
    assert get_settings().unusual_threshold == 2.5
    # Another process (the dashboard) saves a value; this one sees it once the cache expires.
    saved.execute(store.SavedSetting.__table__.update().values(value="1.8"))
    saved.commit()
    assert get_settings().unusual_threshold == 2.5
    monkeypatch.setattr(config, "SAVED_TTL", 0.0)
    assert get_settings().unusual_threshold == 1.8


@pytest.mark.saved_settings
def test_no_database_means_env_alone(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://sna:sna@localhost:1/nothing")
    monkeypatch.setenv("LLM_MONTHLY_BUDGET_USD", "9")
    get_settings.cache_clear()
    assert get_settings().llm_monthly_budget_usd == 9


@pytest.mark.db
@pytest.mark.saved_settings
def test_paused_jobs_skip_their_schedule_but_not_a_run_by_hand(saved, monkeypatch):
    ran = []
    monkeypatch.setattr(orch, "JOBS", {"news": lambda s: ran.append("news") or "ok"})
    store.save(saved, "paused_jobs", "news, themes")
    assert store.paused_jobs(get_settings()) == {"news", "themes"}
    assert orch.scheduled_run("news") is None and ran == []
    assert orch.run_job("news").status == "ok" and ran == ["news"]
    store.save(saved, "paused_jobs", "")
    assert orch.scheduled_run("news").status == "ok" and saved.query(Run).count() == 2


def test_job_notes_from_the_schedule_file():
    notes = orch.job_notes()
    assert notes["filings"] == "new BSE + NSE announcements"
    assert set(notes) == {j.name for j in orch.load_schedule()}


def test_check_key():
    def refusing(**kw):
        request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        raise anthropic.AuthenticationError(
            "invalid x-api-key", response=httpx.Response(401, request=request), body=None
        )

    assert check_key("k", SimpleNamespace(models=SimpleNamespace(list=refusing))) == (
        "Anthropic did not accept this key"
    )
    accepting = SimpleNamespace(models=SimpleNamespace(list=lambda **kw: []))
    assert check_key("k", accepting) is None
