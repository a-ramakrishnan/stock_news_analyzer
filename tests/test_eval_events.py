import json
from datetime import datetime
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy.orm import Session
from test_llm import FakeAnthropic, settings, usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import doc

from stock_news_analyzer.agents import events as agent
from stock_news_analyzer.evals import events as ev
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import Event, EventFiling
from stock_news_analyzer.sources.announcements import IST

LT = "INE018A01030"
RATING = (
    "CARE Ratings has upgraded the long-term rating of the Company's bank facilities of "
    "Rs. 450 crore to CARE AA+ from CARE AA."
)


def event(event_type="credit_rating", value_cr=450.0, quote=RATING, written="Rs. 450 crore"):
    return {
        "event_type": event_type,
        "value_cr": value_cr,
        "value_as_written": written,
        "quote": quote,
    }


# ------------------------------------------------------------------ the grader


def test_grade_a_filing_read_right():
    g = ev.grade([event()], [event()], RATING)
    assert g == {"correct": 1.0, "detect": 1.0, "types": 1.0, "amounts": 1.0, "quotes": 1.0}


def test_grade_a_routine_filing():
    assert ev.grade([], [], "Trading window closure")["correct"] == 1.0
    g = ev.grade(
        [], [event("other", None, "Trading window closure", None)], "Trading window closure"
    )
    assert g["correct"] == 0 and g["detect"] == 0 and g["types"] == 0 and g["amounts"] == 0


def test_grade_mistakes():
    missed = ev.grade([event()], [], RATING)
    assert (missed["detect"], missed["types"], missed["amounts"], missed["quotes"]) == (0, 0, 0, 1)
    wrong_type = ev.grade([event()], [event("agreement")], RATING)
    assert wrong_type["detect"] == 1 and wrong_type["types"] == 0 and wrong_type["correct"] == 0
    lakh_slip = ev.grade([event()], [event(value_cr=4.5)], RATING)
    assert lakh_slip["types"] == 1 and lakh_slip["amounts"] == 0 and lakh_slip["correct"] == 0
    close = ev.grade([event(value_cr=450.0)], [event(value_cr=452.0)], RATING)
    assert close["amounts"] == 1  # within 1%
    made_up = ev.grade([event()], [event(quote="The rating was upgraded to AAA.")], RATING)
    assert made_up["quotes"] == 0 and made_up["correct"] == 1  # quotes are reported, not gated
    no_figure = ev.grade(
        [event()], [event(quote="CARE Ratings has upgraded the long-term")], RATING
    )
    assert no_figure["quotes"] == 0  # the quote must hold its amount
    two = ev.grade(
        [event("management_change", None, "x", None), event("management_change", None, "x", None)],
        [event("management_change", None, "x", None)],
        "x",
    )
    assert two["types"] == pytest.approx(2 / 3, abs=1e-3) and two["amounts"] == 0.5


# ------------------------------------------------------------------ cases from the database


def _seed(session):
    when = datetime(2026, 10, 20, 16, 0, tzinfo=IST)
    docs = {}
    for i, (doc_type, title, kind, review) in enumerate(
        [
            ("credit_rating", "Credit rating", "credit_rating", None),
            ("credit_rating", "Credit rating update", "credit_rating", "rejected"),
            ("board_outcome", "Change in directors", "management_change", None),
            ("board_outcome", "Capacity expansion", "capex", None),
        ]
    ):
        d = doc(session, LT, when.replace(minute=i), doc_type, title, RATING)
        session.add(
            Event(
                isin=LT,
                document_id=d.id,
                published_at=d.published_at,
                event_type=kind,
                headline=title,
                sentiment="positive",
                importance=3,
                quote=RATING,
                review=review,
                model="claude-haiku-5-5",
                prompt_version=agent.PROMPT_VERSION,
            )
        )
        session.add(EventFiling(document_id=d.id, isin=LT, status="extracted"))
        docs[title] = d
    for i in range(3):
        d = doc(
            session,
            LT,
            when.replace(hour=17, minute=i),
            "trading_window",
            f"Trading window closure {i}",
            "The trading window will be closed.",
        )
        session.add(EventFiling(document_id=d.id, isin=LT, status="no_event"))
    session.commit()
    return docs


