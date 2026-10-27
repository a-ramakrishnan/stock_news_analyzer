import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_concalls import LT, _llm
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import KVB, doc

from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import themes as th
from stock_news_analyzer.models import (
    CompanyPeer,
    Event,
    LlmCall,
    Order,
    PeerSignal,
    QuarterlyResult,
    ThemeTag,
)
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.ui import queries

MSUMI = "INE0FS801015"
NOW = datetime.now(IST).replace(microsecond=0)


def test_themes_file():
    themes = th.load_themes()
    assert "data_centres" in themes and themes["defence"]["name"] == "Defence"
    assert all(t["hint"] for t in themes.values())


def order(session, isin, when, value, description):
    d = doc(session, isin, when, "order_win", description, description)
    o = Order(
        isin=isin,
        document_id=d.id,
        announced_at=when,
        kind="order",
        client="A data centre developer",
        client_type="private",
        segment="buildings",
        geography="domestic",
        value_cr=Decimal(value),
        description=description,
        model="m",
    )
    session.add(o)
    session.commit()
    return o


def event(session, isin, when, headline, importance=3, event_type="capex"):
    d = doc(session, isin, when, "other", headline, headline)
    e = Event(
        isin=isin,
        document_id=d.id,
        published_at=when,
        event_type=event_type,
        headline=headline,
        sentiment="positive",
        importance=importance,
        quote="q",
        qa_status="passed",
        model="m",
        prompt_version="events-4",
    )
    session.add(e)
    session.commit()
    return e


def tagging(themes_by_word):
    """Tags each item with the themes whose word appears in its text."""

    def reply(kwargs):
        prompt = kwargs["messages"][0]["content"]
        items = re.findall(r'<item id="(\w+)" company="[^"]*">([^<]*)</item>', prompt)
        answer = th.TagAnswer(
            items=[
                th.ItemThemes(
                    id=key,
                    themes=[t for w, ts in themes_by_word.items() if w in text.lower() for t in ts],
                )
                for key, text in items
            ]
        )
        return SimpleNamespace(usage=usage(2000, 200), parsed_output=answer, stop_reason="end_turn")

    return reply


@pytest.fixture
def items(loaded):  # noqa: F811
    """An L&T data-centre order worth 2% of its revenue, a KVB data-centre loan push a month
    earlier, and an MSUMI event with no theme."""
    for i, end in enumerate((date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30))):
        loaded.add(
            QuarterlyResult(
                isin=LT,
                period=f"Q{i}",
                period_end=end,
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=Decimal(60000),
                unit="crore",
                as_written={},
                model="xbrl",
            )
        )
    loaded.add(
        QuarterlyResult(
            isin=LT,
            period="Q3",
            period_end=date(2026, 9, 30),
            months=3,
            basis="consolidated",
            primary=True,
            revenue_cr=Decimal(60000),
            unit="crore",
            as_written={},
            model="xbrl",
        )
    )
    loaded.commit()
    lt = order(loaded, LT, NOW - timedelta(days=2), 5000, "Hyperscale data centre campus in Mumbai")
    kvb = event(loaded, KVB, NOW - timedelta(days=30), "Loans to data centre developers grow")
    event(loaded, KVB, NOW - timedelta(days=60), "Data centre lending book doubles")
    msumi = event(loaded, MSUMI, NOW - timedelta(days=5), "New CFO appointed", importance=5)
    return lt, kvb, msumi


@pytest.mark.db
def test_items_are_tagged_once_and_unknown_themes_dropped(items):
    lt, kvb, msumi = items
    session = _session(items)
    pending = th.pending(session, date(2025, 1, 1))
    assert {f"O{lt.id}", f"E{kvb.id}", f"E{msumi.id}"} <= {p.key for p in pending}
    assert len(pending) == 4
    llm, client = _llm(
        session, tagging({"data centre": ["data_centres", "buildings_factories", "made_up"]})
    )
    result = th.run(session, llm, since=date(2025, 1, 1))
    assert client.requests[0]["model"] == "claude-haiku-5-5"
    assert (result.items, result.tags, result.untagged, result.calls) == (4, 6, 1, 1)
    tags = {(t.item_type, t.item_id, t.theme) for t in session.query(ThemeTag)}
    assert ("order", lt.id, "data_centres") in tags and ("event", msumi.id, "none") in tags
    assert not any(t[2] == "made_up" for t in tags)
    assert th.pending(session, date(2025, 1, 1)) == []
    assert session.query(LlmCall).filter_by(task="themes").count() == 1


