import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_concalls import LT, _llm
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import doc

from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import events as ev
from stock_news_analyzer.agents import qa
from stock_news_analyzer.models import (
    Document,
    DocumentCompany,
    Event,
    EventFiling,
    LlmCall,
    QuarterlyResult,
)
from stock_news_analyzer.sources.announcements import IST, event_candidate
from stock_news_analyzer.ui import queries

WHEN = datetime(2026, 10, 20, 17, 5, tzinfo=IST)
RATING_TEXT = (
    "Sub: Credit Rating. We wish to inform you that CARE Ratings Limited has upgraded the "
    "long-term rating of the Company's bank facilities of Rs. 5,000 crore to CARE AAA; Stable "
    "from CARE AA+; Positive. The rating letter is enclosed."
)
CAPEX_TEXT = (
    "The Board approved a capital expenditure of Rs. 450 crore for a new plant at Hosur with "
    "a capacity of 2 million units a year, to be commissioned by March 2028."
)


def rating(**kw):
    fields = dict(
        event_type="credit_rating",
        headline="CARE upgraded the long-term rating to AAA from AA+",
        event_date=None,
        sentiment="positive",
        importance=3,
        value_cr=5000,
        value_as_written="Rs. 5,000 crore",
        value_kind="rated bank facilities",
        counterparty="CARE Ratings Limited",
        person=None,
        role=None,
        action="upgraded",
        rating_from="CARE AA+; Positive",
        rating_to="CARE AAA; Stable",
        stake_pct=None,
        quote="CARE Ratings Limited has upgraded the long-term rating of the Company's bank "
        "facilities of Rs. 5,000 crore to CARE AAA; Stable from CARE AA+; Positive.",
    )
    return ev.EventItem(**{**fields, **kw})


def capex(**kw):
    fields = dict(
        event_type="capex",
        headline="Rs 450 crore plant at Hosur, to be commissioned by March 2028",
        event_date="2028-03-31",
        sentiment="positive",
        importance=3,
        value_cr=450,
        value_as_written="Rs. 450 crore",
        value_kind="capex",
        counterparty=None,
        person=None,
        role=None,
        action="approved",
        rating_from=None,
        rating_to=None,
        stake_pct=None,
        quote="The Board approved a capital expenditure of Rs. 450 crore for a new plant at Hosur",
    )
    return ev.EventItem(**{**fields, **kw})


def verdict(**kw):
    fields = dict(
        about_company=True,
        real_event=True,
        event_type_correct=True,
        correct_event_type="capex",
        value_correct=True,
        correct_value_as_written=None,
        correct_value_cr=None,
        note="Matches the filing.",
    )
    return qa.Verdict(**{**fields, **kw})


def reply(events=None, verdicts=(), bad=False):
    """Answers extraction calls with `events` for every filing (none for a filing whose id is
    in `events` as a dict key mapping to its own list), and second passes with `verdicts`."""
    queue = list(verdicts)

    def answer(kwargs):
        prompt = kwargs["messages"][0]["content"]
        if kwargs["output_format"] is ev.EventsAnswer:
            ids = [int(i) for i in re.findall(r'<filing id="(\d+)"', prompt)]
            if bad and len(ids) > 1:
                return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="max_tokens")
            per = events if isinstance(events, dict) else None
            every = [rating()] if events is None else events
            parsed = ev.EventsAnswer(
                filings=[
                    ev.FilingEvents(id=i, events=per.get(i, []) if per is not None else every)
                    for i in ids
                ]
            )
        else:
            if not queue:  # the API is unreachable
                import anthropic
                import httpx

                raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
            parsed = queue.pop(0)
        return SimpleNamespace(usage=usage(3000, 300), parsed_output=parsed, stop_reason="end_turn")

    return answer


def filing(session, text=RATING_TEXT, when=WHEN, doc_type="credit_rating", title="Credit Rating"):
    return doc(session, LT, when, doc_type, title, text)


def nse_copy(session, original, text):
    d = Document(
        source="nse",
        source_id=f"nse-{original.id}",
        doc_type=original.doc_type,
        title=original.title,
        subject=original.subject,
        published_at=original.published_at + timedelta(minutes=10),
        text=text,
        text_status="ok",
        raw={},
    )
    session.add(d)
    session.flush()
    session.add(DocumentCompany(document_id=d.id, isin=LT))
    session.commit()
    return d


