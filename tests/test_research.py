from datetime import date, datetime
from decimal import Decimal

import pytest
from test_prices import _load_series, _trading_days, watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import research as rs
from stock_news_analyzer.agents import valuation as val
from stock_news_analyzer.agents import xbrl_results as xr
from stock_news_analyzer.models import (
    BalanceSheet,
    CorporateAction,
    Document,
    DocumentCompany,
    QuarterlyResult,
)
from stock_news_analyzer.sources.announcements import IST

KVB = "INE036D01028"


def _xbrl(contexts: str, facts: list[tuple[str, str, str]]) -> bytes:
    body = "".join(
        f'<in-capmkt:{tag} contextRef="{ctx}" unitRef="INR">{v}</in-capmkt:{tag}>'
        for tag, ctx, v in facts
    )
    return (
        '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
        f'xmlns:in-capmkt="http://example/in-capmkt">{contexts}{body}</xbrli:xbrl>'
    ).encode()


def _context(cid: str, instant: str | None = None, span=None, member=False) -> str:
    period = (
        f"<xbrli:instant>{instant}</xbrli:instant>"
        if instant
        else f"<xbrli:startDate>{span[0]}</xbrli:startDate><xbrli:endDate>{span[1]}</xbrli:endDate>"
    )
    seg = (
        '<xbrli:segment><xbrldi:explicitMember dimension="x">Seg</xbrldi:explicitMember>'
        "</xbrli:segment>"
        if member
        else ""
    )
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity>{seg}</xbrli:entity>'
        f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
    )


def test_balance_sheet_and_cash_flow_from_xbrl():
    contexts = (
        _context("OneI", instant="2026-03-31")
        + _context("PrevI", instant="2025-03-31")
        + _context("SegI", instant="2026-03-31", member=True)
        + _context("FourD", span=("2025-04-01", "2026-03-31"))
        + _context("OneD", span=("2026-01-01", "2026-03-31"))
    )

    def crore(n: int) -> str:  # filed in rupees
        return str(n * 10_000_000)

    content = _xbrl(
        contexts,
        [
            ("EquityAttributableToOwnersOfParent", "OneI", crore(5000)),
            ("EquityAttributableToOwnersOfParent", "PrevI", "1"),
            ("BorrowingsNoncurrent", "OneI", crore(2000)),
            ("BorrowingsCurrent", "OneI", crore(500)),
            ("BorrowingsCurrent", "SegI", "999"),  # a segment's: left out
            ("CashAndCashEquivalents", "OneI", crore(300)),
            ("CashFlowsFromUsedInOperatingActivities", "FourD", crore(1200)),
            ("CashFlowsFromUsedInOperatingActivities", "OneD", "1"),  # the quarter: not this
            (
                "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                "FourD",
                crore(-400),
            ),
        ],
    )
    found = xr.balance_figures(content, date(2026, 3, 31))
    assert found["equity"][0] == Decimal(5000)
    assert found["borrowings"] == (Decimal(2500), "BorrowingsNoncurrent+BorrowingsCurrent")
    assert found["cash"][0] == Decimal(300)
    assert found["cfo"][0] == Decimal(1200)
    assert found["capex"][0] == Decimal(400)  # filed as negative, kept as an amount spent
    assert xr.balance_figures(content, date(2025, 12, 31)) == {}  # a quarter end: none due


def test_dates_in_filings():
    text = (
        "Intimation of Board Meeting on 18th November, 2026 to consider results for the "
        "quarter ended September 30, 2026; AGM on 12-Aug-2027"
    )
    assert rs.dates_in(text) == [
        date(2026, 11, 18),
        date(2027, 8, 12),
        date(2026, 9, 30),
    ]
    assert rs._quarter_end_after(date(2026, 9, 30)) == date(2026, 12, 31)
    assert rs._quarter_end_after(date(2026, 12, 31)) == date(2027, 3, 31)


def test_trailing_eps_adjusts_for_a_split():
    qs = [
        val.Quarter(date(2025, 6, 30), 10.0, date(2025, 8, 10)),
        val.Quarter(date(2025, 9, 30), 10.0, date(2025, 11, 10)),
        val.Quarter(date(2025, 12, 31), 10.0, date(2026, 2, 10)),
        val.Quarter(date(2026, 3, 31), 6.0, date(2026, 5, 10)),  # reported after a 1:2 split
    ]
    split = [(date(2026, 4, 1), 0.5)]
    eps, used = val.eps_ttm(qs, date(2026, 6, 1), split)
    assert eps == pytest.approx(5 + 5 + 5 + 6) and len(used) == 4
    assert val.eps_ttm(qs, date(2026, 4, 15), split)[0] is None  # only three known by then


@pytest.mark.db
def test_valuation_balance_and_coming(watchlist):  # noqa: F811
    s = watchlist
    days = _trading_days(40)  # June to July 2026
    _load_series(s, days, big_day=30)
    pr.compute_moves(s)
    for end, eps in (
        ("2025-06-30", 1.0),
        ("2025-09-30", 1.0),
        ("2025-12-31", 1.0),
        ("2026-03-31", 1.0),
    ):
        s.add(
            QuarterlyResult(
                isin=KVB,
                period=end,
                period_end=date.fromisoformat(end),
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=Decimal(100),
                pat_cr=Decimal(10),
                eps=Decimal(str(eps)),
                unit="crore",
                model="xbrl",
            )
        )
    s.add(
        BalanceSheet(
            isin=KVB,
            period_end=date(2026, 3, 31),
            months=12,
            basis="consolidated",
            equity_cr=Decimal(200),
            borrowings_cr=Decimal(50),
            cash_cr=Decimal(80),
            cfo_cr=Decimal(45),
            capex_cr=Decimal(15),
            as_written={"equity": "Equity"},
        )
    )
    doc = Document(
        source="bse",
        source_id="bm",
        doc_type="board_meeting",
        title="Board meeting",
        subject="Board Meeting on 10th August, 2026 to consider financial results",
        published_at=datetime(2026, 7, 20, 16, tzinfo=IST),
        raw={},
    )
    s.add(doc)
    s.flush()
    s.add(DocumentCompany(document_id=doc.id, isin=KVB))
    s.add(
        CorporateAction(
            symbol="KARURVYSYA",
            ex_date=date(2026, 8, 20),
            subject="Dividend - Rs 2 Per Share",
            kind="dividend",
            price_factor=1.0,
            raw={},
        )
    )
    s.commit()

    today = days[-1]
    v = val.valuation(s, KVB, today)
    assert v.eps_ttm == pytest.approx(4.0) and v.pe == pytest.approx(v.close / 4.0)
    assert v.pe_median is not None and 0 <= v.pe_percentile <= 1 and v.series

    f = rs.facts(s, KVB, today)
    lines = {b.label: b for b in f.balance}
    assert lines["Net debt"].value == pytest.approx(-30)  # net cash
    assert lines["Debt to equity"].value == pytest.approx(0.25)
    assert lines["Free cash flow, year"].value == pytest.approx(30)
    assert lines["Cash from operations to profit"].value == pytest.approx(45 / 40)
    assert lines["Equity"].badge == rs.FILED and lines["Equity"].note == "Equity"
    assert [c.what for c in f.coming] == [
        "Board meeting to approve results",
        "Ex-date: Dividend - Rs 2 Per Share",
    ]
    assert f.peers[0].is_subject and f.peers[0].pe == pytest.approx(v.pe)
    later = rs.facts(s, KVB, date(2027, 1, 15))
    assert {b.badge for b in later.balance if b.value is not None} == {rs.STALE}
