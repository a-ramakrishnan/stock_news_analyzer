from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_filings import make_pdf
from test_llm import FakeAnthropic, settings, usage
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import concalls as cc
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import (
    Concall,
    ConcallPoint,
    Document,
    DocumentCompany,
    LlmCall,
    Promise,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

LT = "INE018A01030"
KVB = "INE036D01028"
OCT = datetime(2026, 10, 24, 18, 0, tzinfo=IST)  # Q2 FY27 transcript filed
JAN = datetime(2027, 1, 30, 18, 0, tzinfo=IST)  # Q3 FY27 transcript filed

QUOTE = "We expect EBITDA margin of around 8.5 percent for FY27"
TRANSCRIPT = (
    "Larsen & Toubro Limited Q2 FY27 Earnings Conference Call, October 22, 2026. "
    "Moderator: Ladies and gentlemen, good day and welcome. "
    "Management: Order inflow for the quarter was Rs 1,15,000 crore, up 20 percent. "
    f"{QUOTE}, as guided earlier. The Hyderabad plant will be commissioned by Q3 FY27. "
    + "Analyst: Could you comment on working capital in the Middle East? "
    "Management: Collections were slower this quarter but should normalise. " * 40
)


# --- fiscal periods --------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Q3 FY27", date(2026, 12, 31)),
        ("by q1fy28", date(2027, 6, 30)),
        ("Q4 FY2027", date(2027, 3, 31)),
        ("FY28", date(2028, 3, 31)),
        ("in FY'27", date(2027, 3, 31)),
        ("H1 FY27", date(2026, 9, 30)),
        ("H2 FY27", date(2027, 3, 31)),
        ("9M FY27", date(2026, 12, 31)),
        ("by March 2027", date(2027, 3, 31)),
        ("February 2028", date(2028, 2, 29)),
        ("next year", None),
        (None, None),
    ],
)
def test_period_end(text, expected):
    assert cc.period_end(text) == expected


def test_quarter_names():
    assert cc.quarter_name("q2fy27") == "Q2 FY27"
    assert cc.quarter_name("Q2 FY2027 results") == "Q2 FY27"
    assert cc.quarter_name("FY27") is None
    assert cc.quarter_before(date(2026, 10, 24)) == "Q2 FY27"  # Jul-Sep 2026
    assert cc.quarter_before(date(2027, 1, 30)) == "Q3 FY27"
    assert cc.quarter_before(date(2027, 5, 10)) == "Q4 FY27"
    assert cc.quarter_before(date(2026, 8, 1)) == "Q1 FY27"


def test_quotes_are_checked_against_the_transcript():
    text = cc._norm(TRANSCRIPT)
    assert cc.quote_in("we expect EBITDA margin of around 8.5 percent, for FY27", text)
    assert not cc.quote_in("We expect EBITDA margin of 12 percent", text)
    assert not cc.quote_in("FY27", text)  # too short to tell


# --- reading calls ---------------------------------------------------------------


def transcript(session, isin, when, source="bse", text=TRANSCRIPT, status="ok", title=None):
    doc = Document(
        source=source,
        source_id=f"{source}-{isin}-{when:%Y%m%d%H%M}",
        doc_type="concall_transcript",
        title=title or "Transcript of the earnings call",
        subject=title or "Transcript of the earnings call",
        published_at=when,
        text=text,
        text_status=status,
        raw={},
    )
    session.add(doc)
    session.flush()
    session.add(DocumentCompany(document_id=doc.id, isin=isin))
    session.commit()
    return doc


def answer(quarter="Q2 FY27", updates=(), earnings=True):
    return cc.CallAnalysis(
        is_earnings_call=earnings,
        quarter=quarter,
        call_date="2026-10-22",
        tone="cautious",
        summary="Orders grew 20%; margins held; Middle East collections were slow.",
        points=[
            cc.Point(
                category="guidance",
                text="EBITDA margin ~8.5% in FY27",
                sentiment="neutral",
                quote=QUOTE,
            ),
            cc.Point(
                category="risk",
                text="Slow Middle East collections",
                sentiment="negative",
                quote="collections were a disaster this quarter",
            ),  # not in the transcript
        ],
        promises=[
            cc.PromiseItem(
                statement="Hyderabad plant commissioned by Q3 FY27",
                metric="Hyderabad plant",
                target="commissioned",
                due="Q3 FY27",
                quote="The Hyderabad plant will be commissioned by Q3 FY27",
            ),
        ],
        promise_updates=list(updates),
        analyst_concerns=[
            cc.Concern(
                topic="Working capital", question="Middle East collections?", answer="partial"
            )
        ],
        changes=[],
        action_points=["Watch Middle East collections", "Check FY27 margin vs 8.5%"],
    )


def replying(*answers):
    queue = list(answers)

    def reply(_kwargs):
        return SimpleNamespace(
            usage=usage(30000, 3000), parsed_output=queue.pop(0), stop_reason="end_turn"
        )

    return reply


