import re
from datetime import date
from types import SimpleNamespace

import pytest
from test_llm import FakeAnthropic, settings, usage
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import explain as ex
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import Document, LlmCall, MoveExplanation, NewsTriage, StockMove

LT = "INE018A01030"
DAY = date(2026, 10, 21)


@pytest.fixture
def unusual(loaded):  # noqa: F811
    """L&T's 21 Oct move marked unusual (3 days of prices are too few to compute it)."""
    move = loaded.get(StockMove, (LT, DAY))
    move.unusual, move.zscore = True, 3.2
    loaded.commit()
    return loaded


def reply_with(cause="order", confidence="high", evidence=None):
    def reply(kwargs):
        prompt = kwargs["messages"][0]["content"]
        ids = [int(i) for i in re.findall(r'<document id="(\d+)" kind="filing"', prompt)]
        answer = ex.Explanation(
            cause=cause,
            confidence=confidence,
            explanation="L&T filed large orders the same morning; the stock beat the Nifty.",
            evidence=evidence if evidence is not None else ids[:1] + [999_999],
        )
        return SimpleNamespace(usage=usage(4000, 300), parsed_output=answer, stop_reason="end_turn")

    return reply


def _llm(session, reply, **kw):
    client = FakeAnthropic(reply)
    return LLM(session, client=client, settings=settings(**kw)), client


@pytest.mark.db
def test_explains_an_unusual_day_from_its_filings_and_news(unusual):
    assert [(m.trade_date, c.nse_symbol) for m, c in ex.pending(unusual)] == [(DAY, "LT")]
    llm, client = _llm(unusual, reply_with())
    result = ex.explain_moves(unusual, llm, model="claude-sonnet-5-5")
    assert (result.explained, result.calls, result.errors) == (1, 1, [])

    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["output_config"] == {"effort": "medium"}
    prompt = request["messages"][0]["content"]
    assert "Unusual day: Wed 21 Oct 2026" in prompt and "z-score +3.2" in prompt
    assert 'kind="filing" type="order_win"' in prompt and "on the day" in prompt
    assert "L&T bags 'large' orders" in prompt  # the day's news

    row = unusual.get(MoveExplanation, (LT, DAY))
    assert (row.cause, row.confidence) == ("order", "high")
    order = unusual.query(Document).filter_by(doc_type="order_win", source="bse").one()
    assert row.evidence == [order.id]  # the invented id 999999 was dropped
    assert unusual.query(LlmCall).filter_by(task="explain").count() == 1
    assert ex.pending(unusual) == []


@pytest.mark.db
def test_off_topic_and_repeated_news_are_left_out_of_the_prompt(unusual):
    article = unusual.query(Document).filter(Document.title.like("L&T bags%")).one()
    unusual.add(
        NewsTriage(
            document_id=article.id,
            isin=LT,
            relevant=False,
            topic="other",
            sentiment="neutral",
            importance=1,
            summary="x",
        )
    )
    unusual.commit()
    llm, client = _llm(unusual, reply_with())
    ex.explain_moves(unusual, llm)
    assert "L&T bags" not in client.requests[0]["messages"][0]["content"]


@pytest.mark.db
def test_unexplained_days_keep_no_evidence_and_dates_filter(unusual):
    llm, client = _llm(unusual, reply_with(cause="unexplained", confidence="low"))
    assert ex.explain_moves(unusual, llm, until=date(2026, 10, 20)).explained == 0
    assert client.requests == []  # outside the window
    ex.explain_moves(unusual, llm, since=DAY)
    assert unusual.get(MoveExplanation, (LT, DAY)).evidence == []
    assert ex.reset(unusual, "LT") == 1 and len(ex.pending(unusual)) == 1


@pytest.mark.db
def test_failures_and_budget_leave_days_pending(unusual):
    def refused(_kw):
        return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="refusal")

    llm, _ = _llm(unusual, refused)
    result = ex.explain_moves(unusual, llm)
    assert result.explained == 0 and "declined" in result.errors[0]
    llm, client = _llm(unusual, reply_with(), llm_monthly_budget_usd=0.0)
    result = ex.explain_moves(unusual, llm)
    assert "budget" in result.errors[0] and client.requests == []
    assert len(ex.pending(unusual)) == 1