def quarters(session, revenue=1000):
    """Four quarters of L&T revenue before the filings: Rs 4,000 crore a year."""
    for end in (date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)):
        session.add(
            QuarterlyResult(
                isin=LT,
                period=f"Q {end}",
                period_end=end,
                months=3,
                basis="consolidated",
                primary=True,
                revenue_cr=Decimal(revenue),
                unit="crore",
                as_written={},
                model="xbrl",
            )
        )
    session.commit()


# --- which filings are read ---------------------------------------------------------


def test_event_candidates():
    assert event_candidate("credit_rating", "has informed the Exchange about Credit Rating", "")
    assert event_candidate("other", "Appointment of Chief Financial Officer", None)
    assert event_candidate("board_meeting", "Board meeting to consider fund raising via QIP", "")
    assert event_candidate("insider_trading", "Disclosure under SAST regulations", "")
    assert event_candidate("other", "Fire at the Company's Pune plant", "")
    assert not event_candidate("insider_trading", "Closure of Trading Window", "")
    assert not event_candidate("other", "Certificate under Regulation 74(5) of SEBI (DP)", "")
    assert not event_candidate("other", "Copy of newspaper publication", "")
    assert not event_candidate("other", "Intimation of ESG Rating", "")
    assert not event_candidate("credit_rating", "ESG Rating by NSE Sustainability Ratings", "")
    assert not event_candidate("other", "General updates", "")
    assert not event_candidate("other", "Revised operating amount", "")  # not "rating", "mou"
    assert not event_candidate("results", "Appointment of auditor and financial results", "")
    assert not event_candidate("order_win", "Receipt of work order", "")


def test_amounts_as_written_in_crore():
    assert qa.to_crore("Rs. 450 crore") == 450
    assert qa.to_crore("INR 1,200 million") == 120
    assert qa.to_crore("Rs 75 lakh") == Decimal("0.75")
    assert qa.to_crore("₹ 1.2 billion") == 120
    assert qa.to_crore("Rs 1.5 lakh crore") == 150_000
    assert qa.to_crore("Rs. 5,00,00,000") == 5
    assert qa.to_crore("Rs. 450 crore (approx.)") == 450
    assert qa.to_crore("Rs. 4,55,000") == Decimal("0.0455")
    assert qa.to_crore("USD 20 million") is None  # foreign currency: not converted
    assert qa.to_crore("450") is None  # no unit


def test_amounts_shown_with_their_meaning():
    e = Event(event_type="fundraise", value_cr=Decimal("249.04"), materiality=0.031)
    assert ev.amount(e) == "Rs 249 cr (3% of revenue)"
    e = Event(event_type="credit_rating", value_cr=Decimal(12000), materiality=None)
    assert ev.amount(e) == "Rs 12,000 cr rated"
    assert ev.amount(Event(event_type="capex", value_cr=None)) == ""
    # Small amounts in lakh; small shares of revenue to a tenth of a percent.
    fine = Event(event_type="legal_regulatory", value_cr=Decimal("0.0455"), materiality=0.00001)
    assert ev.amount(fine) == "Rs 4.6 lakh (under 0.1% of revenue)"
    ncd = Event(event_type="fundraise", value_cr=Decimal(500), materiality=0.0019)
    assert ev.amount(ncd) == "Rs 500 cr (0.2% of revenue)"
    assert ev.amount(Event(event_type="capex", value_cr=Decimal("0.5"))) == "Rs 50 lakh"
    # Under Rs 1 crore with the figure as written: the filing's own words.
    written = Event(
        event_type="legal_regulatory", value_cr=Decimal(0), value_as_written="Rs 39,000"
    )
    assert ev.amount(written) == "Rs 39,000"


# --- extraction and QA ----------------------------------------------------------------


@pytest.mark.db
def test_a_rating_filed_on_both_exchanges_is_read_once_and_passes_qa(loaded):  # noqa: F811
    bse = filing(loaded)
    nse_copy(loaded, bse, RATING_TEXT[:-30])
    quarters(loaded)
    llm, client = _llm(loaded, reply())
    result = ev.run(loaded, llm)
    assert (result.filings, result.events, result.duplicates, result.errors) == (1, 1, 1, [])
    assert client.requests[0]["model"] == "claude-haiku-5-5"
    assert len(client.requests) == 1  # clean and not important: no second pass
    e = loaded.query(Event).one()
    assert e.document_id == bse.id and e.prompt_version == ev.PROMPT_VERSION
    assert (e.qa_status, e.qa_notes, e.quote_found) == ("passed", [], True)
    assert e.value_cr == 5000 and e.materiality is None  # rated debt isn't spending
    statuses = sorted(f.status for f in loaded.query(EventFiling))
    assert statuses == ["duplicate", "extracted"]
    # Only the fixture's own rating filing is left: its PDF isn't downloaded.
    assert [(d.source, d.text_status) for d, _ in ev.pending(loaded)] == [("nse", "pending")]
    # The fixture's own NSE rating filing has no PDF; without `fetch` it waits.
    assert result.waiting == 1