@pytest.mark.db
def test_sample_freezes_filings_into_cases(loaded, tmp_path):  # noqa: F811
    docs = _seed(loaded)
    paths = ev.sample(loaded, with_events=3, without=2, folder=tmp_path)
    cases = ev.load_cases(tmp_path)
    strata = sorted(c.data["stratum"] for c in cases)
    assert len(paths) == 5 and strata.count("found:none") == 2
    assert "rejected:credit_rating" in strata  # the filings you rejected come first
    assert len({s for s in strata if s.startswith("found:") and s != "found:none"}) == 2
    case = next(c for c in cases if c.data["stratum"] == "rejected:credit_rating")
    assert case.data["document_id"] == docs["Credit rating update"].id
    assert case.expected == [] and not case.verified
    # the case gives the agent exactly what the stored filing gave it
    frozen, company = case.filing()
    stored = docs["Credit rating update"]
    assert agent.filing_text(frozen) == agent.filing_text(stored)
    assert agent._prompt([(frozen, company)]).count("<filing id=") == 1
    assert "text: |" in case.path.read_text()  # readable block text
    # sampling again adds nothing already there
    more = ev.sample(loaded, with_events=3, without=2, folder=tmp_path)
    assert not {p.name for p in more} & {p.name for p in paths}


def _reply_with(found_by_doc):
    """A fake model: for the filing in the prompt, the events in `found_by_doc`."""

    def reply(kwargs):
        prompt = kwargs["messages"][0]["content"]
        doc_id = int(prompt.split('<filing id="')[1].split('"')[0])
        found = found_by_doc.get(doc_id, [])
        if found == "broken":
            return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="max_tokens")
        items = [
            agent.EventItem(
                event_type=e["event_type"],
                headline="h",
                event_date=None,
                sentiment="positive",
                importance=3,
                value_cr=e["value_cr"],
                value_as_written=e["value_as_written"],
                value_kind=None,
                counterparty=None,
                person=None,
                role=None,
                action=None,
                rating_from=None,
                rating_to=None,
                stake_pct=None,
                shares=None,
                quote=e["quote"],
            )
            for e in found
        ]
        answer = agent.EventsAnswer(filings=[agent.FilingEvents(id=doc_id, events=items)])
        return SimpleNamespace(usage=usage(2000, 300), parsed_output=answer, stop_reason="end_turn")

    return reply


@pytest.mark.db
def test_draft_fills_answers_for_you_to_check(loaded, tmp_path):  # noqa: F811
    _seed(loaded)
    ev.sample(loaded, with_events=1, without=1, folder=tmp_path)
    cases = ev.load_cases(tmp_path)
    by_doc = {
        c.data["document_id"]: [event()] if "found:none" != c.data["stratum"] else [] for c in cases
    }
    client = FakeAnthropic(_reply_with(by_doc))
    llm = LLM(loaded, client=client, settings=settings())
    assert ev.draft(llm, cases, say=lambda _: None) == 2
    assert client.requests[0]["model"] == "claude-opus-5-5"
    again = ev.load_cases(tmp_path)
    positive = next(c for c in again if c.expected)
    assert positive.data["expected"]["drafted_by"] == "claude-opus-5-5" and not positive.verified
    assert positive.expected[0] == {
        "event_type": "credit_rating",
        "value_cr": 450.0,
        "value_as_written": "Rs. 450 crore",
        "headline": "h",
    }
    assert ev.draft(llm, again, say=lambda _: None) == 0  # drafted once
    assert "| 2 cases" not in ev.overview(again) and "2 cases: 1 with expected events" in (
        ev.overview(again)
    )


