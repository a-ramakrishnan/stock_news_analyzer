from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from test_concalls import LT
from test_llm import FakeAnthropic, settings
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_results import Q1, Q2, answer, replying, results_filing

from stock_news_analyzer.agents import results as rs
from stock_news_analyzer.evals import framework as fw
from stock_news_analyzer.evals import results as re_eval
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import QuarterlyResult

SPEC = re_eval.SPEC


def xbrl_q2(session, basis="consolidated"):
    """The quarter as the company filed it in XBRL: Rs 67,000 crore revenue, 4,400 profit."""
    session.add(
        QuarterlyResult(
            isin=LT,
            period="Q2 FY27",
            period_end=date(2026, 9, 30),
            months=3,
            basis=basis,
            primary=True,
            revenue_cr=Decimal("67000"),
            other_income_cr=Decimal("1200"),
            finance_costs_cr=Decimal("900"),
            depreciation_cr=Decimal("1100"),
            pbt_cr=Decimal("6000"),
            pat_cr=Decimal("4400"),
            eps=Decimal("31.20"),
            unit="crore",
            as_written={},
            model=rs.XBRL,
        )
    )
    session.commit()


@pytest.mark.db
def test_sample_takes_xbrl_quarters_with_a_results_pdf(loaded):  # noqa: F811
    xbrl_q2(loaded)
    filing = results_filing(loaded)
    added = fw.sample(loaded, SPEC, n=5)
    loaded.commit()
    assert len(added) == 1
    case = added[0]
    assert case.key == "LT-202609" and case.status == "verified"  # the XBRL is the answer
    assert case.drafted_by == "xbrl" and case.tags == ["consolidated", "Q2 FY27"]
    assert case.input["document_id"] == filing.id
    assert case.reference == {
        "period_end": "2026-09-30",
        "months": 3,
        "basis": "consolidated",
        "revenue": 67000.0,
        "other_income": 1200.0,
        "finance_costs": 900.0,
        "depreciation": 1100.0,
        "pbt": 6000.0,
        "pat": 4400.0,
        "eps": 31.2,
    }
    assert fw.sample(loaded, SPEC, n=5) == []  # nothing new


def _run_one(session, case, reply, tmp_path):
    client = FakeAnthropic(reply)
    session.refresh(case)
    session.expunge(case)
    bind = session.get_bind()
    summary = fw.run(
        lambda: Session(bind),
        lambda s: LLM(s, client=client, settings=settings()),
        SPEC,
        [case],
        model="claude-haiku-5-5",
        reps=1,
        flow=tmp_path,
        approve_harness=True,
        say=lambda _: None,
    )
    return summary, client


@pytest.mark.db
def test_a_quarter_read_right_from_the_pdf(loaded, tmp_path):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    loaded.commit()
    summary, client = _run_one(loaded, case, replying(answer([Q2, Q1])), tmp_path)
    assert summary["mean"] == {
        "correct": 1.0,
        "basis": 1.0,
        "revenue": 1.0,
        "pat": 1.0,
        "eps": 1.0,
        "fields": 1.0,
        "found": 1.0,
    }
    prompt = client.requests[0]["messages"][0]["content"]
    assert "Probably results for Q2 FY27" in prompt and "Revenue from operations" in prompt


@pytest.mark.db
def test_mistakes_are_caught(loaded, tmp_path):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    loaded.commit()
    output = {
        "is_results": True,
        "basis": "consolidated",
        "period_end": "2026-09-30",
        **{f: case.reference[f] for f in re_eval.FIELDS},
    }
    assert SPEC.grade(case, output)["correct"] == 1
    crore_for_lakh = {**output, "revenue": 670.0, "pat": 44.0}  # read lakh as crore
    g = SPEC.grade(case, crore_for_lakh)
    assert g["correct"] == 0 and g["revenue"] == 0 and g["pat"] == 0 and g["eps"] == 1
    assert g["fields"] == pytest.approx(5 / 7, abs=1e-3)
    rounded = {**output, "revenue": 67003.0}  # within 0.1%: a rounded statement
    assert SPEC.grade(case, rounded)["revenue"] == 1
    standalone = {**output, "basis": "standalone"}
    assert SPEC.grade(case, standalone)["correct"] == 0
    missing = {"is_results": True, "basis": "consolidated"}  # quarter not found
    g = SPEC.grade(case, missing)
    assert g == {
        "correct": 0.0,
        "basis": 1.0,
        "revenue": 0.0,
        "pat": 0.0,
        "eps": 0.0,
        "fields": 0.0,
        "found": 0.0,
    }
    assert SPEC.describe(missing) == ["quarter not found"]
    assert SPEC.describe(output) == [
        "consolidated 2026-09-30: revenue 67,000.00, PAT 4,400.00, EPS 31.20"
    ]
    assert SPEC.grade(case, SPEC.oracle(case))["correct"] == 1
    assert SPEC.grade(case, SPEC.null(case))["correct"] == 0


@pytest.mark.db
def test_a_figure_not_in_the_text_counts_as_missing(loaded, tmp_path):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    loaded.commit()
    made_up = Q2.model_copy(update={"pat": "4,41,000.00"})  # not in the statement
    summary, _ = _run_one(loaded, case, replying(answer([made_up])), tmp_path)
    assert summary["mean"]["pat"] == 0 and summary["mean"]["revenue"] == 1


