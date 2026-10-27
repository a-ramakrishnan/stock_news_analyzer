from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from test_concalls import LT
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import doc

from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import redflags as rf
from stock_news_analyzer.models import Event, QuarterlyResult, RedFlag
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.ui import queries

WHEN = datetime(2026, 10, 20, 17, 5, tzinfo=IST)


def event(event_type="management_change", **kw):
    fields = dict(
        event_type=event_type,
        headline="Something happened",
        sentiment="neutral",
        importance=3,
        role=None,
        person=None,
        action=None,
        counterparty=None,
        rating_to=None,
        stake_pct=None,
        materiality=None,
        value_cr=None,
        published_at=WHEN,
    )
    return Event(**{**fields, **kw})


def flag(e):
    f = rf.judge(e, "XYZ")
    return (f.kind, f.severity) if f else None


# --- the rules --------------------------------------------------------------------------


def test_management_exits():
    assert flag(event(role="Statutory Auditor", action="resigned")) == ("auditor_exit", "high")
    assert flag(event(role="Internal Auditor", action="resigned")) == ("auditor_exit", "medium")
    assert flag(event(role="Secretarial Auditor", action="appointed")) is None
    assert flag(event(role="MD and CEO", action="sought early retirement")) == ("key_exit", "high")
    assert flag(event(role="Chief Financial Officer", action="resigned")) == ("key_exit", "high")
    assert flag(event(role="CFO", action="ceased, redesignated Deputy CFO")) == (
        "key_exit",
        "medium",
    )
    assert flag(event(role="Chief Financial Officer", action="appointed")) is None
    assert flag(event(role="Independent Director", action="resigned")) == (
        "independent_director_exit",
        "medium",
    )
    assert flag(event(role="Independent Director", action="will cease at end of term")) is None
    assert flag(event(role="COO", action="ceased on completion of tenure")) is None
    assert flag(event(role="Senior Management Personnel", action="resigned")) is None


def test_ratings_pledges_and_selling():
    assert flag(event("credit_rating", action="downgraded", rating_to="CARE BBB")) == (
        "downgrade",
        "high",
    )
    assert flag(event("credit_rating", action="outlook revised", rating_to="AA-; Negative")) == (
        "negative_outlook",
        "medium",
    )
    assert flag(event("credit_rating", action="reaffirmed", rating_to="AAA; Stable")) is None
    assert flag(event("credit_rating", action="upgraded", rating_to="A1+")) is None
    assert flag(event("promoter_action", action="pledge invoked")) == ("pledge", "high")
    assert flag(event("promoter_action", action="pledge created")) == ("pledge", "medium")
    assert flag(event("promoter_action", action="pledge released")) is None
    # A fund trimming its stake is low; a promoter selling is medium.
    assert flag(event("promoter_action", action="sold shares", stake_pct=1.48)) == (
        "holder_selling",
        "low",
    )
    assert flag(event("promoter_action", action="sold shares", stake_pct=0.2)) is None
    promoter = event("promoter_action", action="sold shares", headline="Promoter sold 20,00,000")
    assert flag(promoter) == ("promoter_selling", "medium")
    assert flag(event("promoter_action", action="reclassification to public")) is None


def test_penalties_by_size_and_disruptions():
    legal = "legal_regulatory"
    assert flag(event(legal, sentiment="negative", materiality=0.03)) == ("legal", "high")
    assert flag(event(legal, sentiment="negative", materiality=0.002)) == ("legal", "medium")
    assert flag(event(legal, sentiment="negative", materiality=0.00001)) == ("legal", "low")
    sebi = event(legal, sentiment="negative", materiality=0.00001, counterparty="SEBI")
    assert flag(sebi) == ("regulator", "medium")
    assert flag(event(legal, sentiment="positive", materiality=0.5)) is None  # a stay won
    assert flag(event(legal, sentiment="mixed", importance=4)) == ("legal", "medium")
    assert flag(event(legal, sentiment="mixed", importance=3)) == ("legal", "low")  # adjourned
    assert flag(event("disruption", sentiment="negative", importance=4)) == ("disruption", "high")
    assert flag(event("disruption", sentiment="neutral", importance=4)) is None
    assert flag(event("capex", sentiment="negative", importance=5)) is None