def _verified_cases(session, folder):
    _seed(session)
    ev.sample(session, with_events=2, without=1, folder=folder)
    for c in ev.load_cases(folder):
        has = c.data["stratum"] != "found:none"
        c.data["expected"] = {"verified": True, "events": [event()] if has else []}
        ev.save(c)
    return ev.load_cases(folder)


@pytest.mark.db
def test_run_grades_resumes_and_records_failures(loaded, tmp_path):  # noqa: F811
    cases = _verified_cases(loaded, tmp_path / "cases")
    pos = [c for c in cases if c.expected]
    neg = [c for c in cases if not c.expected][0]
    found = {
        pos[0].data["document_id"]: [event()],  # right
        pos[1].data["document_id"]: "broken",  # cut off: an error, not a zero
        neg.data["document_id"]: [event("other", None, "The trading window", None)],
    }
    client = FakeAnthropic(_reply_with(found))
    flow = tmp_path / "flow"
    bind = loaded.get_bind()
    kwargs = dict(
        variant="baseline",
        model="claude-haiku-5-5",
        reps=2,
        workers=2,
        flow=flow,
        say=lambda _: None,
    )

    def run(**kw):
        return ev.run(
            lambda: Session(bind),
            lambda s: LLM(s, client=client, settings=settings()),
            cases,
            **{**kwargs, **kw},
        )

    with pytest.raises(ev.HarnessChanged):
        run()
    summary = run(approve_harness=True)
    rows = [json.loads(x) for x in (flow / "baseline" / "results.jsonl").read_text().splitlines()]
    errors = [json.loads(x) for x in (flow / "baseline" / "errors.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and len(errors) == 2  # the broken case: 2 reps, both errors
    assert {e["class"] for e in errors} == {"bad_answer"}
    right = [r for r in rows if r["prompt_id"] == pos[0].id]
    assert all(r["grade"]["correct"] == 1 for r in right)
    wrong = [r for r in rows if r["prompt_id"] == neg.id]
    assert all(r["grade"]["detect"] == 0 for r in wrong)
    row = right[0]
    assert row["model"] == "claude-haiku-5-5" and row["usage"]["input_tokens"] == 2000
    assert (
        row["cost_usd"] > 0
        and row["status"] == "ok"
        and row["tags"][0].split(":")[0] in ("found", "rejected")
    )
    trace = json.loads((flow / "baseline" / "traces" / f"{pos[0].id}_rep0.json").read_text())
    assert [t["role"] for t in trace] == ["system", "user", "assistant"]
    assert summary["mean"]["correct"] == 0.5 and summary["recall"] == 1.0
    assert summary["specificity"] == 0.0 and summary["precision"] == 0.5
    assert "**Correct: 50%**" in (flow / "baseline" / "summary.md").read_text()
    state = json.loads((flow / "_state.json").read_text())
    assert state["metrics"][0] == {"id": "correct", "label": "Correct", "kind": "binary"}

    asked = len(client.requests)
    run()  # resume: only the failed attempts are tried again
    assert len(client.requests) - asked >= 2
    assert len((flow / "baseline" / "results.jsonl").read_text().splitlines()) == 4


@pytest.mark.db
def test_oracle_and_null_check_the_grader_for_free(loaded, tmp_path):  # noqa: F811
    cases = _verified_cases(loaded, tmp_path / "cases")
    common = dict(model="claude-haiku-5-5", reps=1, flow=tmp_path / "flow", say=lambda _: None)
    oracle = ev.run(None, None, cases, variant="v1", mode="oracle", **common)
    null = ev.run(None, None, cases, variant="v2", mode="null", **common)
    assert oracle["mean"]["correct"] == 1.0
    assert null["mean"]["correct"] == pytest.approx(1 / 3)  # only the routine filing
    assert yaml.safe_load(cases[0].path.read_text())["expected"]["verified"] is True
