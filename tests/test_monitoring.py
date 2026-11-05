from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import doc

from stock_news_analyzer import monitoring as mon
from stock_news_analyzer.models import Event, LlmCall, ResearchBrief
from stock_news_analyzer.sources.announcements import IST

LT = "INE018A01030"
TODAY = date(2026, 11, 5)


def at(days_ago: int) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days_ago), time(10), tzinfo=IST)


def events(session, d, n, passed, version="events-4", found=None):
    """`n` events created `d` days ago, `passed` of them passing the QA check."""
    filing = doc(session, LT, at(d), "credit_rating", f"Filing {d}-{n}-{version}", "text")
    for i in range(n):
        session.add(
            Event(
                isin=LT,
                document_id=filing.id,
                published_at=at(d),
                event_type="capex",
                headline="h",
                sentiment="positive",
                importance=3,
                model="claude-haiku-5-5",
                prompt_version=version,
                created_at=at(d),
                qa_status="passed" if i < passed else "flagged",
                quote_found=i < (passed if found is None else found),
            )
        )
    session.commit()


@pytest.mark.db
def test_a_drop_beyond_chance_is_an_alert(loaded):  # noqa: F811
    for d in range(10, 34, 3):  # the 28 days before: 8 x 5 events, 90% passing
        events(loaded, d, 5, 5 if d % 2 else 4)
    events(loaded, 2, 8, 4, version="events-5")  # the last week: 50% on a new prompt
    events(loaded, 4, 8, 4, version="events-5")
    s = mon.status(loaded, mon.BY_ID["events.qa"], TODAY)
    assert s.alert and s.recent == 0.5 and s.base == pytest.approx(36 / 40)
    assert (s.recent_n, s.base_n) == (16, 40)
    assert "fell to 50% in the last 7 days (16 items) from 90%" in s.message
    groups = {r["group"] for r in mon.series(loaded, mon.BY_ID["events.qa"], 60, TODAY)}
    assert groups == {"events-4", "events-5"}  # the new prompt shows where it came from
    assert [a.monitor.id for a in mon.alerts(loaded, TODAY)][:1] == ["events.qa"]


@pytest.mark.db
def test_a_small_change_or_too_little_work_is_no_alert(loaded):  # noqa: F811
    for d in range(10, 34, 3):
        events(loaded, d, 5, 5 if d % 2 else 4)
    events(loaded, 2, 12, 10)  # 83%: a little lower, within chance
    s = mon.status(loaded, mon.BY_ID["events.qa"], TODAY)
    assert not s.alert and "within what chance explains" in s.message
    quiet = mon.status(loaded, mon.BY_ID["briefs.dropped"], TODAY)
    assert not quiet.alert and quiet.message == "not enough work yet to compare"


@pytest.mark.db
def test_lower_is_better_monitors(loaded):  # noqa: F811
    for d in range(10, 34, 2):
        for _ in range(4):
            loaded.add(
                LlmCall(
                    at=at(d),
                    task="triage",
                    model="claude-haiku-5-5",
                    ok=True,
                    cost_usd=Decimal("0.001"),
                )
            )
    for i in range(12):
        loaded.add(
            LlmCall(
                at=at(1),
                task="events",
                model="claude-haiku-5-5",
                ok=i % 2 == 0,
                error=None if i % 2 == 0 else "cut off",
                cost_usd=Decimal("0.002"),
            )
        )
    loaded.add(
        LlmCall(
            at=at(1), task="eval-draft", model="claude-opus-5-5", ok=False, cost_usd=Decimal("0.01")
        )
    )  # evals don't count as production work
    loaded.commit()
    s = mon.status(loaded, mon.BY_ID["ai.failures"], TODAY)
    assert s.alert and s.recent == 0.5 and s.base == 0 and "rose to 50%" in s.message
    spend = mon.spend(loaded, 40, TODAY)
    assert round(sum(r["cost_usd"] for r in spend), 3) == 0.082
    assert {r["task"] for r in spend} == {"triage", "events", "eval-draft"}


@pytest.mark.db
def test_briefs_with_parts_dropped(loaded):  # noqa: F811
    for i in range(3):
        loaded.add(
            ResearchBrief(
                isin=LT,
                created_at=at(1),
                model="claude-sonnet-5-5",
                facts=[],
                view={},
                dropped=["a number"] if i == 0 else [],
            )
        )
    loaded.commit()
    rows = mon.series(loaded, mon.BY_ID["briefs.dropped"], 10, TODAY)
    assert rows == [
        {"day": TODAY - timedelta(days=1), "group": "claude-sonnet-5-5", "passed": 1, "total": 3}
    ]


@pytest.mark.db
def test_alerts_reach_the_digest(loaded, monkeypatch):  # noqa: F811
    from stock_news_analyzer.agents import digest as dg

    for d in range(10, 34, 3):
        events(loaded, d, 5, 5)
    events(loaded, 2, 12, 3)
    until = datetime.combine(TODAY, time(8), tzinfo=IST)
    md = dg.build_digest(loaded, until - timedelta(days=1), until).markdown
    assert "## Agent quality" in md and "Events passing the QA check fell to 25%" in md
    monkeypatch.setattr(mon, "alerts", lambda *a, **k: [])
    assert (
        "## Agent quality" not in dg.build_digest(loaded, until - timedelta(days=1), until).markdown
    )


@pytest.mark.db
def test_every_monitor_query_runs(loaded):  # noqa: F811
    for m in mon.MONITORS:
        assert mon.series(loaded, m, 30, TODAY) == [] or m.id.startswith("events")
        assert mon.status(loaded, m, TODAY).message


@pytest.mark.db
def test_the_monitoring_page(loaded, test_database_url, monkeypatch, tmp_path):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    events(loaded, 2, 3, 3)
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at_ = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.monitoring_page()", default_timeout=30
    )
    at_.run()
    assert not at_.exception, at_.exception
    assert "No agent is doing worse" in at_.success[0].value
    assert len(at_.metric) == len(mon.MONITORS)
    get_settings.cache_clear()