def _session(items):
    from sqlalchemy.orm import object_session

    return object_session(items[0])


@pytest.mark.db
def test_read_across_to_peers_and_theme_companies(items):
    lt, kvb, msumi = items
    session = _session(items)
    session.add(CompanyPeer(isin=LT, peer_isin=MSUMI, source="industry"))
    session.commit()
    llm, _ = _llm(session, tagging({"data centre": ["data_centres"]}))
    result = th.run(session, llm, since=date(2025, 1, 1))
    # The L&T order (Rs 5,000 crore, 2% of a Rs 2.4 lakh crore year) reads across to its
    # approved peer MSUMI and to KVB, which has data centres among its core themes.
    signals = {(s.target_isin, s.relation) for s in session.query(PeerSignal)}
    assert signals == {(MSUMI, "peer"), (KVB, "theme:data_centres")}
    assert result.signals == 2
    # MSUMI's important event has no theme and no peers: nothing reads across from it.
    assert th.read_across(session, date(2025, 1, 1)) == 0
    rows = queries.read_across(session)
    assert set(rows["for"]) == {"MSUMI", "KARURVYSYA"}
    md = dg.build_digest(session, NOW - timedelta(hours=1), datetime.now(IST)).markdown
    assert "## Read-across" in md and "For KARURVYSYA (data centres)" in md


@pytest.mark.db
def test_theme_strength(items):
    session = _session(items)
    llm, _ = _llm(session, tagging({"data centre": ["data_centres"]}))
    th.run(session, llm, since=date(2025, 1, 1))
    top = th.summary(session)[0]
    assert top["theme"] == "data_centres" and top["items"] == 3 and top["before"] == 0
    assert top["companies"] == ["KARURVYSYA", "LT"] and top["order_value_cr"] == 5000
    months = th.monthly(session, "data_centres")
    assert sum(m["items"] for m in months) == 3
    table = queries.themes(session)
    assert table.iloc[0]["theme"] == "Data centres"
    detail_months, detail_items = queries.theme_detail(session, "data_centres")
    assert len(detail_items) == 3
    assert th.reset(session) > 0 and session.query(ThemeTag).count() == 0


@pytest.mark.db
def test_broad_themes_and_single_items_dont_read_across(items):
    lt, kvb, msumi = items
    session = _session(items)
    # MSUMI has one data-centre item (not a core theme); everything is also "exports".
    event(session, MSUMI, NOW - timedelta(days=20), "Wiring for a data centre client")
    llm, _ = _llm(
        session, tagging({"data centre": ["data_centres", "exports_overseas"], "cfo": []})
    )
    th.run(session, llm, since=date(2025, 1, 1))
    core = th.core_themes(session)
    assert core[KVB] == ["data_centres"]  # exports_overseas allows no read-across
    assert core.get(MSUMI, []) == []  # one data-centre item of two: not enough items
    targets = {(s.target_isin, s.relation) for s in session.query(PeerSignal)}
    assert targets == {(KVB, "theme:data_centres")}
    # The same order filed twice reads across once.
    dup = order(session, LT, lt.announced_at + timedelta(minutes=5), 5000, "Hyperscale data centre")
    llm, _ = _llm(session, tagging({"data centre": ["data_centres"]}))
    th.run(session, llm, since=date(2025, 1, 1))
    assert session.query(PeerSignal).count() == 1 and dup.id
    assert th.reset(session, signals_only=True) == 1 and session.query(ThemeTag).count() > 0
