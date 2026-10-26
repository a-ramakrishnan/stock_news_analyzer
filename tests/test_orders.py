from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_concalls import LT, _llm
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import concalls as cc
from stock_news_analyzer.agents import orders as ob
from stock_news_analyzer.models import (
    Document,
    DocumentCompany,
    LlmCall,
    Order,
    OrderBookSnapshot,
    OrderFiling,
)
from stock_news_analyzer.sources.announcements import IST

KVB = "INE036D01028"
ORDER_TEXT = (
    "Larsen & Toubro has won large orders for a metro line in New Delhi from DMRC and a "
    "highway in Andhra Pradesh. *Large orders are valued between Rs 2,500 crore and Rs 5,000 "
    "crore. Execution over 36 months."
)


def test_quarter_of():
    assert cc.quarter_of(date(2026, 8, 15)) == "Q2 FY27"
    assert cc.quarter_of(date(2026, 4, 1)) == "Q1 FY27"
    assert cc.quarter_of(date(2027, 3, 31)) == "Q4 FY27"
    assert cc.quarter_of(date(2026, 12, 1)) == "Q3 FY27"


@pytest.fixture
def filings(loaded):  # noqa: F811
    """The fixture's L&T order win, filed on BSE and NSE, with the order letter's text."""
    for doc in loaded.query(Document).filter_by(doc_type="order_win"):
        doc.text, doc.text_status = ORDER_TEXT, "ok"
    loaded.commit()
    return loaded


def doc(session, isin, when, doc_type, title, text):
    d = Document(
        source="bse",
        source_id=f"{doc_type}-{isin}-{when:%Y%m%d%H%M}",
        doc_type=doc_type,
        title=title,
        subject=title,
        published_at=when,
        text=text,
        text_status="ok",
        raw={},
    )
    session.add(d)
    session.flush()
    session.add(DocumentCompany(document_id=d.id, isin=isin))
    session.commit()
    return d


def large_order(client="Delhi Metro Rail Corporation"):
    return ob.OrderItem(
        kind="order",
        client=client,
        client_type="government",
        segment="metro rail",
        geography="domestic",
        value_cr=None,
        value_low_cr=2500,
        value_high_cr=5000,
        value_as_written="Rs 2,500 crore and Rs 5,000 crore",
        size_class="large",
        execution_months=36,
        description="Metro line in New Delhi and a highway in Andhra Pradesh.",
    )


def reply(orders=None, is_order=True, book=None):
    """Answers extraction calls with `orders` for every filing, and order-book calls with
    `book` (order book, inflow, revenue as written)."""

    def answer(kwargs):
        prompt = kwargs["messages"][0]["content"]
        if kwargs["output_format"] is ob.ExtractAnswer:
            import re

            ids = [int(i) for i in re.findall(r'<filing id="(\d+)"', prompt)]
            parsed = ob.ExtractAnswer(
                filings=[
                    ob.FilingOrders(
                        id=i,
                        is_order_announcement=is_order,
                        orders=orders if orders is not None else [large_order()],
                    )
                    for i in ids
                ]
            )
        else:
            figures = book or {}

            def fig(name, value):
                written = figures.get(name)
                return ob.Figure(value_cr=value if written else None, as_written=written)

            parsed = ob.SnapshotAnswer(
                period_end="2026-09-30" if figures else None,
                order_book=fig("order_book", 650000),
                inflow=fig("inflow", 115000),
                revenue=fig("revenue", 67000),
                note="From the investor presentation." if figures else "No order book given.",
            )
        return SimpleNamespace(usage=usage(3000, 300), parsed_output=parsed, stop_reason="end_turn")

    return answer


@pytest.mark.db
def test_an_order_filed_on_both_exchanges_is_stored_once(filings):
    llm, client = _llm(filings, reply())
    result = ob.extract_orders(filings, llm)
    assert (result.orders, result.duplicates, result.errors) == (1, 1, [])
    assert client.requests[0]["model"] == "claude-haiku-5-5"
    order = filings.query(Order).one()
    assert (order.value_low_cr, order.value_high_cr, order.value_cr) == (2500, 5000, 3750)
    assert order.value_found and order.client_type == "government"
    assert order.execution_months == 36
    statuses = sorted(f.status for f in filings.query(OrderFiling))
    assert statuses == ["duplicate", "extracted"]
    assert ob.pending_filings(filings) == []
    assert filings.query(LlmCall).filter_by(task="orders").count() == 1