def _llm(session, reply, **kw):
    client = FakeAnthropic(reply)
    return LLM(session, client=client, settings=settings(**kw)), client


@pytest.mark.db
def test_reads_a_call_once_although_filed_on_both_exchanges(loaded, tmp_path):  # noqa: F811
    bse = transcript(loaded, LT, OCT)
    nse = transcript(loaded, LT, OCT + timedelta(minutes=20), source="nse", text=TRANSCRIPT[:-50])
    llm, client = _llm(loaded, replying(answer()))
    calls, estimate = cc.estimate(loaded, cc.pending(loaded), "claude-sonnet-5-5")
    assert calls == 2  # this call, and the fixture's L&T transcript whose PDF is not read yet
    assert 0.05 < float(estimate) < 0.5
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    assert (result.analysed, result.duplicates, result.calls, result.errors) == (1, 1, 1, [])
    assert result.waiting == 1  # the fixture's transcript, PDF not downloaded

    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["output_config"] == {"effort": "medium"}
    prompt = request["messages"][0]["content"]
    assert "probably the Q2 FY27 results call" in prompt and "Previous call: none stored" in prompt
    assert "<transcript>" in prompt and "Order inflow for the quarter" in prompt

    call = loaded.query(Concall).filter_by(status="analysed").one()
    assert call.document_id == bse.id  # the copy with more text
    assert (call.quarter, call.period_end, call.tone) == ("Q2 FY27", date(2026, 9, 30), "cautious")
    assert call.call_date == date(2026, 10, 22) and call.text_source == "filing"
    copy = loaded.query(Concall).filter_by(document_id=nse.id).one()
    assert copy.status == "duplicate" and f"#{call.id}" in copy.note

    points = {p.category: p for p in loaded.query(ConcallPoint).filter_by(concall_id=call.id)}
    assert points["guidance"].quote_found and not points["risk"].quote_found
    promise = loaded.query(Promise).one()
    assert (promise.due_date, promise.status, promise.quote_found) == (
        date(2026, 12, 31),
        "open",
        True,
    )
    assert loaded.query(LlmCall).filter_by(task="concall").count() == 1
    assert {bse.id, nse.id}.isdisjoint(d.id for d, _ in cc.pending(loaded))  # both looked at


@pytest.mark.db
def test_next_call_is_compared_and_updates_promises(loaded, tmp_path):  # noqa: F811
    transcript(loaded, LT, OCT)
    llm, _ = _llm(loaded, replying(answer()))
    cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    promise = loaded.query(Promise).one()

    transcript(loaded, LT, JAN)
    later = answer(
        "Q3 FY27",
        updates=[
            cc.PromiseUpdate(id=promise.id, status="delayed", note="Now expected in Q1 FY28."),
            cc.PromiseUpdate(id=999_999, status="kept", note="An id it was never shown."),
        ],
    )
    llm, client = _llm(loaded, replying(later))
    cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    prompt = client.requests[0]["messages"][0]["content"]
    assert '<previous quarter="Q2 FY27" tone="cautious">' in prompt
    assert f"- id {promise.id}: Hyderabad plant commissioned by Q3 FY27" in prompt
    loaded.refresh(promise)
    assert (promise.status, promise.status_note) == ("delayed", "Now expected in Q1 FY28.")
    assert promise.status_concall_id == loaded.query(Concall).filter_by(quarter="Q3 FY27").one().id
    assert loaded.query(Promise).count() == 2  # the new call's promise was added


@pytest.mark.db
def test_a_letter_with_a_link_is_followed(loaded, tmp_path):  # noqa: F811
    letter = (
        "Dear Sir, the transcript of the earnings call is available on our website at "
        "https://www.larsentoubro.com/media/transcript-q2fy27.pdf and "
        "https://www.bseindia.com/xml-data/corpfiling/x.pdf . Not http://localhost:8501/x "
        "or http://192.168.1.1/x. Yours faithfully"
    )
    transcript(loaded, LT, OCT, text=letter)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return make_pdf(TRANSCRIPT.replace("(", "").replace(")", ""))

    llm, client = _llm(loaded, replying(answer()))
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path, fetch=fetch)
    assert result.analysed == 1
    assert fetched == ["https://www.larsentoubro.com/media/transcript-q2fy27.pdf"]
    call = loaded.query(Concall).filter_by(status="analysed").one()
    assert call.text_source == "link" and "Order inflow" in call.linked_text
    assert (tmp_path / call.linked_path).read_bytes().startswith(b"%PDF")
    assert "Order inflow" in client.requests[0]["messages"][0]["content"]


