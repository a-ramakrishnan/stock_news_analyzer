from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_concalls import LT, _llm
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import KVB, _orders, _snapshot, doc

from stock_news_analyzer.agents import orders as ob
from stock_news_analyzer.agents import results as rs
from stock_news_analyzer.models import LlmCall, QuarterlyResult, ResultFiling
from stock_news_analyzer.sources.announcements import IST

OCT = datetime(2026, 10, 28, 16, 0, tzinfo=IST)
STATEMENT = """Larsen & Toubro Limited
Statement of Consolidated Unaudited Financial Results for the quarter ended September 30, 2026
(Rs in lakh)
Particulars Quarter ended Half year ended
30.09.2026 30.06.2026 30.09.2025 30.09.2026
Revenue from operations 67,00,000.00 60,00,000.00 61,00,000.00 1,27,00,000.00
Other income 1,20,000.00 1,00,000.00 90,000.00 2,20,000.00
Finance costs 90,000.00 85,000.00 80,000.00 1,75,000.00
Depreciation and amortisation expense 1,10,000.00 1,05,000.00 1,00,000.00 2,15,000.00
Profit before tax 6,00,000.00 5,20,000.00 5,10,000.00 11,20,000.00
Net profit for the period 4,40,000.00 3,90,000.00 3,80,000.00 8,30,000.00
Basic EPS (Rs) 31.20 27.70 26.95 58.90
"""
PADDING = "Notes to the results. " * 40


def col(end, months, revenue, other, finance, dep, pbt, pat, eps):
    return rs.Column(
        period_end=end,
        months=months,
        revenue=revenue,
        other_income=other,
        finance_costs=finance,
        depreciation=dep,
        pbt=pbt,
        pat=pat,
        eps=eps,
    )


Q2 = col(
    "2026-09-30",
    3,
    "67,00,000.00",
    "1,20,000.00",
    "90,000.00",
    "1,10,000.00",
    "6,00,000.00",
    "4,40,000.00",
    "31.20",
)
Q1 = col(
    "2026-06-30",
    3,
    "60,00,000.00",
    "1,00,000.00",
    "85,000.00",
    "1,05,000.00",
    "5,20,000.00",
    "3,90,000.00",
    "27.70",
)
Q2_LAST_YEAR = col(
    "2025-09-30",
    3,
    "61,00,000.00",
    "90,000.00",
    "80,000.00",
    "1,00,000.00",
    "5,10,000.00",
    "3,80,000.00",
    "26.95",
)
H1 = col(
    "2026-09-30",
    6,
    "1,27,00,000.00",
    "2,20,000.00",
    "1,75,000.00",
    "2,15,000.00",
    "11,20,000.00",
    "8,30,000.00",
    "58.90",
)


def answer(columns=None, is_results=True, unit="lakh"):
    return rs.ResultsAnswer(
        is_results=is_results,
        basis="consolidated",
        unit=unit,
        columns=[Q2, Q1, Q2_LAST_YEAR, H1] if columns is None else columns,
        note="Consolidated results for the quarter ended 30 Sep 2026.",
    )


def replying(*answers):
    queue = list(answers)

    def reply(_kwargs):
        return SimpleNamespace(
            usage=usage(8000, 1200), parsed_output=queue.pop(0), stop_reason="end_turn"
        )

    return reply


def results_filing(
    session,
    when=OCT,
    title="Financial Results for the quarter ended 30.09.2026",
    isin=LT,
    text=STATEMENT + PADDING,
):
    return doc(session, isin, when, "results", title, text)


def test_figures_as_written_become_numbers():
    assert rs.number("12,345.67") == Decimal("12345.67")
    assert rs.number("1,27,00,000.00") == Decimal("12700000.00")
    assert rs.number("(234.10)") == Decimal("-234.10")
    assert rs.number("-56") == Decimal("-56")
    assert rs.number("Rs. 31.20") == Decimal("31.20")
    assert rs.number("-") is None and rs.number(None) is None