@pytest.mark.db
def test_size_classes_get_the_range_the_company_states_elsewhere(filings):
    llm, _ = _llm(filings, reply())
    ob.extract_orders(filings, llm)  # a "large" order, with its range in the footnote
    later = doc(
        filings,
        LT,
        datetime(2026, 11, 5, 9, 0, tzinfo=IST),
        "order_win",
        "L&T wins large order",
        "L&T has won a large order for a refinery.",
    )
    unpriced = large_order("Indian Oil")
    unpriced.value_low_cr = unpriced.value_high_cr = unpriced.value_as_written = None
    llm, _ = _llm(filings, reply(orders=[unpriced]))
    ob.extract_orders(filings, llm)
    order = filings.query(Order).filter_by(document_id=later.id).one()
    assert order.value_cr is None and order.size_class == "large"
    assert ob.apply_scales(filings) == 1
    filings.refresh(order)
    assert (order.value_low_cr, order.value_high_cr, order.value_cr) == (2500, 5000, 3750)
    assert "scale from" in order.value_as_written and not order.value_found
    assert ob.apply_scales(filings) == 0  # learned values are not a source for others


@pytest.mark.db
def test_not_an_order_and_waiting_for_pdfs(loaded):  # noqa: F811
    llm, client = _llm(loaded, reply())
    result = ob.extract_orders(loaded, llm)
    assert result.waiting == 2 and client.requests == []  # the fixture's PDFs not downloaded
    for d in loaded.query(Document).filter_by(doc_type="order_win"):
        d.text, d.text_status = "SEBI order in the matter of a former employee.", "ok"
    loaded.commit()
    llm, _ = _llm(loaded, reply(orders=[], is_order=False))
    result = ob.extract_orders(loaded, llm)
    assert result.orders == 0 and loaded.query(Order).count() == 0
    assert {f.status for f in loaded.query(OrderFiling)} == {"not_order"}


def _orders(session, n, isin=LT, when=datetime(2026, 8, 10, 10, 0, tzinfo=IST), value=1000):
    d = doc(session, isin, when, "order_win", f"Order {when:%d%m%H}", ORDER_TEXT)
    for i in range(n):
        session.add(
            Order(
                isin=isin,
                document_id=d.id,
                announced_at=when,
                kind="order",
                client=f"Client {i}",
                client_type="psu" if i == 0 else "private",
                geography="domestic",
                value_cr=Decimal(value),
                description="x",
                model="test",
            )
        )
    session.commit()


@pytest.mark.db
def test_order_book_read_once_a_quarter_best_document_first(filings):
    _orders(filings, 2)  # L&T becomes order-driven
    presentation = doc(
        filings,
        LT,
        datetime(2026, 10, 24, 18, 0, tzinfo=IST),
        "investor_presentation",
        "Investor presentation Q2 FY27",
        "Order book Rs 6,50,000 crore, up 15%. Order inflow Rs 1,15,000 crore. Revenue from "
        "operations Rs 67,000 crore. " * 10,
    )
    doc(
        filings,
        LT,
        datetime(2026, 10, 23, 18, 0, tzinfo=IST),
        "results",
        "Results Q2 FY27",
        "Revenue from operations 67,000. " * 30,
    )
    book = {
        "order_book": "Rs 6,50,000 crore",
        "inflow": "Rs 1,15,000 crore",
        "revenue": "Rs 99,999 crore",  # not in the text
    }
    llm, client = _llm(filings, reply(book=book))
    result = ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    assert (result.snapshots, result.calls) == (1, 1)
    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert "Quarter wanted: Q2 FY27" in request["messages"][0]["content"]
    assert 'kind="investor_presentation"' in request["messages"][0]["content"]  # tried first
    snap = filings.query(OrderBookSnapshot).one()
    assert (snap.quarter, snap.order_book_cr, snap.document_id) == (
        "Q2 FY27",
        650000,
        presentation.id,
    )
    assert snap.as_written["order_book"]["found"] and not snap.as_written["revenue"]["found"]

    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    assert len(client.requests) == 1  # this quarter is done

    # A corporate presentation filed the next quarter repeating the same figures.
    doc(
        filings,
        LT,
        datetime(2027, 2, 10, 18, 0, tzinfo=IST),
        "investor_presentation",
        "Corporate presentation",
        "Order book Rs 6,50,000 crore. " * 30,
    )
    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    q3 = filings.query(OrderBookSnapshot).filter_by(quarter="Q3 FY27").one()
    assert q3.order_book_cr is None and "same order book and revenue as Q2 FY27" in q3.note

    # One stored earlier (before this guard) is left out of the figures.
    q3.order_book_cr, q3.revenue_cr = snap.order_book_cr, snap.revenue_cr
    filings.commit()
    books = [r["order_book_cr"] for r in ob.quarterly(filings, LT) if r["order_book_cr"]]
    assert books == [650000]


