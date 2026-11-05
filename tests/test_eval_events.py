import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy.orm import Session
from test_llm import FakeAnthropic, settings, usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import doc

from stock_news_analyzer.agents import events as agent
from stock_news_analyzer.evals import events as ev
from stock_news_analyzer.evals import framework as fw
from stock_news_analyzer.evals import registry
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import EvalCase, EvalResult, EvalRun, Event, EventFiling
from stock_news_analyzer.sources.announcements import IST

LT = "INE018A01030"
SPEC = ev.SPEC
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
    assert ev.grade([event(value_cr=450.0)], [event(value_cr=452.0)], RATING)["amounts"] == 1
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


def test_the_registry_lists_every_eval():
    specs = registry()
    assert list(specs) == ["events", "results"]
    assert specs["events"].agent == "events" and specs["results"].needs_checking is False
    for spec in specs.values():
        assert spec.metrics[0]["kind"] == "binary" and spec.metrics[0]["id"] == "correct"


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
def test_sample_freezes_filings_into_cases(loaded):  # noqa: F811
    docs = _seed(loaded)
    added = fw.sample(loaded, SPEC, n=5)
    loaded.commit()
    tags = sorted(c.tags[0] for c in added)
    assert len(added) == 5 and tags.count("found:none") == 2
    assert "rejected:credit_rating" in tags  # the filings you rejected come first
    assert all(c.status == "new" and c.reference is None for c in added)
    case = next(c for c in added if c.tags[0] == "rejected:credit_rating")
    assert case.key == f"doc{docs['Credit rating update'].id}" and case.source == "rejected"
    # the case gives the agent exactly what the stored filing gave it
    frozen, company = ev.filing(case.input)
    stored = docs["Credit rating update"]
    assert agent.filing_text(frozen) == agent.filing_text(stored)
    assert agent._prompt([(frozen, company)]).count("<filing id=") == 1
    # sampling again adds only new filings
    more = fw.sample(loaded, SPEC, n=5)
    assert not {c.key for c in more} & {c.key for c in added}
    assert "5 cases: 5 new." in fw.overview(SPEC, added)


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
def test_draft_fills_answers_and_keeps_history(loaded):  # noqa: F811
    _seed(loaded)
    added = fw.sample(loaded, SPEC, n=2)
    loaded.commit()
    by_doc = {c.input["document_id"]: [event()] if c.tags[0] != "found:none" else [] for c in added}
    client = FakeAnthropic(_reply_with(by_doc))
    llm = LLM(loaded, client=client, settings=settings())
    assert fw.draft(loaded, SPEC, llm, "claude-opus-5-5", say=lambda _: None) == 2
    assert client.requests[0]["model"] == "claude-opus-5-5"
    positive = next(c for c in fw.cases(loaded, SPEC) if c.reference["events"])
    assert positive.status == "draft" and positive.drafted_by == "claude-opus-5-5"
    assert positive.reference["events"][0] == {
        "event_type": "credit_rating",
        "value_cr": 450.0,
        "value_as_written": "Rs. 450 crore",
        "headline": "h",
    }
    assert positive.history[0]["status"] == "new"  # what it was before the draft
    assert fw.draft(loaded, SPEC, llm, "claude-opus-5-5", say=lambda _: None) == 0
    fw.set_answer(positive, {"events": []}, "verified", "you", "not an event after all")
    assert positive.status == "verified" and len(positive.history) == 2
    assert positive.history[-1]["reference"]["events"][0]["value_cr"] == 450.0
    with pytest.raises(ValueError):
        fw.set_answer(positive, None, "maybe", "you")


@pytest.mark.db
def test_draft_stops_cleanly_on_an_api_error_and_continues(loaded):  # noqa: F811
    import anthropic
    import httpx

    _seed(loaded)
    fw.sample(loaded, SPEC, n=3)
    loaded.commit()
    calls = []

    def reply(kwargs):
        calls.append(1)
        if len(calls) == 2:  # e.g. the credit balance ran out
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        return _reply_with({})(kwargs)

    llm = LLM(loaded, client=FakeAnthropic(reply), settings=settings())
    said = []
    assert fw.draft(loaded, SPEC, llm, "claude-opus-5-5", say=said.append) == 1
    assert said[-1].startswith("1 drafted this time; run draft again to continue from")
    assert fw.overview(SPEC, fw.cases(loaded, SPEC)).count("*not drafted*") == 2
    assert fw.draft(loaded, SPEC, llm, "claude-opus-5-5", say=said.append) == 2  # the rest
    assert "*not drafted*" not in fw.overview(SPEC, fw.cases(loaded, SPEC))