@pytest.mark.db
def test_the_answer_keeps_the_readers_note_and_what_it_left_out(loaded, tmp_path):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    loaded.commit()
    made_up = Q2.model_copy(update={"pat": "4,41,000.00"})  # not in the statement
    reply = answer([made_up])
    out = SPEC._quarter(reply, case.reference, rs.statement_text(re_eval._filing(case.input)[0]))
    assert out["note"].startswith("Consolidated results") and out["unit"] == "lakh"
    assert out["not_in_text"] == {"pat": "4,41,000.00"} and out["pat"] is None
    lines = SPEC.describe(out)
    assert lines[0].startswith("consolidated 2026-09-30 in lakh: revenue 67,000.00")
    assert lines[1] == "written but not in the text, left out: PAT 4,41,000.00"
    assert SPEC.describe({"is_results": False, "note": "A covering letter."}) == [
        "no results read (A covering letter.)"
    ]
    assert SPEC.describe(case.reference)[0].startswith("consolidated 2026-09-30: revenue")


@pytest.mark.db
def test_diagnosis_says_where_the_figures_went(loaded, monkeypatch):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    loaded.commit()

    d = re_eval.diagnose(case)  # the lakh statement is in the excerpt: a misread is Haiku's
    assert d["verdict"] == "in_excerpt"
    assert d["fields"]["revenue"] == {"text": "lakh", "sent": "lakh"}
    assert d["fields"]["eps"] == {"text": "rupees", "sent": "rupees"}

    monkeypatch.setattr(re_eval.reader, "excerpt", lambda text: text[:60])
    d = re_eval.diagnose(case)  # in the PDF, but not in what the reader sends
    assert d["verdict"] == "outside_excerpt" and d["fields"]["pat"] == {
        "text": "lakh",
        "sent": None,
    }
    monkeypatch.undo()

    other = fw.EvalCase(
        key="x",
        title="x",
        input=case.input,
        reference={**case.reference, "revenue": 1234.5, "pat": 99.1},
    )
    assert re_eval.diagnose(other)["verdict"] == "not_in_text"
    blank = fw.EvalCase(
        key="y",
        title="y",
        input={**case.input, "text": "Covering letter."},
        reference=case.reference,
    )
    assert re_eval.diagnose(blank)["verdict"] == "no_text"

    md = re_eval.diagnosis_markdown(
        [re_eval.diagnose(case), re_eval.diagnose(other)], {"LT-202609": "0 of 3 right"}
    )
    assert "| LT-202609 | 0 of 3 right | lakh / lakh | lakh / lakh |" in md
    assert "- the figures aren't in the PDF's text (another document, or garbled text): 1" in md


def test_figures_are_found_in_any_unit_allowing_for_rounding():
    from decimal import Decimal as D

    lakh = {D("30742.37")}
    assert re_eval._written_as(307.42, lakh) == "lakh"  # XBRL rounds to 0.01 crore
    assert re_eval._written_as(67078.68, {D("67079")}) == "crore"  # a statement in whole crore
    assert re_eval._written_as(1988.53, {D("19885.3")}) == "million"
    assert re_eval._written_as(1988.53, {D("1989.9")}) is None
    assert re_eval._written_as(None, lakh) is None


@pytest.mark.db
def test_sampling_takes_only_a_pdf_that_holds_the_figures(loaded):  # noqa: F811
    from datetime import timedelta

    from test_results import OCT

    xbrl_q2(loaded)
    letter = results_filing(  # ranks first (a results title, longer text) but holds nothing
        loaded,
        when=OCT - timedelta(minutes=5),
        title="Financial Results Q2 - covering letter",
        text="Please find enclosed the results. " * 400,
    )
    statement = results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=5)[0]
    assert case.input["document_id"] == statement.id != letter.id


@pytest.mark.db
def test_a_quarter_whose_pdfs_lack_the_figures_is_not_sampled(loaded):  # noqa: F811
    xbrl_q2(loaded)
    results_filing(loaded, text="A scanned file with a few words. " * 40)
    assert fw.sample(loaded, SPEC, n=5) == []


@pytest.mark.db
def test_diagnose_excludes_cases_that_measure_the_pdf(
    loaded,  # noqa: F811
    test_database_url,
    monkeypatch,
):
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings

    xbrl_q2(loaded)
    results_filing(loaded)
    case = fw.sample(loaded, SPEC, n=1)[0]
    bad = fw.add_case(
        loaded,
        SPEC,
        fw.NewCase(
            key="LT-BAD",
            title="LT: garbled",
            input={**case.input, "document_id": 999},
            reference={**case.reference, "revenue": 1234.5, "pat": 99.1},
            drafted_by="xbrl",
        ),
    )
    fw.set_answer(bad, bad.reference, "verified", "test")
    from stock_news_analyzer.models import EvalRun

    loaded.add(  # a run on record: its variant is named after the exclusions are saved
        EvalRun(
            flow="results",
            variant="v1",
            model="m",
            cases=2,
            cases_verified=2,
            attempts=0,
            scores={},
        )
    )
    loaded.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(app, ["eval", "results", "diagnose", "--all", "--exclude-missing"])
    finally:
        get_settings.cache_clear()
    assert out.exit_code == 0, out.stdout
    assert "Excluded 1 cases" in out.stdout and "sample --n 1" in out.stdout
    assert "Cases v1 got wrong in its latest run (2)" in out.stdout
    loaded.expire_all()
    by_key = {c.key: c for c in fw.cases(loaded, SPEC)}
    assert by_key["LT-BAD"].status == "excluded" and by_key["LT-202609"].status == "verified"
    assert by_key["LT-BAD"].note.startswith("the figures aren't in the PDF's text")