def test_period_labels():
    assert rs.period_label(date(2026, 9, 30), 3) == "Q2 FY27"
    assert rs.period_label(date(2026, 9, 30), 6) == "H1 FY27"
    assert rs.period_label(date(2027, 3, 31), 6) == "H2 FY27"
    assert rs.period_label(date(2027, 3, 31), 12) == "FY27"
    assert rs.period_label(date(2026, 12, 31), 9) is None  # nine months: not stored
    assert rs.period_label(date(2026, 12, 31), 6) is None


def test_excerpt_keeps_the_statements_and_drops_the_rest():
    text = "Covering letter. " + "Auditor's report. " * 2000 + STATEMENT + "Notes. " * 2000
    part = rs.excerpt(text)
    assert part.startswith("Covering letter.")
    assert "Revenue from operations 67,00,000.00" in part and "Basic EPS (Rs) 31.20" in part
    assert len(part) < len(text) / 3
    assert rs.excerpt("No statement here.") == "No statement here."


def test_excerpt_finds_the_statement_behind_a_long_press_release():
    release = "".join(
        f"Revenue from operations for segment {i} rose 12% to Rs 6,707 crore.\n" + "Text. " * 900
        for i in range(10)
    )
    part = rs.excerpt("Press release. " + release + STATEMENT)
    assert "Revenue from operations 67,00,000.00 60,00,000.00" in part


def broken_then(answers):
    """Replies with each of `answers` in turn; None stands for a cut-off, malformed answer."""

    def reply(_kwargs):
        parsed = answers.pop(0)
        if parsed is None:
            rs.ResultsAnswer.model_validate_json('{"is_results": true, "basis": "')
        return SimpleNamespace(
            usage=usage(8000, 1200), parsed_output=parsed, stop_reason="end_turn"
        )

    return reply


@pytest.mark.db
def test_sonnet_reads_what_haiku_could_not(loaded):  # noqa: F811
    first = results_filing(loaded)
    llm, client = _llm(loaded, broken_then([None, answer()]))
    result = rs.read_results(loaded, llm)
    assert (result.failed, result.periods, result.calls) == (0, 4, 2)
    filing = loaded.get(ResultFiling, first.id)
    assert (filing.status, filing.model) == ("read", "claude-sonnet-5-5")


@pytest.mark.db
def test_a_figure_not_in_the_filing_is_not_stored(loaded):  # noqa: F811
    results_filing(loaded)
    dropped = Q2.model_copy(update={"revenue": "6700000000"})  # "67,00,000.00" without its point
    llm, _ = _llm(loaded, replying(answer([dropped, Q1])))
    rs.read_results(loaded, llm)
    q2 = loaded.query(QuarterlyResult).filter_by(period="Q2 FY27").one()
    assert q2.revenue_cr is None and q2.pat_cr == Decimal("4400.00")
    assert q2.as_written["revenue"] == {"as_written": "6700000000", "found": False}
    assert rs.numbers_in("Revenue 67,078.68 (234.10)") == {Decimal("67078.68"), Decimal("234.10")}