@pytest.mark.db
def test_a_quarter_without_an_order_book_tries_new_documents_only(filings):
    _orders(filings, 2)
    doc(
        filings,
        LT,
        datetime(2026, 7, 25, 18, 0, tzinfo=IST),
        "results",
        "Results Q1 FY27",
        "Revenue from operations 60,000. " * 30,
    )
    llm, client = _llm(filings, reply(book=None))
    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    snap = filings.query(OrderBookSnapshot).filter_by(quarter="Q1 FY27").one()
    assert snap.order_book_cr is None and len(snap.tried) == 1
    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    assert len(client.requests) == 1  # nothing new to try
    doc(
        filings,
        LT,
        datetime(2026, 7, 28, 18, 0, tzinfo=IST),
        "investor_presentation",
        "Investor presentation Q1 FY27",
        "Order book Rs 6,00,000 crore. " * 30,
    )
    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    assert len(client.requests) == 2
    waiting = doc(
        filings,
        LT,
        datetime(2026, 7, 29, 18, 0, tzinfo=IST),
        "concall_transcript",
        "Transcript Q1 FY27",
        "",
    )
    waiting.text_status = "pending"
    filings.commit()
    ob.update_snapshots(filings, llm, since=date(2026, 1, 1))
    snap = filings.query(OrderBookSnapshot).filter_by(quarter="Q1 FY27").one()
    assert waiting.id not in snap.tried  # read once its PDF is downloaded


def _snapshot(session, quarter, book, inflow, revenue, isin=LT):
    session.add(
        OrderBookSnapshot(
            isin=isin,
            quarter=quarter,
            period_end=cc.period_end(quarter),
            order_book_cr=book,
            inflow_cr=inflow,
            revenue_cr=revenue,
            as_written={},
            tried=[],
        )
    )


