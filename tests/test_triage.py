import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_llm import FakeAnthropic, settings, usage
from test_news import CONFIG as NEWS_CONFIG
from test_news import FakeClient as FakeFeeds
from test_news import watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import news as nw
from stock_news_analyzer.agents import triage as tr
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import Document, DocumentCompany, LlmCall, NewsTriage

LT = "INE018A01030"
KVB = "INE036D01028"


def answer_each(kwargs, relevant=lambda title: True, importance=3):
    """A fake model: triages every <article> in the prompt, judging by its headline."""
    prompt = kwargs["messages"][0]["content"]
    items = []
    for doc_id, title in re.findall(r'<article id="(\d+)".*?\nHeadline: (.*?)\n', prompt, re.S):
        items.append(
            tr.ArticleTriage(
                id=int(doc_id),
                relevant=relevant(title),
                topic="order_win" if "order" in title else "market",
                sentiment="positive",
                importance=importance,
                summary=f"About: {title}",
            )
        )
    return SimpleNamespace(
        usage=usage(), parsed_output=tr.TriageBatch(articles=items), stop_reason="end_turn"
    )


@pytest.fixture
def news(watchlist):  # noqa: F811
    nw.NewsCollector(watchlist, FakeFeeds(failing=("broken",)), NEWS_CONFIG).collect(google=False)
    return watchlist


def _llm(session, reply=answer_each, **kw):
    client = FakeAnthropic(reply)
    return LLM(session, client=client, settings=settings(**kw)), client


@pytest.mark.db
def test_triage_judges_each_article_per_company(news):
    llm, client = _llm(news)
    pending = tr.pending(news)
    assert len(pending) == 4  # 3 articles; one mentions both LT and KVB
    result = tr.triage_news(news, llm, model="claude-haiku-5-5")
    assert (result.triaged, result.duplicates, result.calls, result.errors) == (4, 0, 2, [])
    assert result.cost_usd > 0 and news.query(LlmCall).count() == 2
    assert all(r["model"] == "claude-haiku-5-5" for r in client.requests)
    # One call per company, naming the company and its aliases from the watchlist file.
    lt_prompt = next(
        r for r in client.requests if r["messages"][0]["content"].startswith("Company: Larsen")
    )
    assert "Also called: L&T" in lt_prompt["messages"][0]["content"]
    rows = {(t.isin, t.topic) for t in news.query(NewsTriage)}
    assert (LT, "order_win") in rows and (KVB, "market") in rows
    assert tr.pending(news) == []
    again = tr.triage_news(news, llm)  # nothing left: no calls
    assert (again.triaged, again.calls) == (0, 0)


@pytest.mark.db
def test_repeated_story_reuses_the_first_articles_triage(news):
    first = news.query(Document).filter(Document.title.like("L&T bags%")).one()
    copy = Document(
        source="news:google",
        source_id="copy-1",
        doc_type="news",
        title="L&T bags 'large' orders for projects in New Delhi & Andhra Pradesh",
        published_at=first.published_at + timedelta(hours=5),
        publisher="Another Paper",
        url="https://example.com/copy",
        raw={},
    )
    news.add(copy)
    news.flush()
    news.add(DocumentCompany(document_id=copy.id, isin=LT))
    news.commit()

    llm, client = _llm(news)
    result = tr.triage_news(news, llm, symbol="LT")
    assert (result.triaged, result.duplicates) == (2, 1)
    assert "copy-1" not in str(client.requests)  # the copy was never sent to the model
    dup = news.get(NewsTriage, (copy.id, LT))
    assert dup.duplicate_of == first.id and dup.model is None and dup.topic == "order_win"


@pytest.mark.db
def test_failures_leave_articles_pending_and_budget_stops_the_run(news):
    def broken(kwargs):
        return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="refusal")

    llm, _ = _llm(news, broken)
    result = tr.triage_news(news, llm)
    assert result.triaged == 0 and len(result.errors) == 2 and len(tr.pending(news)) == 4

    llm, client = _llm(news, llm_monthly_budget_usd=0.0)
    result = tr.triage_news(news, llm)
    assert "budget" in result.errors[0] and client.requests == []


@pytest.mark.db
def test_off_topic_and_importance_are_kept_within_range(news):
    llm, _ = _llm(
        news, lambda kw: answer_each(kw, relevant=lambda t: "gainers" not in t, importance=9)
    )
    tr.triage_news(news, llm)
    rows = news.query(NewsTriage).all()
    assert {t.importance for t in rows} == {5}  # clamped to 1..5
    gainers = [t for t in rows if not t.relevant]
    assert len(gainers) == 2  # the "top gainers" list, for both companies


@pytest.mark.db
def test_digest_shows_triaged_news_and_hides_off_topic(news):
    from datetime import datetime

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.sources.announcements import IST

    llm, _ = _llm(news, lambda kw: answer_each(kw, relevant=lambda t: "gainers" not in t))
    tr.triage_news(news, llm)
    # The "top gainers" item has no date in the feed, so it is stored with today's fetch time.
    md = build_digest(
        news, datetime(2026, 1, 1, tzinfo=IST), datetime.now(IST) + timedelta(days=1)
    ).markdown
    lt = md.split("## LT:")[1].split("## ")[0]
    assert "★★★ order_win, positive" in lt and "About: L&T bags 'large' orders" in lt
    assert "top gainers" not in lt and "1 off-topic or repeated articles hidden" in lt