# --- raising and showing ---------------------------------------------------------------


def stored(session, **kw):
    n = session.query(Event).count()  # a filing a minute apart each (its id comes from the time)
    d = doc(session, LT, WHEN + timedelta(minutes=n), "other", "A management change", "text")
    kw = {"qa_status": "passed", **kw}
    e = event(isin=LT, document_id=d.id, quote="q", model="m", prompt_version="events-3", **kw)
    session.add(e)
    session.commit()
    return e


@pytest.mark.db
def test_scan_raises_each_flag_once(loaded):  # noqa: F811
    e = stored(loaded, role="Statutory Auditor", action="resigned", headline="Auditor quit")
    stored(loaded, role="CFO", action="resigned", headline="CFO quit", qa_status="failed")
    result = rf.scan(loaded, today=date(2026, 10, 27))
    assert result.raised == 1 and result.by_severity == {"high": 1}
    f = loaded.query(RedFlag).one()
    assert (f.kind, f.event_id, f.ref) == ("auditor_exit", e.id, f"event:{e.id}")
    assert f.flagged_on == WHEN.date()
    again = rf.scan(loaded, today=date(2026, 10, 27))
    assert again.raised == 0  # not again
    f.severity = "low"  # graded by an older rule: the next scan corrects it
    loaded.commit()
    assert rf.scan(loaded, today=date(2026, 10, 27)).regraded == 1
    assert f.severity == "high"
    assert [r["kind"] for r in queries.red_flags(loaded, days=3650)] == ["auditor exit"]
    rf.dismiss(loaded, f.id, "the new auditor is a big-four firm")
    assert queries.red_flags(loaded, days=3650) == []
    assert rf.open_flags(loaded, 3650, include_dismissed=True)[0][0].note.startswith("the new")


def quarter(session, end=date(2026, 6, 30)):
    session.add(
        QuarterlyResult(
            isin=LT,
            period="Q1 FY27",
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
    session.commit()


@pytest.mark.db
def test_results_past_the_deadline(loaded):  # noqa: F811
    quarter(loaded)  # Q1 FY27 read; Q2 FY27 (to 30 Sep) is due by 14 Nov
    assert rf.overdue_results(loaded, date(2026, 11, 14)) == []
    late = rf.overdue_results(loaded, date(2026, 11, 20))
    lt = [f for f in late if f.isin == LT]
    assert len(lt) == 1 and lt[0].severity == "medium" and lt[0].ref == "results:Q2 FY27"
    assert "due 14 Nov 2026" in lt[0].title
    assert rf.overdue_results(loaded, date(2026, 12, 20))[0].severity == "high"
    filed = datetime(2026, 11, 18, 18, 0, tzinfo=IST)
    doc(loaded, LT, filed, "results", "Financial results for the quarter", "results text")
    assert [f for f in rf.overdue_results(loaded, date(2026, 11, 20)) if f.isin == LT] == []


@pytest.mark.db
def test_digest_shows_recent_flags_only(loaded):  # noqa: F811
    stored(loaded, role="Statutory Auditor", action="resigned", headline="Auditor quit")
    old = stored(loaded, role="CFO", action="resigned", headline="Old CFO exit")
    old.published_at = WHEN - timedelta(days=200)
    loaded.commit()
    rf.scan(loaded, today=date(2026, 10, 27))
    for f in loaded.query(RedFlag):  # as if raised the morning after the filing
        f.created_at = WHEN + timedelta(hours=14)
    loaded.commit()
    md = dg.build_digest(loaded, WHEN, WHEN + timedelta(days=1)).markdown
    assert "## Red flags" in md
    assert "- **HIGH** 20 Oct: LT: auditor exit. Auditor quit" in md
    assert "Old CFO exit" not in md  # a flag about a filing months old: history, not news