@pytest.mark.db
def test_metrics_and_peers(filings):
    for q, book, inflow, revenue in [
        ("Q1 FY26", 500000, 70000, 50000),
        ("Q2 FY26", 520000, 80000, 60000),
        ("Q3 FY26", 540000, 90000, 70000),
        ("Q4 FY26", 560000, 100000, 80000),
        ("Q1 FY27", 600000, 110000, 60000),
        ("Q2 FY27", 650000, 115000, 67000),
    ]:
        _snapshot(filings, q, book, inflow, revenue)
    _orders(filings, 2, when=datetime(2026, 8, 10, 10, 0, tzinfo=IST), value=40000)  # Q2 FY27
    _orders(filings, 1, when=datetime(2025, 8, 10, 10, 0, tzinfo=IST), value=20000)  # Q2 FY26
    filings.commit()

    rows = {r["quarter"]: r for r in ob.quarterly(filings, LT)}
    q2 = rows["Q2 FY27"]
    assert q2["announced_cr"] == 80000 and q2["announced"] == 2
    assert q2["book_to_bill"] == pytest.approx(115000 / 67000)
    assert q2["announced_share"] == pytest.approx(80000 / 115000)
    # 650,000 - (600,000 + 115,000 - 67,000) = 2,000
    assert q2["unexplained_cr"] == pytest.approx(2000)
    assert rows["Q1 FY26"]["unexplained_cr"] is None  # no opening book

    s = ob.summary(filings, LT, today=date(2026, 10, 26))
    assert s["quarters"] == ["Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"]
    assert s["inflow_cr"] == 415000 and s["revenue_cr"] == 277000
    assert s["years_of_revenue"] == pytest.approx(650000 / 277000)
    assert s["execution"] == pytest.approx(277000 / 520000)  # book at Q2 FY26
    assert s["announced_growth"] == pytest.approx(80000 / 20000 - 1)
    assert s["government_share"] == pytest.approx(0.5) and s["orders_last_year"] == 2
    assert s["top_client"] == "Client 0" and s["top_client_share"] == pytest.approx(0.5)
    filings.query(Order).filter(Order.client == "Client 0").update({"client": None})
    assert ob.summary(filings, LT, today=date(2026, 10, 26))["top_client"] == "Client 1"
    filings.query(Order).filter(Order.client.is_(None)).update({"client": "Client 0"})

    assert ob.summary(filings, LT, today=date(2026, 3, 1))["years_of_revenue"] is None  # 3 quarters
    # A quarter that ended but has no results yet does not blank the measures.
    _orders(filings, 1, when=datetime(2026, 11, 2, 10, 0, tzinfo=IST), value=5000)  # Q3 FY27
    later = ob.summary(filings, LT, today=date(2027, 1, 10))
    assert later["quarters"] == ["Q3 FY26", "Q4 FY26", "Q1 FY27", "Q2 FY27"]
    assert later["years_of_revenue"] == pytest.approx(650000 / 277000)
    filings.query(Order).filter(Order.value_cr == 5000).delete()
    filings.commit()

    _orders(filings, 2, isin=KVB, value=100)
    ranked = {r["symbol"]: r for r in ob.peers(filings, today=date(2026, 10, 26))}
    assert set(ranked) == {"LT", "KARURVYSYA"}
    assert ranked["LT"]["years_of_revenue_rank"] == 1
    assert "years_of_revenue_rank" not in ranked["KARURVYSYA"]  # no order book: not ranked


@pytest.mark.db
def test_orders_reach_digest_dashboard_cli_and_scheduler(
    filings, test_database_url, monkeypatch, tmp_path
):
    from streamlit.testing.v1 import AppTest
    from typer.testing import CliRunner

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.agents.orchestrator import run_job
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.ui import queries

    llm, _ = _llm(filings, reply())
    ob.extract_orders(filings, llm)
    _orders(filings, 1, value=900)
    _snapshot(filings, "Q2 FY27", 650000, 115000, 67000)
    filings.commit()

    now = datetime.now(IST)
    md = build_digest(filings, now.replace(year=now.year - 1), now).markdown
    assert "## Orders" in md and "- LT 21 Oct: Rs 2,500-5,000 cr from Delhi Metro" in md

    data = queries.order_book(filings, LT)
    assert list(data["quarters"]["quarter"]) == ["Q2 FY27", "Q3 FY27"]
    assert len(data["orders"]) == 2 and data["summary"]["order_book_cr"] == 650000

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    runner = CliRunner()
    out = runner.invoke(app, ["orders", "list", "LT", "--days", "36500"])
    assert out.exit_code == 0 and "Rs 3,750 cr (2,500-5,000)" in out.stdout
    line = next(x for x in out.stdout.splitlines() if "3,750" in x)
    assert "not found as written" not in line  # valued from its size class, not a number
    out = runner.invoke(app, ["orders", "book", "LT"])
    assert out.exit_code == 0 and "650,000" in out.stdout and "Q2 FY27" in out.stdout
    out = runner.invoke(app, ["orders", "coverage"])
    assert out.exit_code == 0
    lt = next(line for line in out.stdout.splitlines() if line.startswith("LT "))
    # 3 order-win filings: 1 read, 1 copy, the helper's unread; 2 orders; 1 order book
    assert lt.split()[1:9] == ["3", "1", "1", "0", "0", "1", "2", "1"] and lt.endswith("yes")
    out = runner.invoke(app, ["orders", "peers"])
    assert out.exit_code == 0 and "LT" in out.stdout
    assert run_job("orders").summary.startswith("skipped")

    at = AppTest.from_string(
        "import streamlit as st\nst.cache_data.clear()\n"
        "from stock_news_analyzer.ui import app\napp.stock_page_body()",
        default_timeout=30,
    )
    at.query_params["symbol"] = "LT"
    at.run()
    assert not at.exception, at.exception
    assert any(m.label == "Order book" and m.value == "Rs 650,000 cr" for m in at.metric)