@pytest.mark.db
def test_dashboard_news_filters_and_ai_usage(news):
    from stock_news_analyzer.ui import queries

    assert queries.llm_usage(news)["pending_triage"] == 4
    assert queries.news(news)["importance"].isna().all()  # nothing triaged yet

    llm, _ = _llm(news, lambda kw: answer_each(kw, relevant=lambda t: "gainers" not in t))
    tr.triage_news(news, llm)
    everything = queries.news(news)
    assert len(everything) == 4 and everything["summary"].notna().all()
    assert len(queries.news(news, hide_noise=True)) == 2  # the gainers list hidden twice
    assert list(queries.news(news, topics=["order_win"])["symbol"]) == ["LT"]
    assert queries.news(news, min_importance=4).empty

    usage = queries.llm_usage(news)
    assert usage["pending_triage"] == 0 and usage["spent"] > 0
    assert list(usage["by_task"]["task"]) == ["triage"] and usage["by_task"]["calls"][0] == 2


@pytest.mark.db
def test_cli_and_scheduled_job_without_an_api_key(news, test_database_url, monkeypatch):
    from typer.testing import CliRunner

    from stock_news_analyzer.agents.orchestrator import run_job
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # wins over a real key in .env
    get_settings.cache_clear()
    runner = CliRunner()

    result = runner.invoke(app, ["triage", "run"])
    assert result.exit_code == 1 and "no Anthropic API key" in result.stdout
    run = run_job("triage")
    assert run.status == "ok" and run.summary.startswith("skipped")

    llm, _ = _llm(news)
    tr.triage_news(news, llm)
    result = runner.invoke(
        app, ["triage", "list", "LT", "--days", "36500", "--min-importance", "1"]
    )
    assert result.exit_code == 0 and "order_win" in result.stdout and "About: L&T" in result.stdout
    result = runner.invoke(app, ["llm", "usage"])
    assert result.exit_code == 0 and "triage" in result.stdout and "2 calls" in result.stdout


def link_to_first(kwargs, story=None):
    """A fake model that says every later article reports the same event as the first one."""
    reply = answer_each(kwargs)
    first = reply.parsed_output.articles[0].id
    for item in reply.parsed_output.articles[1:]:
        item.same_story_as = story if story is not None else first
    return reply


@pytest.mark.db
def test_llm_links_reports_of_the_same_event(news):
    llm, _ = _llm(news, link_to_first)
    result = tr.triage_news(news, llm)
    assert (result.triaged, result.same_story, result.calls) == (4, 2, 2)
    for isin in (LT, KVB):
        rows = news.query(NewsTriage).filter_by(isin=isin).order_by(NewsTriage.document_id).all()
        first = next(r for r in rows if r.duplicate_of is None)
        copy = [r for r in rows if r.duplicate_of]
        assert len(copy) == 1 and copy[0].duplicate_of == first.document_id
        assert (copy[0].topic, copy[0].summary) == (first.topic, first.summary)  # one judgement


@pytest.mark.db
def test_links_to_earlier_reports_from_previous_runs(news):
    llm, _ = _llm(news)
    tr.triage_news(news, llm, symbol="LT")
    first = news.query(Document).filter(Document.title.like("L&T bags%")).one()
    later = Document(
        source="news:google",
        source_id="later-1",
        doc_type="news",
        title="Larsen wins two big contracts in Delhi, Andhra",
        published_at=first.published_at + timedelta(days=1),
        raw={},
    )
    news.add(later)
    news.flush()
    news.add(DocumentCompany(document_id=later.id, isin=LT))
    news.commit()

    def link_to_earlier(kwargs):
        prompt = kwargs["messages"][0]["content"]
        assert "<earlier>" in prompt and f"id {first.id} (21 Oct): L&T bags" in prompt
        return _single_link(kwargs, first.id)

    llm, _ = _llm(news, link_to_earlier)
    result = tr.triage_news(news, llm, symbol="LT")
    assert result.same_story == 1
    assert news.get(NewsTriage, (later.id, LT)).duplicate_of == first.id


def _single_link(kwargs, story):
    reply = answer_each(kwargs)
    for item in reply.parsed_output.articles:
        item.same_story_as = story
    return reply


@pytest.mark.db
def test_invalid_links_are_ignored(news):
    def bad_links(kwargs):
        reply = answer_each(kwargs)
        items = reply.parsed_output.articles
        items[0].same_story_as = items[-1].id  # a later article: not allowed
        items[-1].same_story_as = 999_999  # an id never shown
        return reply

    llm, _ = _llm(news, bad_links)
    result = tr.triage_news(news, llm)
    assert result.same_story == 0
    assert news.query(NewsTriage).filter(NewsTriage.duplicate_of.is_not(None)).count() == 0


@pytest.mark.db
def test_reset_forgets_results_for_one_stock_or_all(news):
    llm, _ = _llm(news)
    tr.triage_news(news, llm)
    assert tr.reset(news, "LT") == 2 and len(tr.pending(news)) == 2
    assert tr.reset(news) == 2 and len(tr.pending(news)) == 4