@pytest.mark.db
def test_pdfs_not_downloaded_are_fetched_first(loaded):  # noqa: F811
    fetched = []

    def fetch(d, isin):
        d.text, d.text_status = RATING_TEXT, "ok"
        fetched.append((d.id, isin))
        return True

    llm, _ = _llm(loaded, reply())
    result = ev.run(loaded, llm, fetch=fetch)
    assert result.fetched == 1 and fetched[0][1] == LT
    assert (result.waiting, result.events) == (0, 1)


@pytest.mark.db
def test_routine_filings_give_no_event(loaded):  # noqa: F811
    filing(
        loaded,
        "Intimation of change in the e-mail address.",
        doc_type="other",
        title="Change of address update",
    )
    llm, _ = _llm(loaded, reply(events=[]))
    result = ev.run(loaded, llm)
    # The title names no event, so it isn't even read.
    assert result.filings == 0
    filing(loaded, "No change in the rating.", title="Credit Rating")
    result = ev.run(loaded, llm)
    assert (result.filings, result.no_event, result.events) == (1, 1, 0)


@pytest.mark.db
def test_unit_mistake_is_corrected_and_confirmed(loaded):  # noqa: F811
    quarters(loaded)
    filing(loaded, CAPEX_TEXT, doc_type="other", title="Capital expenditure for new plant")
    # The model said 4,500 for "Rs. 450 crore".
    llm, client = _llm(loaded, reply(events=[capex(value_cr=4500)], verdicts=[verdict()]))
    result = ev.run(loaded, llm)
    e = loaded.query(Event).one()
    assert e.value_cr == 450 and e.materiality == pytest.approx(0.1125)
    assert any(n.startswith("unit: 'Rs. 450 crore' is Rs 450 crore") for n in e.qa_notes)
    assert e.qa_status == "passed" and e.qa_model == "claude-sonnet-5-5"
    assert "confirmed by the second pass" in e.qa_notes
    assert client.requests[1]["model"] == "claude-sonnet-5-5"
    assert (result.passed, result.second_pass) == (1, 1)
    assert loaded.query(LlmCall).filter_by(task="qa").count() == 1


@pytest.mark.db
def test_unconfirmed_events_go_to_the_review_queue(loaded):  # noqa: F811
    filing(loaded, CAPEX_TEXT, doc_type="other", title="Capital expenditure for new plant")
    made_up = capex(
        value_cr=900, value_as_written="Rs. 900 crore", quote="A plant costing Rs 900 crore."
    )
    wrong = verdict(real_event=False, note="The filing gives Rs 450 crore, not 900.")
    llm, _ = _llm(loaded, reply(events=[made_up], verdicts=[wrong]))
    result = ev.run(loaded, llm)
    e = loaded.query(Event).one()
    assert e.qa_status == "failed" and result.rejected == 1
    assert "quote not found in the filing" in e.qa_notes
    assert "amount 'Rs. 900 crore' not found in the filing" in e.qa_notes
    assert [x.id for x, _ in qa.review_queue(loaded)] == [e.id]
    assert queries.events(loaded, LT).empty  # failed events are hidden...
    qa.decide(loaded, e.id, accept=True, note="checked the PDF")
    assert qa.review_queue(loaded) == []
    assert queries.events(loaded, LT)["qa"].tolist() == ["you accepted it"]  # ...until accepted
    qa.decide(loaded, e.id, accept=False)
    assert queries.events(loaded, LT).empty


