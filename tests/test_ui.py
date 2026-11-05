from datetime import date

import pytest
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.models import Run, StockMove
from stock_news_analyzer.ui import charts, queries

LT = "INE018A01030"


@pytest.mark.db
def test_watchlist_cards(loaded):  # noqa: F811
    cards = {c["symbol"]: c for c in queries.watchlist(loaded)}
    assert set(cards) == {"LT", "KARURVYSYA", "MSUMI"}
    lt = cards["LT"]
    assert not lt["owned"] and lt["sector_index"] == "Nifty Infrastructure"
    assert lt["date"] == date(2026, 10, 21)
    assert lt["stock_return"] == pytest.approx(-0.0071, abs=1e-4)
    assert lt["excess_return"] == pytest.approx(-0.0037, abs=1e-4)
    assert lt["close"] > 0


@pytest.mark.db
def test_market_strip(loaded):  # noqa: F811
    rows = {r["index"]: r for r in queries.market(loaded)}
    assert list(rows)[0] == "Nifty 50"
    assert {"Nifty Bank", "Nifty Infrastructure", "Nifty Auto"} <= set(rows)
    assert rows["Nifty 50"]["change"] == pytest.approx(-0.0034, abs=1e-4)


@pytest.mark.db
def test_performance_is_indexed_to_100(loaded):  # noqa: F811
    perf = queries.performance(loaded, LT, date(2026, 10, 1))
    days = [date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 21)]
    assert list(perf["date"]) == days
    assert perf["stock"].iloc[0] == 100 and perf["nifty"].iloc[0] == 100  # first day = base
    moves = {m.trade_date: m.stock_return for m in loaded.query(StockMove).filter_by(isin=LT)}
    expected = 100 * (1 + moves[days[1]]) * (1 + moves[days[2]])
    assert perf["stock"].iloc[-1] == pytest.approx(expected)
    assert queries.performance(loaded, LT, date(2030, 1, 1)).empty


@pytest.mark.db
def test_filings_dedupe_search_and_text(loaded):  # noqa: F811
    both = queries.filings(loaded, isin=LT, doc_types=["order_win"])
    assert sorted(both["exchange"]) == ["BSE", "NSE"]  # one order win, filed on both
    once = queries.filings(loaded, isin=LT, doc_types=["order_win"], dedupe=True)
    assert list(once["exchange"]) == ["BSE"]
    assert queries.filings(loaded, search="no such words anywhere").empty
    assert queries.filings(loaded, since=date(2026, 10, 21))["published"].min() >= (
        once["published"].iloc[0].replace(hour=0, minute=0)
    )
    assert "order_win" in queries.doc_types(loaded) and "news" not in queries.doc_types(loaded)
    assert isinstance(queries.document_text(loaded, int(once["id"].iloc[0])), str)


@pytest.mark.db
def test_news_and_labels(loaded):  # noqa: F811
    articles = queries.news(loaded, isin=LT)
    assert not articles.empty and articles["url"].str.startswith("http").all()
    assert queries.news(loaded, search="zzzz").empty
    lb = queries.labels(loaded, LT)
    assert (lb["type"] != "news").all()
    assert len(queries.labels(loaded, LT, news_too=True)) > len(lb)


@pytest.mark.db
def test_event_study_counts_bse_and_nse_copies_once(loaded):  # noqa: F811
    study = queries.event_study(loaded, LT).set_index("type")
    assert study.loc["order_win", "events"] == 1
    assert study.loc["order_win", "avg_1d"] == pytest.approx(-0.0037, abs=1e-4)
    assert study.loc["order_win", "n_20d"] == 0  # not 20 trading days old yet


@pytest.mark.db
def test_system_queries(loaded, tmp_path):  # noqa: F811
    from datetime import UTC, datetime

    loaded.add(
        Run(
            job="news",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status="ok",
            summary="3 new articles",
        )
    )
    loaded.commit()
    last = queries.last_runs(loaded)
    assert last["news"]["summary"] == "3 new articles" and last["filings"] is None
    assert queries.runs(loaded).iloc[0]["job"] == "news"
    counts = queries.data_counts(loaded)
    assert counts["trading days"] == 3 and counts["companies"] > 0
    assert queries.latest_digest(tmp_path) is None
    (tmp_path / "digests").mkdir()
    (tmp_path / "digests" / "2026-10-21-0800.md").write_text("# old")
    (tmp_path / "digests" / "2026-10-22-0800.md").write_text("# new")
    assert queries.latest_digest(tmp_path) == ("2026-10-22-0800.md", "# new")