@pytest.mark.db
def test_a_lost_decimal_point_is_restored_by_checking_figures_against_each_other(loaded):  # noqa: F811
    def quarter(end, revenue, pat, written_revenue, written_pat):
        loaded.add(
            QuarterlyResult(
                isin=LT,
                period=rs.period_label(end, 3),
                period_end=end,
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=revenue,
                pat_cr=pat,
                unit="crore",
                model="m",
                as_written={
                    "revenue": {"as_written": written_revenue, "found": True},
                    "pat": {"as_written": written_pat, "found": True},
                    "finance_costs": {"as_written": "782.10", "found": True},
                },
            )
        )

    quarter(date(2025, 3, 31), Decimal("7439228"), Decimal("549726"), "7439228", "549726")
    quarter(date(2025, 6, 30), Decimal("63679.12"), Decimal("3617.45"), "63,679.12", "3,617.45")
    quarter(date(2025, 9, 30), Decimal("67983.53"), Decimal("3926.10"), "67,983.53", "3,926.10")
    quarter(date(2025, 12, 31), Decimal("71450.20"), Decimal("3215.00"), "71,450.20", "3,215.00")
    # 30x the usual revenue and written with its point: not a lost point, left out.
    quarter(
        date(2026, 3, 31), Decimal("2100000.50"), Decimal("5326.00"), "21,00,000.50", "5,326.00"
    )
    loaded.commit()
    assert rs.check_scale(loaded, LT) == 3
    rows = {r.period: r for r in rs.periods(loaded, LT, 3)}
    assert rows["Q4 FY25"].revenue_cr == Decimal("74392.28")
    assert rows["Q4 FY25"].pat_cr == Decimal("5497.26")
    assert rows["Q4 FY25"].as_written["revenue"]["note"] == "decimal point restored"
    assert rows["Q4 FY26"].revenue_cr is None
    assert rows["Q4 FY26"].as_written["revenue"]["note"] == "out of scale, left out"
    assert rows["Q1 FY26"].revenue_cr == Decimal("63679.12")  # untouched
    assert rs.check_scale(loaded, LT) == 0  # nothing left to change