@pytest.mark.db
def test_the_second_pass_corrects_the_amount(loaded):  # noqa: F811
    filing(loaded, CAPEX_TEXT, doc_type="other", title="Capital expenditure for new plant")
    llm, _ = _llm(
        loaded,
        reply(
            events=[capex(value_cr=2, value_as_written="2 million")],
            verdicts=[
                verdict(
                    value_correct=False,
                    correct_value_as_written="Rs. 450 crore",
                    correct_value_cr=450,
                )
            ],
        ),
    )
    ev.run(loaded, llm)
    e = loaded.query(Event).one()
    assert (e.value_cr, e.value_as_written, e.qa_status) == (450, "Rs. 450 crore", "passed")
    assert "amount corrected to 'Rs. 450 crore' by the second pass" in e.qa_notes


@pytest.mark.db
def test_flagged_without_a_second_pass_when_the_api_fails(loaded):  # noqa: F811
    filing(loaded, CAPEX_TEXT, doc_type="other", title="Capital expenditure for new plant")
    llm, _ = _llm(loaded, reply(events=[capex(event_date="1999-01-01")], verdicts=[]))
    result = ev.run(loaded, llm)  # the verdict queue is empty: the second pass errors
    e = loaded.query(Event).one()
    assert e.qa_status == "flagged" and e.event_date is None
    assert any("far from the filing" in n for n in e.qa_notes)
    assert result.errors and result.flagged == 1
    assert queries.events(loaded, LT)["qa"].tolist() == ["unchecked"]


@pytest.mark.db
def test_required_fields_and_plausibility(loaded):  # noqa: F811
    quarters(loaded, revenue=100)  # Rs 400 crore a year: a Rs 450 crore plant is 1.1x
    filing(loaded)
    filing(loaded, CAPEX_TEXT, when=WHEN + timedelta(days=3), doc_type="other", title="New plant")
    events = {}
    llm, _ = _llm(loaded, reply(events=events, verdicts=[verdict(), verdict()]))
    rows = [(d, c) for d, c in ev.pending(loaded) if d.text_status == "ok"]
    events[rows[0][0].id] = [rating(rating_to=None)]
    events[rows[1][0].id] = [capex()]
    ev.run(loaded, llm)
    rated, plant = loaded.query(Event).order_by(Event.published_at).all()
    assert rated.qa_notes[0] == "missing rating_to"
    assert plant.qa_notes[0] == "amount is 1.1 times a year's revenue"
    assert plant.materiality == pytest.approx(1.125)


@pytest.mark.db
def test_the_same_event_from_a_later_filing_is_a_repeat(loaded):  # noqa: F811
    filing(loaded)
    filing(loaded, RATING_TEXT + " Press release.", when=WHEN + timedelta(days=5))
    llm, _ = _llm(loaded, reply())
    result = ev.run(loaded, llm)
    assert result.events == 2 and result.same_event == 1
    first, second = loaded.query(Event).order_by(Event.published_at).all()
    assert (first.qa_status, second.qa_status, second.duplicate_of) == (
        "passed",
        "duplicate",
        first.id,
    )
    assert len(queries.events(loaded, LT)) == 1


@pytest.mark.db
def test_a_spoilt_batch_is_read_filing_by_filing(loaded):  # noqa: F811
    filing(loaded)
    filing(loaded, CAPEX_TEXT, when=WHEN + timedelta(days=3), doc_type="other", title="New plant")
    llm, client = _llm(loaded, reply(bad=True))
    result = ev.extract(loaded, llm)
    assert result.events == 2 and result.calls == 3
    assert len(client.requests) == 3


@pytest.mark.db
def test_digest_lists_important_events(loaded):  # noqa: F811
    filing(loaded)
    llm, _ = _llm(loaded, reply(events=[rating(importance=4)], verdicts=[verdict()]))
    ev.run(loaded, llm)
    now = datetime.now(IST)
    md = dg.build_digest(loaded, now - timedelta(days=1), now + timedelta(minutes=1)).markdown
    assert "## Events" in md
    assert "- LT 20 Oct, credit rating, positive: CARE upgraded the long-term rating" in md
    assert "(Rs 5,000 cr rated)" in md  # the debt rated, not money raised


@pytest.mark.db
def test_coverage_and_reset(loaded):  # noqa: F811
    filing(loaded)
    llm, _ = _llm(loaded, reply())
    ev.run(loaded, llm)
    row = next(r for r in ev.coverage(loaded) if r["symbol"] == "LT")
    assert (row["filings"], row["extracted"], row["no_pdf"], row["passed"]) == (2, 1, 1, 1)
    assert ev.reset(loaded, "LT") == 2  # the event and its filing
    assert loaded.query(Event).count() == 0