@pytest.mark.db
def test_files_from_step_33_are_read_and_written_back(loaded, tmp_path):  # noqa: F811
    old = {
        "id": "doc12",
        "document_id": 12,
        "company": "Larsen & Toubro Limited",
        "symbol": "LT",
        "isin": LT,
        "published_at": "2026-10-20T16:00:00+05:30",
        "doc_type": "credit_rating",
        "stratum": "found:credit_rating",
        "title": "Credit rating",
        "subject": None,
        "text_status": "ok",
        "text": RATING,
        "expected": {
            "verified": True,
            "drafted_by": "claude-opus-5-5",
            "events": [{"event_type": "credit_rating", "value_cr": 450.0}],
            "note": "checked",
        },
    }
    undrafted = {
        **old,
        "id": "doc13",
        "document_id": 13,
        "expected": {"verified": False, "drafted_by": None, "events": [], "note": ""},
    }
    for data in (old, undrafted):
        (tmp_path / f"{data['id']}.yaml").write_text(yaml.dump(data))
    assert fw.import_files(loaded, SPEC, tmp_path) == 2
    by_key = {c.key: c for c in fw.cases(loaded, SPEC)}
    assert by_key["doc12"].status == "verified" and by_key["doc12"].note == "checked"
    assert by_key["doc12"].reference == {
        "events": [{"event_type": "credit_rating", "value_cr": 450.0}]
    }
    assert by_key["doc12"].tags == ["found:credit_rating", "credit_rating"]
    assert by_key["doc13"].status == "new" and by_key["doc13"].reference is None
    assert fw.import_files(loaded, SPEC, tmp_path) == 0  # nothing changed
    out = tmp_path / "out"
    assert fw.export(loaded, SPEC, out) == 2
    written = yaml.safe_load((out / "doc12.yaml").read_text())
    assert written["status"] == "verified" and written["input"]["document_id"] == 12
    written["status"], written["note"] = "excluded", "a duplicate"
    (out / "doc12.yaml").write_text(yaml.dump(written))
    assert fw.import_files(loaded, SPEC, out) == 1
    assert by_key["doc12"].status == "excluded" and by_key["doc12"].history[-1]["by"] == "file"


# ------------------------------------------------------------------ running


def _verified(session):
    _seed(session)
    added = fw.sample(session, SPEC, n=3)
    for c in added:
        events = [event()] if c.tags[0] != "found:none" else []
        fw.set_answer(c, {"events": events}, "verified", "test")
    session.commit()
    items = fw.cases(session, SPEC)
    for c in items:
        session.expunge(c)
    return items