@pytest.mark.db
def test_an_unusable_answer_is_recorded_and_the_next_filing_tried(loaded):  # noqa: F811
    first = results_filing(loaded)
    second = results_filing(loaded, OCT.replace(minute=20), "Outcome of Board Meeting")
    answers = [None, None, answer()]  # Haiku and Sonnet both fail on the first filing

    llm, client = _llm(loaded, broken_then(answers))
    result = rs.read_results(loaded, llm)
    assert (result.failed, result.periods, result.calls) == (1, 4, 3)
    assert [r["model"] for r in client.requests] == [
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    assert client.requests[0]["max_tokens"] == rs.MAX_TOKENS
    assert loaded.get(ResultFiling, first.id).status == "failed"
    assert loaded.get(ResultFiling, second.id).status == "read"
    assert rs.pending(loaded) == []  # not asked again on the next run


@pytest.mark.db
def test_reads_a_quarter_and_its_comparatives_once(loaded):  # noqa: F811
    bse = results_filing(loaded)
    nse = results_filing(loaded, OCT.replace(minute=20), "Outcome of Board Meeting")
    llm, client = _llm(loaded, replying(answer()))
    result = rs.read_results(loaded, llm)
    assert (result.filings, result.periods, result.duplicates, result.errors) == (1, 4, 1, [])
    assert client.requests[0]["model"] == "claude-haiku-5-5"
    prompt = client.requests[0]["messages"][0]["content"]
    assert "Probably results for Q2 FY27" in prompt and "(Rs in lakh)" in prompt
    rows = {(r.period, r.primary): r for r in loaded.query(QuarterlyResult)}
    assert set(rows) == {
        ("Q2 FY27", True),
        ("H1 FY27", True),
        ("Q1 FY27", False),
        ("Q2 FY26", False),
    }
    q2 = rows[("Q2 FY27", True)]
    assert q2.revenue_cr == Decimal("67000.00")  # 67,00,000 lakh
    assert q2.pat_cr == Decimal("4400.00") and q2.eps == Decimal("31.20")
    assert q2.basis == "consolidated" and q2.unit == "lakh" and q2.document_id == bse.id
    assert all(v["found"] for v in q2.as_written.values())
    filings = {f.document_id: f for f in loaded.query(ResultFiling)}
    assert (filings[bse.id].status, filings[bse.id].period) == ("read", "Q2 FY27")
    assert filings[nse.id].status == "duplicate"
    assert rs.pending(loaded) == []
    assert loaded.query(LlmCall).filter_by(task="results").count() == 1

    shown = {r["period"]: r for r in rs.table(loaded, LT)}
    assert list(shown) == ["Q2 FY26", "Q1 FY27", "Q2 FY27"]  # quarters; the half year is apart
    assert shown["Q2 FY27"]["revenue_yoy"] == pytest.approx(67000 / 61000 - 1)
    # EBITDA = 6,000 + 900 + 1,100 - 1,200 = 6,800
    assert shown["Q2 FY27"]["ebitda_cr"] == pytest.approx(6800)
    assert shown["Q2 FY27"]["ebitda_margin"] == pytest.approx(6800 / 67000)
    assert shown["Q2 FY27"]["pat_yoy"] == pytest.approx(4400 / 3800 - 1)


@pytest.mark.db
def test_a_key_figures_table_is_used_when_there_is_no_statement(loaded):  # noqa: F811
    text = (
        "Press release. L&T's Q1 results.\nAnnexure 1 Group Performance - Key Parameters\n"
        "Key Parameters (in Rs crore) Q1 FY'26 Q1 FY'27 % Var\n"
        "Revenue from operations 63,679 67,942 7%\n"
        "Finance costs 782 539 (31%)\nDepreciation & Amortisation 1,033 1,032 0%\n"
        "Consolidated Profit After Tax 3,617 4,123 14%\n" + PADDING
    )
    results_filing(
        loaded, datetime(2026, 7, 28, 16, 0, tzinfo=IST), "Outcome of Board Meeting", text=text
    )
    key = [
        col("2026-06-30", 3, "67,942", None, "539", "1,032", None, "4,123", None),
        col("2025-06-30", 3, "63,679", None, "782", "1,033", None, "3,617", None),
    ]
    llm, client = _llm(loaded, replying(answer(key, unit="crore")))
    rs.read_results(loaded, llm)
    assert (
        "Key Parameters" in rs.SYSTEM
        and "Key Parameters" in client.requests[0]["system"][0]["text"]
    )
    shown = {r["period"]: r for r in rs.table(loaded, LT)}
    q1 = shown["Q1 FY27"]
    assert (q1["revenue_cr"], q1["pat_cr"]) == (67942, 4123) and q1["checked"]
    assert q1["ebitda_cr"] is None  # no profit before tax or other income in the table
    assert q1["revenue_yoy"] == pytest.approx(67942 / 63679 - 1)


@pytest.mark.db
def test_a_periods_own_filing_wins_over_a_comparative_column(loaded):  # noqa: F811
    results_filing(loaded)
    july = results_filing(
        loaded,
        datetime(2026, 7, 30, 16, 0, tzinfo=IST),
        "Financial Results for the quarter ended 30.06.2026",
        text=STATEMENT + "Revenue from operations (restated) 59,50,000.00\n" + PADDING,
    )
    restated = Q1.model_copy(update={"revenue": "59,50,000.00"})
    llm, _ = _llm(loaded, replying(answer([restated]), answer()))
    rs.read_results(loaded, llm)  # Q1's own filing first (oldest period first)
    q1 = loaded.query(QuarterlyResult).filter_by(period="Q1 FY27").one()
    assert (q1.revenue_cr, q1.primary, q1.document_id) == (Decimal("59500.00"), True, july.id)
    assert q1.as_written["revenue"]["found"] is True


@pytest.mark.db
def test_a_filing_without_a_statement_is_recorded_and_not_read_again(loaded):  # noqa: F811
    notice = results_filing(loaded, title="Outcome of Board Meeting: dividend")
    llm, _ = _llm(loaded, replying(answer([], is_results=False)))
    result = rs.read_results(loaded, llm)
    assert (result.no_figures, result.periods) == (1, 0)
    assert loaded.get(ResultFiling, notice.id).status == "no_figures"
    scanned = results_filing(loaded, OCT.replace(hour=18), text="Signed copy")
    rs.read_results(loaded, llm)  # no LLM call: the reply queue is empty
    assert loaded.get(ResultFiling, scanned.id).status == "no_text"


@pytest.mark.db
def test_trailing_revenue_from_quarters_or_half_years(loaded):  # noqa: F811
    def period(end, months, revenue, isin=LT):
        loaded.add(
            QuarterlyResult(
                isin=isin,
                period=rs.period_label(end, months) or "x",
                period_end=end,
                months=months,
                basis="standalone",
                primary=True,
                revenue_cr=revenue,
                unit="crore",
                as_written={},
                model="m",
            )
        )

    for end, revenue in [
        (date(2025, 12, 31), 100),
        (date(2026, 3, 31), 110),
        (date(2026, 6, 30), 120),
        (date(2026, 9, 30), 130),
    ]:
        period(end, 3, revenue)
    period(date(2026, 3, 31), 6, 300, KVB)
    period(date(2026, 9, 30), 6, 340, KVB)
    loaded.commit()
    assert rs.trailing_revenue(loaded, LT, date(2026, 9, 30)) == (460, "4 quarters")
    assert rs.trailing_revenue(loaded, LT, date(2026, 6, 30)) is None
    assert rs.trailing_revenue(loaded, KVB, date(2026, 9, 30)) == (640, "2 half years")
    # Moved to quarterly results after H1 FY27: two quarters and the half year before them.
    period(date(2026, 12, 31), 3, 200, KVB)
    period(date(2027, 3, 31), 3, 210, KVB)
    loaded.commit()
    assert rs.trailing_revenue(loaded, KVB, date(2027, 3, 31)) == (
        750,
        "2 quarters and a half year",
    )
    assert rs.quarter_revenue(loaded, LT)["Q2 FY27"] == 130


@pytest.mark.db
def test_order_metrics_use_results_revenue_where_order_books_lack_it(loaded):  # noqa: F811
    # Half-yearly reporter: order books at the half years, revenue only in the results.
    _snapshot(loaded, "Q4 FY26", 2000, None, None)
    _snapshot(loaded, "Q2 FY27", 2400, None, None)
    _orders(loaded, 2, when=datetime(2026, 8, 10, 10, 0, tzinfo=IST), value=300)
    _orders(loaded, 1, when=datetime(2025, 11, 10, 10, 0, tzinfo=IST), value=200)
    for end, revenue in [(date(2026, 3, 31), 500), (date(2026, 9, 30), 700)]:
        loaded.add(
            QuarterlyResult(
                isin=LT,
                period=rs.period_label(end, 6),
                period_end=end,
                months=6,
                basis="standalone",
                primary=True,
                revenue_cr=revenue,
                unit="lakh",
                as_written={},
                model="m",
            )
        )
    loaded.add(
        QuarterlyResult(
            isin=LT,
            period="Q1 FY27",
            period_end=date(2026, 6, 30),
            months=3,
            basis="standalone",
            primary=False,
            revenue_cr=330,
            unit="lakh",
            as_written={},
            model="m",
        )
    )
    loaded.commit()
    rows = {r["quarter"]: r for r in ob.quarterly(loaded, LT)}
    assert rows["Q2 FY27"]["revenue_cr"] is None  # no quarter's figure for Q2: only the half
    s = ob.summary(loaded, LT, today=date(2026, 10, 26))
    assert s["revenue_cr"] == 1200 and s["revenue_from"] == "results, 2 half years"
    assert s["years_of_revenue"] == pytest.approx(2400 / 1200)
    assert s["inflow_cr"] == 800 and s["inflow_from"] == "announced"  # orders in the 12 months
    assert s["book_to_bill"] == pytest.approx(800 / 1200)

    # A newer order book whose 12 months the results don't cover yet: the measures stay on
    # the latest book they can be worked out for.
    _snapshot(loaded, "Q3 FY27", 2600, None, None)
    loaded.commit()
    s = ob.summary(loaded, LT, today=date(2027, 1, 20))
    assert s["order_book_quarter"] == "Q2 FY27" and s["years_of_revenue"] == pytest.approx(2)

    _snapshot(loaded, "Q1 FY27", 2200, 100, None)
    loaded.commit()
    q1 = {r["quarter"]: r for r in ob.quarterly(loaded, LT)}["Q1 FY27"]
    assert (q1["revenue_cr"], q1["revenue_from"]) == (330, "results")


@pytest.mark.db
def test_results_reach_digest_dashboard_cli_and_scheduler(
    loaded,  # noqa: F811
    test_database_url,
    monkeypatch,
    tmp_path,
):
    from streamlit.testing.v1 import AppTest
    from typer.testing import CliRunner

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.agents.orchestrator import RUN_ALL, run_job
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.ui import queries

    results_filing(loaded)
    llm, _ = _llm(loaded, replying(answer()))
    rs.read_results(loaded, llm)

    now = datetime.now(IST)
    md = build_digest(loaded, now.replace(year=now.year - 1), now.replace(year=now.year + 1))
    assert "## Results" in md.markdown
    assert (
        "- LT Q2 FY27 (consolidated): revenue Rs 67,000 cr (+10% y/y), profit Rs 4,400 cr "
        "(+16% y/y), EBITDA margin 10.1%" in md.markdown
    )
    assert list(queries.results(loaded, LT)["period"]) == ["Q2 FY26", "Q1 FY27", "Q2 FY27"]
    assert RUN_ALL.index("results") < RUN_ALL.index("orders")

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    runner = CliRunner()
    out = runner.invoke(app, ["results", "list", "LT"])
    assert out.exit_code == 0, out.stdout
    q2 = next(x for x in out.stdout.splitlines() if x.startswith("Q2 FY27"))
    assert "67,000" in q2 and "+10%" in q2 and "consolidated" in q2 and "not all" not in q2
    q1 = next(x for x in out.stdout.splitlines() if x.startswith("Q1 FY27"))
    assert "comparative column" in q1
    out = runner.invoke(app, ["results", "coverage"])
    assert out.exit_code == 0
    lt = next(line for line in out.stdout.splitlines() if line.startswith("LT "))
    assert lt.split()[1:10] == ["1", "1", "0", "0", "0", "0", "0", "0", "4"]
    assert lt.endswith("Q2 FY27")
    assert run_job("results").summary.startswith("skipped")

    at = AppTest.from_string(
        "import streamlit as st\nst.cache_data.clear()\n"
        "from stock_news_analyzer.ui import app\napp.stock_page_body()",
        default_timeout=30,
    )
    at.query_params["symbol"] = "LT"
    at.run()
    assert not at.exception, at.exception
    assert any(m.label == "Revenue, Q2 FY27" and m.value == "Rs 67,000 cr" for m in at.metric)


@pytest.mark.db
def test_probe_shows_the_results_listing_and_an_xbrl_file(
    loaded,  # noqa: F811
    test_database_url,
    monkeypatch,
    tmp_path,
):
    from test_xbrl import SAMPLE
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.sources import exchange_http

    class FakeNSE:
        def __init__(self, *a, **kw):
            pass

        def nse_financial_results(self, symbol, period="Quarterly", index="equities"):
            if period != "Quarterly":
                raise exchange_http.ExchangeError("NSE returned HTTP 404")
            return [
                {
                    "symbol": symbol,
                    "toDate": "30-Jun-2026",
                    "consolidated": "Consolidated",
                    "xbrl": "/corporate/xbrl/LT_Q1.xml",
                }
            ]

        def download(self, exchange, urls):
            assert urls == ["https://nsearchives.nseindia.com/corporate/xbrl/LT_Q1.xml"]
            return urls[0], SAMPLE, True

    monkeypatch.setattr(exchange_http, "ExchangeClient", FakeNSE)
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    out = CliRunner().invoke(app, ["results", "probe", "LT"])
    assert out.exit_code == 0, out.stdout
    assert "Quarterly (equities): 1 filings" in out.stdout
    assert "Half-Yearly (equities): FAILED ExchangeError" in out.stdout
    assert "3 facts" in out.stdout and "RevenueFromOperations" in out.stdout
    assert (tmp_path / "probe" / "LT.xml").read_bytes() == SAMPLE
