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
    assert lt["owned"] and lt["sector_index"] == "Nifty Infrastructure"
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
        "stock_page_body",
        "filings_page",
        "news_page",
        "themes_page",
        "moves_page",
        "manage_page",
        "system_page",
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
        "Larsen & Toubro Limited",
        "Filings",
        "News",
        "Themes",
        "What moves the stock",
        "Manage stocks",
        "System",
    }


def test_main_registers_every_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(
        "from unittest import mock\n"
        "import streamlit as st\n"
        "from stock_news_analyzer.ui import app\n"
        "with mock.patch.object(st, 'navigation') as nav:\n"
        "    app.main()\n"
        "st.markdown(str(len(nav.call_args.args[0])))\n"
    )
    at.run()
    assert not at.exception and at.markdown[-1].value == "8"