@pytest.mark.db
def test_transcripts_that_cannot_be_read(loaded, tmp_path):  # noqa: F811
    def broken(_url):
        raise OSError("connection refused")

    transcript(loaded, LT, OCT, text="See https://example.com/t.pdf for the transcript.")
    transcript(loaded, LT, JAN, text="", status="empty")
    transcript(
        loaded, LT, JAN + timedelta(days=60), title="Transcript of the Annual General Meeting"
    )
    llm, client = _llm(loaded, replying())
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path, fetch=broken)
    assert (result.no_text, result.skipped, result.calls) == (2, 1, 0) and client.requests == []
    notes = {c.published_at: (c.status, c.note) for c in loaded.query(Concall)}
    assert notes[OCT][0] == "no_text" and "https://example.com/t.pdf (OSError)" in notes[OCT][1]
    assert notes[JAN] == ("no_text", "scanned PDF with no text layer")
    notes = {status: note for status, note in notes.values()}
    assert "general meeting" in notes["skipped"]
    assert cc.reset(loaded, "LT", only_unread=True) == 3


@pytest.mark.db
def test_only_owned_stocks_unless_named(loaded, tmp_path):  # noqa: F811
    loaded.query(WatchlistItem).filter_by(isin=KVB).one().owned = False
    loaded.commit()
    transcript(loaded, KVB, OCT)
    assert all(c.isin != KVB for _, c in cc.pending(loaded))
    assert [c.isin for _, c in cc.pending(loaded, symbol="KARURVYSYA")] == [KVB]
    assert cc.pending(loaded, since=date(2026, 10, 25)) == []


@pytest.mark.db
def test_failures_and_budget_leave_transcripts_unread(loaded, tmp_path):  # noqa: F811
    doc = transcript(loaded, LT, OCT)

    def refused(_kw):
        return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="refusal")

    llm, _ = _llm(loaded, refused)
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    assert result.analysed == 0 and "declined" in result.errors[0]
    llm, client = _llm(loaded, replying(answer()), llm_monthly_budget_usd=0.0)
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    assert "budget" in result.errors[0] and client.requests == []
    assert doc.id in [d.id for d, _ in cc.pending(loaded)]


@pytest.mark.db
def test_not_an_earnings_call_and_reset(loaded, tmp_path):  # noqa: F811
    transcript(loaded, LT, OCT)
    llm, _ = _llm(loaded, replying(answer(earnings=False)))
    result = cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    assert result.skipped == 1 and loaded.query(Promise).count() == 0
    assert cc.reset(loaded) == 1 and loaded.query(Concall).count() == 0


@pytest.mark.db
def test_calls_reach_digest_dashboard_and_cli(loaded, tmp_path, test_database_url, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.agents.orchestrator import run_job
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.ui import queries

    doc = transcript(loaded, LT, OCT)
    llm, _ = _llm(loaded, replying(answer()))
    cc.analyse_calls(loaded, llm, data_dir=tmp_path)

    now = datetime.now(IST)
    md = build_digest(loaded, now - timedelta(hours=1), now + timedelta(minutes=1)).markdown
    assert "## Earnings calls" in md and "### LT Q2 FY27: cautious" in md
    assert "- Watch Middle East collections" in md
    assert "- Hyderabad plant commissioned by Q3 FY27 (due Q3 FY27)" in md

    calls = queries.concalls(loaded, LT)
    assert len(calls) == 1 and calls[0]["quarter"] == "Q2 FY27"
    assert {p["category"] for p in calls[0]["points"]} == {"guidance", "risk"}
    assert [p["quote"] for p in calls[0]["points"]] == [QUOTE, None]  # unverified quote hidden
    ledger = queries.promises(loaded, LT)
    assert list(ledger["due_date"]) == [date(2026, 12, 31)]
    assert bool(ledger["overdue"].iloc[0]) == (now.date() > date(2026, 12, 31))
    assert "Order inflow" in queries.concall_text(loaded, doc.id)
    assert queries.data_counts(loaded)["earnings calls analysed"] == 1

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    runner = CliRunner()
    out = runner.invoke(app, ["concalls", "list", "LT"])
    assert out.exit_code == 0 and "Q2 FY27" in out.stdout and "cautious" in out.stdout
    out = runner.invoke(app, ["concalls", "show", "LT", "--quarter", "q2fy27"])
    assert out.exit_code == 0 and "To watch:" in out.stdout
    assert "(quote not found in the transcript)" in out.stdout
    out = runner.invoke(app, ["concalls", "promises", "--open"])
    assert out.exit_code == 0 and "Hyderabad plant" in out.stdout
    out = runner.invoke(app, ["concalls", "run", "--since", "2026-01-01"])
    assert out.exit_code == 0 and "about 1 call once BSE/NSE copies are merged" in out.stdout
    assert "1 transcripts have no PDF yet" in out.stdout  # the fixture's, never downloaded
    run = run_job("concalls")
    assert run.status == "ok" and run.summary.startswith("skipped")


@pytest.mark.db
def test_stock_page_shows_calls(loaded, tmp_path, test_database_url, monkeypatch):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    transcript(loaded, LT, OCT)
    llm, _ = _llm(loaded, replying(answer()))
    cc.analyse_calls(loaded, llm, data_dir=tmp_path)

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.stock_page_body()", default_timeout=30
    )
    at.query_params["symbol"] = "LT"
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Q2 FY27: cautious tone" in text and "Watch Middle East collections" in text
    assert "Promise ledger" in text