@pytest.mark.db
def test_explanations_reach_digest_dashboard_and_cli(unusual, test_database_url, monkeypatch):
    from datetime import datetime

    from typer.testing import CliRunner

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.sources.announcements import IST
    from stock_news_analyzer.ui import queries

    llm, _ = _llm(unusual, reply_with())
    ex.explain_moves(unusual, llm)

    md = build_digest(
        unusual, datetime(2026, 10, 15, tzinfo=IST), datetime(2026, 10, 22, 8, tzinfo=IST)
    ).markdown
    assert "Likely cause (order, high confidence): L&T filed large orders" in md
    assert "- LT 21 Oct: -0.37% vs Nifty 50 (order)" in md

    days = queries.unusual_days(unusual, LT)
    assert list(days["cause"]) == ["order"] and "L&T Wins" in days["evidence"][0]
    perf = queries.performance(unusual, LT, date(2026, 10, 1))
    assert perf.loc[perf["date"] == DAY, "cause"].item() == "order"
    assert {c["symbol"]: c["cause"] for c in queries.watchlist(unusual)}["LT"] == "order"

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["explain", "list", "LT", "--days", "36500"])
    assert result.exit_code == 0 and "order, high confidence" in result.stdout
    assert "#" in result.stdout  # the evidence documents are listed


@pytest.mark.db
def test_chart_hover_and_scheduled_job(unusual, test_database_url, monkeypatch):
    from stock_news_analyzer.agents.orchestrator import run_job
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.ui import charts, queries

    llm, _ = _llm(unusual, reply_with())
    ex.explain_moves(unusual, llm)
    perf = queries.performance(unusual, LT, date(2026, 10, 1))
    fig = charts.performance_chart(perf, "LT", "Nifty Infrastructure")
    marker = next(t for t in fig.data if t.name == "Unusual day")
    assert "order: L&T filed large orders" in marker.customdata[0][2]

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    run = run_job("explain")
    assert run.status == "ok" and run.summary.startswith("skipped")


@pytest.mark.db
def test_prompt_has_deals_and_peer_moves(unusual):
    from datetime import datetime

    from test_deals import FakeNSE

    from stock_news_analyzer.agents import deals as dl
    from stock_news_analyzer.agents import watchlist as wl
    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.models import Company
    from stock_news_analyzer.sources.announcements import IST

    dl.collect(unusual, FakeNSE(), date(2026, 10, 1), date(2026, 10, 21))
    lt = unusual.get(Company, LT)
    llm, client = _llm(unusual, reply_with())

    # Without approved peers: the largest companies in L&T's NSE industry, if any traded.
    ex.explain_moves(unusual, llm)
    prompt = client.requests[0]["messages"][0]["content"]
    assert "Bulk and block deals (1, from two sessions before to the day):" in prompt
    assert "(on the day) block: EXAMPLE PENSION FUND buys 1,500,000 shares at Rs 3,640.00" in prompt
    assert "of the day's volume" in prompt and "Peers on the day" in prompt

    # Peers with prices in the test files (in real use you would pick construction companies).
    assert wl.set_peers(unusual, lt, ["KARURVYSYA", "MSUMI", "NOSUCH"]) == ["NOSUCH"]
    peers, source = wl.peers_for(unusual, lt)
    assert source == "approved" and {p.nse_symbol for p in peers} == {"KARURVYSYA", "MSUMI"}
    ex.reset(unusual)
    ex.explain_moves(unusual, llm)
    prompt = client.requests[1]["messages"][0]["content"]
    assert "Peers on the day (you chose): KARURVYSYA " in prompt and "; average " in prompt

    md = build_digest(
        unusual, datetime(2026, 10, 15, tzinfo=IST), datetime(2026, 10, 22, 8, tzinfo=IST)
    ).markdown
    assert "**Bulk/block deals (1):**" in md and "EXAMPLE PENSION FUND buys 1,500,000" in md


@pytest.mark.db
def test_redo_only_unexplained_days(unusual):
    llm, _ = _llm(unusual, reply_with(cause="unexplained", confidence="low"))
    ex.explain_moves(unusual, llm)
    assert ex.reset(unusual, only_unexplained=True, since=date(2026, 10, 22)) == 0  # outside
    assert ex.reset(unusual, only_unexplained=True) == 1
    llm, _ = _llm(unusual, reply_with())
    ex.explain_moves(unusual, llm)
    assert ex.reset(unusual, only_unexplained=True) == 0  # now explained: kept