@pytest.mark.db
def test_charts_build(loaded):  # noqa: F811
    perf = queries.performance(loaded, LT, date(2026, 10, 1))
    events = queries.labels(loaded, LT)
    fig = charts.performance_chart(perf, "LT", "Nifty Infrastructure", events)
    names = [t.name for t in fig.data]
    assert names[:3] == ["Nifty 50", "Nifty Infrastructure", "LT"] and "Filing" in names
    assert len(fig.layout.yaxis.title.text) > 0  # one axis, labelled
    assert charts.excess_bars(perf, dark=True).data[0].type == "bar"
    study = queries.event_study(loaded)
    assert len(charts.event_study_chart(study).data) == 3  # 1, 5 and 20 days
    assert charts.performance_chart(perf.iloc[0:0], "LT", None).data == ()


@pytest.mark.db
@pytest.mark.parametrize(
    "page",
    [
        "today_page",
        "portfolio_page",
        "flags_page",
        "stock_page_body",
        "research_page",
        "weeks_page",
        "filings_page",
        "news_page",
        "themes_page",
        "ask_page",
        "moves_page",
        "evidence_page",
        "manage_page",
        "settings_page",
        "system_page",
        "agents_page",
        "guide_page",
    ],
)
def test_every_page_renders(loaded, test_database_url, monkeypatch, tmp_path, page):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from stock_news_analyzer.config import get_settings

    get_settings.cache_clear()
    at = AppTest.from_string(
        f"from stock_news_analyzer.ui import app\napp.{page}()", default_timeout=30
    )
    at.query_params["symbol"] = "LT"
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value in {
        "Today",
        "Portfolio",
        "Red flags",
        "Larsen & Toubro Limited",
        "Research brief",
        "Week by week",
        "Filings",
        "News",
        "Themes",
        "Ask",
        "What moves the stock",
        "What news does to prices",
        "Manage stocks",
        "Settings",
        "System",
        "Agent map",
        "Guide",
    }


def test_main_registers_every_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(
        "from unittest import mock\n"
        "import streamlit as st\n"
        "from stock_news_analyzer.ui import app\n"
        "with mock.patch.object(st, 'navigation') as nav, "
        "mock.patch.object(app, 'setup_needed', return_value=False):\n"
        "    app.main()\n"
        "groups = nav.call_args.args[0]\n"
        "st.markdown(','.join(groups))\n"
        "st.markdown(str(sum(len(p) for p in groups.values())))\n"
    )
    at.run()
    assert not at.exception and at.markdown[-1].value == "17"
    assert at.markdown[-2].value == "Today,Research,Library,Set up,Help"


def test_guide_sections():
    from stock_news_analyzer.ui import guide

    parts = guide.sections()
    assert list(parts)[:3] == ["What it is", "Getting started", "A daily routine"]
    assert "Settings" in parts
    assert all(body for body in parts.values())
    slugs = [guide.slug(t) for t in parts]
    assert len(set(slugs)) == len(slugs) and "keeping-it-running" in slugs
    assert "what-news-does-to-prices" in slugs  # the evidence page's help link
    assert "week-by-week" in slugs and "portfolio" in slugs and "research-brief" in slugs
    # Every page's help link points at a section that exists.
    app = (guide.GUIDE_FILE.parent / "app.py").read_text()
    import re

    linked = set(re.findall(r'help_link\("([a-z-]+)"\)', app)) | {"the-pages"}
    assert linked <= set(slugs), linked - set(slugs)


def test_guide_opens_at_the_linked_section():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string("from stock_news_analyzer.ui import app\napp.guide_page()")
    at.query_params["section"] = "words-used"
    at.run()
    assert not at.exception
    opened = [e.label for e in at.expander if e.proto.expanded]
    assert opened == ["Words used"] and len(at.expander) == 15
    assert any("Book-to-bill" in m.value for m in at.markdown)


@pytest.mark.db
def test_flag_table_dismiss_and_restore(loaded):  # noqa: F811
    from datetime import date

    from stock_news_analyzer.agents import redflags
    from stock_news_analyzer.models import RedFlag

    flag = RedFlag(
        isin=LT,
        kind="auditor_exit",
        severity="high",
        title="LT: auditor resigned",
        detail="mid-term",
        flagged_on=date.today(),
        ref="test:1",
    )
    loaded.add(flag)
    loaded.commit()
    table = queries.flag_table(loaded)
    row = table[table["id"] == flag.id].iloc[0]
    assert row["title"] == "LT: auditor resigned (mid-term)" and row["status"] == "open"
    redflags.dismiss(loaded, flag.id, "planned rotation")
    assert flag.id not in set(queries.flag_table(loaded)["id"])
    shown = queries.flag_table(loaded, include_dismissed=True)
    assert shown[shown["id"] == flag.id].iloc[0][["status", "note"]].tolist() == [
        "dismissed",
        "planned rotation",
    ]
    redflags.restore(loaded, flag.id)
    assert flag.id in set(queries.flag_table(loaded)["id"])


