from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from test_prices import _load_series, _trading_days, watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import study
from stock_news_analyzer.models import (
    Deal,
    Document,
    DocumentCompany,
    Event,
    Order,
    QuarterlyResult,
)
from stock_news_analyzer.sources.announcements import IST

KVB = "INE036D01028"


@pytest.mark.parametrize(
    ("revenue", "now", "before", "kind"),
    [
        (0.10, 15, 20, "Results: revenue up, profit down"),
        (0.10, 30, 20, "Results: revenue up, profit up 20%+"),
        (0.10, 21, 20, "Results: revenue and profit up"),
        (-0.10, 25, 20, "Results: revenue down, profit up"),
        (-0.10, 15, 20, "Results: revenue and profit down"),
        (0.01, 20.1, 20, "Results: little change"),
        (0.10, -5, 20, "Results: swung to a loss"),
        (0.10, 5, -2, "Results: back to a profit"),
        (None, 25, 20, None),  # no revenue a year before: not a case
    ],
)
def test_results_kind(revenue, now, before, kind):
    assert study.results_kind(revenue, Decimal(now), Decimal(before)) == kind


def test_order_size():
    assert study.order_kind(0.08).startswith("Order win: large")
    assert study.order_kind(0.02).startswith("Order win: medium")
    assert study.order_kind(0.002).startswith("Order win: small")
    assert study.order_kind(None) == "Order win: size not given"


def test_summary_gives_median_middle_half_and_share_up():
    def case(kind, move):
        c = study.Case("Results", kind, KVB, "KARURVYSYA", datetime.now(IST), "")
        c.excess = {5: move}
        return c

    moves = [-0.02, 0.01, 0.03, 0.04, None]  # the last is too recent for 5 days
    rows = study.summarise([case("A", m) for m in moves] + [case("B", 0.01)], horizon=5)
    a = next(r for r in rows if r.kind == "A")
    assert (a.cases, a.waiting, a.up, a.few) == (4, 1, 0.75, True)
    assert a.median == pytest.approx(0.02)
    assert a.low < a.median < a.high
    assert [r.kind for r in rows] == ["A", "B"]  # most cases first


def _doc(session, key, when, doc_type="results"):
    doc = Document(
        source="test", source_id=key, doc_type=doc_type, title=key, published_at=when, raw={}
    )
    session.add(doc)
    session.flush()
    session.add(DocumentCompany(document_id=doc.id, isin=KVB))
    return doc


def _at(day, hour):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, tzinfo=IST)