@pytest.mark.db
def test_run_grades_records_resumes_and_keeps_failures_apart(loaded, tmp_path):  # noqa: F811
    from stock_news_analyzer.ui import queries

    items = _verified(loaded)
    pos = [c for c in items if c.reference["events"]]
    neg = next(c for c in items if not c.reference["events"])
    found = {
        pos[0].input["document_id"]: [event()],  # right
        pos[1].input["document_id"]: "broken",  # cut off: an error, not a zero
        neg.input["document_id"]: [event("other", None, "The trading window", None)],
    }
    client = FakeAnthropic(_reply_with(found))
    flow = tmp_path / "flow"
    bind = loaded.get_bind()

    def run(**kw):
        return fw.run(
            lambda: Session(bind),
            lambda s: LLM(s, client=client, settings=settings()),
            SPEC,
            items,
            **{
                "model": "claude-haiku-5-5",
                "reps": 2,
                "workers": 2,
                "flow": flow,
                "say": lambda _: None,
                **kw,
            },
        )

    with pytest.raises(fw.HarnessChanged):
        run()
    summary = run(approve_harness=True)
    rows = [json.loads(x) for x in (flow / "baseline" / "results.jsonl").read_text().splitlines()]
    errors = [json.loads(x) for x in (flow / "baseline" / "errors.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and len(errors) == 2 and {e["class"] for e in errors} == {"bad_answer"}
    right = [r for r in rows if r["prompt_id"] == pos[0].key]
    assert all(r["grade"]["correct"] == 1 for r in right)
    assert right[0]["meta"]["expected"] == ["credit_rating Rs 450 cr"]
    assert right[0]["model"] == "claude-haiku-5-5" and right[0]["usage"]["input_tokens"] == 2000
    assert all(r["grade"]["detect"] == 0 for r in rows if r["prompt_id"] == neg.key)
    trace = json.loads((flow / "baseline" / "traces" / f"{pos[0].key}_rep0.json").read_text())
    assert [t["role"] for t in trace] == ["system", "user", "assistant"]
    assert summary["mean"]["correct"] == 0.5
    assert summary["stats"] == {"Recall": 1.0, "Precision": 0.5, "Specificity": 0.0}
    assert "**Correct: 50%**" in (flow / "baseline" / "summary.md").read_text()

    with Session(bind) as check:
        run_row = check.query(EvalRun).one()
        assert (run_row.flow, run_row.attempts, run_row.errors, run_row.cases_verified) == (
            "events",
            4,
            2,
            3,
        )
        assert run_row.scores["passed"] == 1 and run_row.scores["stats"]["Recall"] == 1.0
        assert run_row.harness == fw.harness_digest(SPEC)
        assert check.query(EvalResult).filter(EvalResult.error.isnot(None)).count() == 2
        overview = queries.eval_overview(check)["events"]
        assert overview["current"]["correct"] == 0.5 and overview["cases"]["verified"] == 3
        listed = queries.eval_cases(check, run_row.id)
        assert [c["passing"] for c in listed] == [False, False, True]  # failing first
        wrong = next(c for c in listed if c["runs"] and not c["passing"])
        assert wrong["detail"] == {"expected": [], "found": ["other: h"]}

    asked = len(client.requests)
    run()  # resume: only the failed attempts are tried again
    assert len(client.requests) - asked >= 2
    assert len((flow / "baseline" / "results.jsonl").read_text().splitlines()) == 4


@pytest.mark.db
def test_oracle_and_null_check_the_grader_for_free(loaded, tmp_path):  # noqa: F811
    items = _verified(loaded)
    common = dict(model="claude-haiku-5-5", reps=1, flow=tmp_path / "flow", say=lambda _: None)
    oracle = fw.run(None, None, SPEC, items, variant="v1", mode="oracle", **common)
    null = fw.run(None, None, SPEC, items, variant="v2", mode="null", **common)
    assert oracle["mean"]["correct"] == 1.0
    assert null["mean"]["correct"] == pytest.approx(1 / 3)  # only the routine filing


def test_runnable_holds_back_unchecked_and_excluded_cases():
    def case(key, status, ref=True):
        return EvalCase(key=key, status=status, reference={"events": []} if ref else None)

    items = [
        case("a", "verified"),
        case("b", "draft"),
        case("c", "new", False),
        case("d", "excluded"),
    ]
    chosen, waiting = fw.runnable(items, unverified=False)
    assert [c.key for c in chosen] == ["a"] and waiting == ["b", "c"]
    chosen, _ = fw.runnable(items, unverified=True)
    assert [c.key for c in chosen] == ["a", "b"]  # a case needs an answer to be run


# ------------------------------------------------------------------ the page


@pytest.mark.db
def test_the_agent_evals_page_shows_runs(loaded, test_database_url, monkeypatch, tmp_path):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    for variant, correct, passed in (
        ("baseline", 0.70, 28),
        ("baseline", 0.80, 32),
        ("v1", 0.9, 36),
    ):
        run = EvalRun(
            flow="events",
            variant=variant,
            model="claude-haiku-5-5",
            cases=40,
            cases_verified=38,
            attempts=120,
            errors=1,
            scores={
                "correct": correct,
                "detect": 0.95,
                "types": 0.9,
                "amounts": 0.85,
                "quotes": 0.97,
                "margin": 0.09,
                "passed": passed,
                "failed": 40 - passed,
                "stats": {"Recall": 0.96, "Precision": 0.9, "Specificity": 0.8},
            },
            cost_usd=Decimal("0.05"),
        )
        loaded.add(run)
        loaded.flush()
        loaded.add(
            EvalResult(
                run_id=run.id,
                case_id="doc1",
                rep=0,
                title="LT: Credit rating",
                tags=["found:credit_rating", "credit_rating"],
                grade={"correct": 0, "detect": 1, "types": 1, "amounts": 0, "quotes": 1},
                detail={
                    "expected": ["credit_rating Rs 450 cr"],
                    "found": ["credit_rating Rs 4.5 cr"],
                },
            )
        )
    loaded.add(
        EvalCase(
            dataset="results",
            key="LT-202609",
            source="sample",
            input={},
            reference={"basis": "consolidated"},
            status="verified",
            history=[],
        )
    )
    loaded.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.evals_page()", default_timeout=30
    )
    at.run()
    assert not at.exception, at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Agents with an eval"] == "2 of 10"
    assert values["Fully correct"] == "80%" and values["Cases failing"] == "8"
    assert any("doc1" in e.label for e in at.expander)
    captions = " ".join(c.value for c in at.caption)
    assert "1 cases: 1 checked" in captions and "sna eval results run" in captions
    get_settings.cache_clear()


def test_step_34_details_still_show():
    from stock_news_analyzer.ui.app import _eval_detail

    old = {
        "expected_events": [{"event_type": "capex", "value_cr": 14}],
        "found_events": [{"event_type": "capex", "value_cr": 1400, "headline": "Plant"}],
    }
    assert _eval_detail(old) == (["capex Rs 14 cr"], ["capex Rs 1,400 cr: Plant"])
    assert _eval_detail({"expected": ["a"], "found": []}) == (["a"], [])