@pytest.mark.db
def test_a_job_already_running_is_seen(loaded):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from stock_news_analyzer.agents import orchestrator as orch
    from stock_news_analyzer.models import Run

    loaded.add(Run(job="news", started_at=datetime.now(UTC), status="running"))
    loaded.add(
        Run(job="prices", started_at=datetime.now(UTC) - timedelta(hours=5), status="running")
    )
    loaded.commit()
    assert orch.running(loaded, "news") is not None
    assert orch.running(loaded, "prices") is None  # cut off long ago by a restart
    assert orch.running(loaded, "filings") is None


def test_a_new_copy_opens_on_the_setup():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(
        "from unittest import mock\n"
        "import streamlit as st\n"
        "from stock_news_analyzer.ui import app\n"
        "with mock.patch.object(st, 'navigation') as nav, "
        "mock.patch.object(app, 'setup_needed', return_value=True):\n"
        "    app.main()\n"
        "st.markdown(','.join(p.title for p in nav.call_args.args[0]))\n"
    )
    at.run()
    assert not at.exception and at.markdown[-1].value == "Setup,Guide"


@pytest.mark.db
@pytest.mark.parametrize("step", [0, 1, 2, 3])
def test_every_setup_step_renders(loaded, test_database_url, monkeypatch, tmp_path, step):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from stock_news_analyzer.config import get_settings

    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.setup_page()", default_timeout=30
    )
    at.session_state["setup_step"] = step
    at.run()
    assert not at.exception, at.exception
    assert (
        at.title[0].value
        == [
            "Welcome to Stock News Analyzer",
            "AI features",
            "Your stocks",
            "History",
        ][step]
    )


@pytest.mark.db
def test_agent_map_shows_each_part_live(loaded):  # noqa: F811
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from stock_news_analyzer.models import LlmCall
    from stock_news_analyzer.ui import agent_map

    now = datetime.now(UTC)
    loaded.add_all(
        [
            Run(job="filings", started_at=now - timedelta(minutes=2), status="running"),
            Run(
                job="news",
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(hours=1) + timedelta(seconds=40),
                status="error",
                error="HTTP 403 from a feed",
            ),
            Run(
                job="triage",
                started_at=now - timedelta(minutes=30),
                finished_at=now - timedelta(minutes=29),
                status="ok",
                summary="12 articles triaged",
            ),
            LlmCall(
                at=now - timedelta(minutes=29, seconds=30),  # during the triage run
                task="triage",
                model="claude-haiku-5-5",
                input_tokens=100,
                output_tokens=10,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=Decimal("0.0020"),
                ok=True,
            ),
        ]
    )
    loaded.commit()
    status = queries.agent_status(loaded)
    assert status["jobs"]["filings"]["status"] == "running"
    assert status["jobs"]["news"]["status"] == "error"
    assert status["ai_today"]["triage"]["calls"] == 1
    assert status["runs_24h"] == 3 and status["errors_24h"] == 1

    events = queries.agent_events(loaded, days=7)
    assert [e["job"] for e in events] == ["news", "triage", "filings"]
    triage = events[1]
    assert triage["status"] == "ok" and triage["summary"] == "12 articles triaged"
    assert triage["calls"] == 1 and triage["cost"] == pytest.approx(0.002)
    assert events[0]["error"] == "HTTP 403 from a feed"

    replay = agent_map.render(status, app_palette(), False, events, mode="replay")
    assert 'id="play"' in replay and 'id="scrub"' in replay and '"mode": "replay"' in replay
    assert "12 articles triaged" in replay  # the runs travel with the page
    assert "</script>" not in replay.split('id="data"')[1].split("</script>")[0]
    assert 'id="job-triage"' in replay and 'id="tool-anthropic"' in replay
    assert "Turns the outside world into data" in replay  # each layer explains itself

    page = agent_map.render(status, app_palette(), False, events, mode="live")
    assert 'id="play"' not in page and "Today's action" in page
    assert 'class="chip running"' in page and "running for 2 min" in page
    assert 'class="chip error" id="job-news" data-job="news" title="HTTP 403 from a feed"' in page
    assert "1 AI call today · $0.00" in page
    for layer in ("Perceive", "Plan", "Think", "Remember", "Act", "Guardrails", "Observe"):
        assert layer in page
    assert "$" + "bg" not in page  # every colour filled in


def app_palette() -> dict:
    """The dashboard's light colours, without importing the Streamlit app."""
    import ast
    from pathlib import Path

    source = (Path(queries.__file__).parent / "app.py").read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PALETTE":
            light = node.value.values[0]
            return {k.arg: ast.literal_eval(k.value) for k in light.keywords}
    raise AssertionError("PALETTE not found")