@pytest.mark.db
def test_cases_from_results_orders_events_and_deals(watchlist):  # noqa: F811
    days = _trading_days(60)
    _load_series(watchlist, days, big_day=30)  # KVB beats the Nifty by 5% on day 30
    pr.compute_moves(watchlist)
    s = watchlist

    # Results for the June quarter, filed on the big day, against June a year before.
    for end, revenue, pat in (("2025-06-30", 100, 20), ("2026-06-30", 110, 15)):
        s.add(
            QuarterlyResult(
                isin=KVB,
                period="Q1 FY27" if end.startswith("2026") else "Q1 FY26",
                period_end=datetime.strptime(end, "%Y-%m-%d").date(),
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=Decimal(revenue),
                pat_cr=Decimal(pat),
                unit="crore",
                model="xbrl",
            )
        )
    assert days[30] - timedelta(days=100) < datetime(2026, 6, 30).date() < days[30]
    results_doc = _doc(s, "results", _at(days[30], 11))

    # An order worth Rs 60 cr after the close on day 10 (mid-June 2026). Only the quarter
    # reported by then counts: a year's revenue is 100 x 4, not the later 110 x 4.
    order_doc = _doc(s, "order", _at(days[10], 17), "order_win")
    s.add(
        Order(
            isin=KVB,
            document_id=order_doc.id,
            announced_at=order_doc.published_at,
            kind="order",
            client="A state road authority",
            client_type="government",
            geography="domestic",
            value_cr=Decimal(60),
            description="highway",
            model="test",
        )
    )

    # Events: one that counts, one routine, one the QA check failed.
    event_doc = _doc(s, "event", _at(days[20], 10), "other")
    for importance, qa_status, headline in (
        (4, "passed", "CFO resigns"),
        (2, "passed", "Routine appointment"),
        (5, "failed", "Misread filing"),
    ):
        s.add(
            Event(
                isin=KVB,
                document_id=event_doc.id,
                published_at=event_doc.published_at,
                event_type="management_change",
                headline=headline,
                sentiment="negative",
                importance=importance,
                qa_status=qa_status,
                model="test",
                prompt_version="1",
            )
        )
    s.add(
        Deal(
            kind="block",
            trade_date=days[40],
            symbol="KARURVYSYA",
            isin=KVB,
            client="A Fund",
            side="BUY",
            quantity=1_000_000,
            price=Decimal(250),
        )
    )
    s.commit()

    cases = {c.kind: c for c in study.all_cases(s)}
    assert set(cases) == {
        "Results: revenue up, profit down",
        "Order win: large (5%+ of a year's revenue)",
        "Management change: negative",
        "Block deal: buy",
    }
    results = cases["Results: revenue up, profit down"]
    assert results.document_id == results_doc.id and results.day0 == days[30]
    assert results.excess[1] == pytest.approx(0.05, abs=1e-3)  # the 5% day itself
    assert results.excess[20] is not None and results.sector_excess[1] is None  # no sector data
    assert "revenue +10%, profit -25%" in results.detail

    order = cases["Order win: large (5%+ of a year's revenue)"]
    assert order.day0 == days[11]  # filed after the close
    assert "Rs 60 cr (15.0% of a year's revenue)" in order.detail
    assert cases["Management change: negative"].detail == "CFO resigns"
    deal = cases["Block deal: buy"]
    assert deal.day0 == days[41] and "Rs 25 cr" in deal.detail
    assert deal.excess[20] is None  # 20 days haven't passed yet

    rows = study.summarise(list(cases.values()), horizon=1)
    assert [r.group for r in rows] == ["Results", "Order wins", "Events", "Deals"]
    assert rows[0].median == pytest.approx(0.05, abs=1e-3) and rows[0].up == 1.0


@pytest.mark.db
def test_cli_evidence(watchlist, test_database_url, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    days = _trading_days(40)
    _load_series(watchlist, days, big_day=30)
    pr.compute_moves(watchlist)
    watchlist.add(
        Deal(
            kind="block",
            trade_date=days[29],
            symbol="KARURVYSYA",
            isin=KVB,
            client="A Fund",
            side="SELL",
            quantity=1000,
            price=None,
        )
    )
    watchlist.commit()
    runner = CliRunner()
    result = runner.invoke(app, ["evidence", "--days", "1", "--kind", "block"])
    assert result.exit_code == 0, result.stdout
    assert "1 cases; moves against the Nifty 50 over 1 trading days" in result.stdout
    assert "Block deal: sell" in result.stdout and "+5.0%" in result.stdout  # day 30's jump
    assert runner.invoke(app, ["evidence", "--days", "3"]).exit_code == 1


def test_cases_grouped_by_the_size_of_the_move():
    def case(kind, symbol, move):
        c = study.Case("Order wins", kind, KVB, symbol, datetime.now(IST), "")
        c.excess = {5: move}
        return c

    cases = [
        case("Large", "LT", 0.003),
        case("Large", "LT", 0.004),
        case("Small", "BEL", 0.003),
        case("Large", "BEL", 0.06),
        case("Small", "LT", -0.07),
        case("Small", "LT", None),  # too recent: in no band
    ]
    bands = study.by_move(cases, horizon=5)
    assert [b.label for b in bands][:2] == ["−5% or worse", "−5% to −2%"]
    assert [b.label for b in bands][4:6] == ["−0.5% to 0%", "0% to +0.5%"]
    assert bands[-1].label == "+5% or better"
    small_up = bands[5]  # a +0.3% move: what lay behind it
    assert [c.symbol for c in small_up.cases] == ["LT", "LT", "BEL"]  # biggest first
    assert small_up.kinds == [("Large", 2, 3), ("Small", 1, 2)]  # 2 of Large's 3 cases
    assert small_up.stocks == [("LT", 2), ("BEL", 1)]
    assert [len(b.cases) for b in bands] == [1, 0, 0, 0, 0, 3, 0, 0, 0, 1]
