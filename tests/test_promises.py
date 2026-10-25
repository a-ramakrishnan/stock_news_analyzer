import re
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from test_concalls import LT, OCT, _llm, answer, replying, transcript
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import concalls as cc
from stock_news_analyzer.agents import promises as pl
from stock_news_analyzer.models import (
    Concall,
    Document,
    DocumentCompany,
    LlmCall,
    Promise,
    PromiseCheck,
)
from stock_news_analyzer.sources.announcements import IST

FEB = date(2027, 2, 15)  # after the Hyderabad plant's due date (31 Dec 2026)
APR = date(2027, 4, 1)  # after its results window too (due date + 75 days: 16 Mar 2027)


def filing(session, when, doc_type="results", title="Financial results Q3 FY27", text=None):
    doc = Document(
        source="bse",
        source_id=f"f-{doc_type}-{when:%Y%m%d%H%M}",
        doc_type=doc_type,
        title=title,
        subject=title,
        published_at=when,
        text=text or "Revenue up 18%. The Hyderabad plant was commissioned in December 2026.",
        text_status="ok",
        raw={},
    )
    session.add(doc)
    session.flush()
    session.add(DocumentCompany(document_id=doc.id, isin=LT))
    session.commit()
    return doc


@pytest.fixture
def ledger(loaded, tmp_path):  # noqa: F811
    """L&T's Q2 FY27 call read: one promise, the Hyderabad plant by Q3 FY27 (31 Dec 2026)."""
    transcript(loaded, LT, OCT)
    llm, _ = _llm(loaded, replying(answer()))
    cc.analyse_calls(loaded, llm, data_dir=tmp_path)
    return loaded


def verdicts(verdict="kept", extra_ids=()):
    def reply(kwargs):
        prompt = kwargs["messages"][0]["content"]
        promise_ids = [int(i) for i in re.findall(r'<promise id="(\d+)"', prompt)]
        doc_ids = [int(i) for i in re.findall(r'<document id="(\d+)"', prompt)]
        items = [
            pl.Verdict(
                id=i,
                verdict=verdict,
                note="Commissioned in December 2026, per the Q3 results.",
                evidence=doc_ids[:1] + [999_999],
            )
            for i in promise_ids + list(extra_ids)
        ]
        return SimpleNamespace(
            usage=usage(8000, 500),
            parsed_output=pl.CheckAnswer(verdicts=items),
            stop_reason="end_turn",
        )

    return reply


@pytest.mark.db
def test_a_promise_past_its_date_is_settled_from_later_results(ledger):
    results = filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST))
    filing(
        ledger,
        datetime(2027, 1, 30, 17, 5, tzinfo=IST),
        doc_type="other",
        title="Board meeting outcome",
        text="Routine matters.",
    )  # not evidence
    assert pl.due(ledger, today=date(2026, 12, 1)) == []  # not due yet
    [(company, promises)] = pl.due(ledger, today=FEB)
    assert company.nse_symbol == "LT" and [p.due_date for p in promises] == [date(2026, 12, 31)]

    llm, client = _llm(ledger, verdicts(extra_ids=[123_456]))
    result = pl.check_promises(ledger, llm, today=FEB)
    assert (result.checked, result.settled, result.calls, result.errors) == (1, 1, 1, [])
    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5" and request["output_config"] == {
        "effort": "medium"
    }
    prompt = request["messages"][0]["content"]
    assert 'due="31 Dec 2026"' in prompt and "Hyderabad plant commissioned by Q3 FY27" in prompt
    assert f'<document id="{results.id}" kind="results" date="30 Jan 2027">' in prompt
    assert "Board meeting outcome" not in prompt  # not results and no telling words in the title
    assert "Q2 FY27 earnings call" not in prompt  # before the evidence window

    promise = ledger.query(Promise).one()
    assert promise.status == "kept" and "December 2026" in promise.status_note
    check = ledger.query(PromiseCheck).one()
    assert check.evidence == [results.id]  # the invented id 999999 was dropped
    assert (check.previous_status, check.verdict) == ("open", "kept")
    assert ledger.query(LlmCall).filter_by(task="promises").count() == 1
    assert pl.due(ledger, today=FEB) == []  # settled


@pytest.mark.db
def test_no_evidence_waits_for_a_new_document(ledger):
    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST), text="Revenue up 18%.")
    llm, client = _llm(ledger, verdicts("no_evidence"))
    pl.check_promises(ledger, llm, today=FEB)
    promise = ledger.query(Promise).one()
    assert promise.status == "open" and promise.status_note is None
    assert ledger.query(PromiseCheck).one().evidence == []

    pl.check_promises(ledger, llm, today=FEB)
    assert len(client.requests) == 1  # nothing new: not asked again

    news = Document(
        source="news:x",
        source_id="n1",
        doc_type="news",
        title="L&T shares rise",
        published_at=datetime(2027, 2, 2, tzinfo=IST),
        text="x",
        raw={},
    )
    ledger.add(news)
    ledger.flush()
    ledger.add(DocumentCompany(document_id=news.id, isin=LT))
    ledger.commit()
    pl.check_promises(ledger, llm, today=FEB)
    assert len(client.requests) == 1  # news does not trigger a check

    filing(
        ledger,
        datetime(2027, 2, 10, 17, 0, tzinfo=IST),
        doc_type="other",
        title="Commencement of commercial production at Hyderabad",
    )
    pl.check_promises(ledger, llm, today=FEB)
    assert len(client.requests) == 2
    assert "Commencement of commercial production" in client.requests[1]["messages"][0]["content"]


@pytest.mark.db
def test_missed_waits_for_the_results_window_to_close(ledger):
    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST), text="Hyderabad plant pending.")
    llm, client = _llm(ledger, verdicts("missed"))
    result = pl.check_promises(ledger, llm, today=FEB)
    promise = ledger.query(Promise).one()
    assert (result.held, result.settled, promise.status) == (1, 0, "open")
    assert ledger.query(PromiseCheck).one().verdict == "missed"  # the verdict is kept

    result = pl.check_promises(ledger, llm, today=APR)
    assert len(client.requests) == 1  # settled from the stored verdict, no LLM call
    ledger.refresh(promise)
    assert promise.status == "missed" and "per the Q3 results" in promise.status_note
    assert result.settled == 1

    # A miss recorded before the window closed (as the first version allowed) is reopened.
    promise.status = "missed"
    ledger.commit()
    assert pl.settle_misses(ledger, FEB) == (0, 1)
    ledger.refresh(promise)
    assert (promise.status, promise.status_note) == ("open", None)


@pytest.mark.db
def test_no_documents_no_call_and_budget(ledger):
    llm, client = _llm(ledger, verdicts())
    lines = []
    result = pl.check_promises(ledger, llm, today=FEB, progress=lines.append)
    assert result.calls == 0 and client.requests == [] and "no results or filings" in lines[0]
    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST))
    llm, client = _llm(ledger, verdicts(), llm_monthly_budget_usd=0.0)
    result = pl.check_promises(ledger, llm, today=FEB)
    assert "budget" in result.errors[0] and client.requests == []
    assert ledger.query(Promise).one().status == "open"


@pytest.mark.db
def test_many_promises_are_checked_in_batches_in_one_run(ledger):
    call = ledger.query(Concall).filter_by(status="analysed").one()
    for _ in range(pl.MAX_PROMISES):
        _promise(ledger, call, "open", date(2026, 12, 31))
    ledger.commit()
    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST))
    llm, client = _llm(ledger, verdicts())
    result = pl.check_promises(ledger, llm, today=FEB)
    assert (len(client.requests), result.checked, result.companies) == (2, 16, 1)


@pytest.mark.db
def test_reset_puts_back_what_the_calls_said(ledger):
    promise = ledger.query(Promise).one()
    promise.status, promise.status_note = "delayed", "Now Q1 FY28."
    ledger.commit()
    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST))
    llm, _ = _llm(ledger, verdicts("missed"))
    pl.check_promises(ledger, llm, today=APR)
    assert promise.status == "missed"
    assert pl.reset(ledger, "LT") == 1
    ledger.refresh(promise)
    assert (promise.status, promise.status_note) == ("delayed", "Now Q1 FY28.")
    assert ledger.query(PromiseCheck).count() == 0


def _promise(session, call, status, due_date):
    session.add(
        Promise(
            isin=LT,
            concall_id=call.id,
            statement=f"{status} promise",
            metric="m",
            target="t",
            due="x",
            due_date=due_date,
            status=status,
        )
    )


@pytest.mark.db
def test_credibility_score(ledger):
    call = ledger.query(Concall).filter_by(status="analysed").one()
    ledger.query(Promise).delete()
    today = date(2027, 6, 1)
    for status, due_date in [
        ("kept", date(2026, 12, 31)),
        ("kept", date(2026, 12, 31)),
        ("kept_late", date(2026, 9, 30)),
        ("partly", date(2026, 9, 30)),
        ("missed", date(2026, 9, 30)),
        ("dropped", None),
        ("delayed", date(2026, 12, 31)),  # long past its date + reporting lag: counts as 0
        ("open", date(2027, 5, 31)),  # results for it may not be out yet: still to come
        ("on_track", date(2028, 3, 31)),
    ]:
        _promise(ledger, call, status, due_date)
    ledger.commit()
    [lt] = pl.credibility(ledger, today=today)
    assert (lt["kept"], lt["kept_late"], lt["partly"], lt["missed"], lt["dropped"]) == (
        2,
        1,
        1,
        1,
        1,
    )
    assert (lt["overdue"], lt["to_come"], lt["scored"]) == (1, 2, 7)
    assert lt["score"] == pytest.approx((2 + 0.5 + 0.5) / 7)

    ledger.query(Promise).filter(Promise.status.in_(("kept", "kept_late", "partly"))).delete()
    ledger.query(Promise).filter(Promise.status.in_(("missed", "dropped"))).delete()
    ledger.commit()
    assert pl.credibility(ledger, today=today)[0]["score"] is None  # 1 scored: too few


@pytest.mark.db
def test_ledger_reaches_digest_dashboard_cli_and_scheduler(
    ledger, test_database_url, monkeypatch, tmp_path
):
    from streamlit.testing.v1 import AppTest
    from typer.testing import CliRunner

    from stock_news_analyzer.agents.digest import build_digest
    from stock_news_analyzer.agents.orchestrator import run_job
    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.ui import queries

    filing(ledger, datetime(2027, 1, 30, 17, 0, tzinfo=IST))
    llm, _ = _llm(ledger, verdicts())
    pl.check_promises(ledger, llm, today=FEB)
    call = ledger.query(Concall).filter_by(status="analysed").one()
    for status in ("missed", "kept"):
        _promise(ledger, call, status, date(2026, 9, 30))
    ledger.commit()

    now = datetime.now(IST)
    md = build_digest(ledger, now.replace(year=now.year - 1), now).markdown
    assert "## Promises" in md and "- LT **kept**: Hyderabad plant commissioned by Q3 FY27" in md
    checks = queries.promise_checks(ledger, LT)
    assert list(checks["verdict"]) == ["kept"] and "Financial results" in checks["based_on"][0]
    [score] = queries.credibility(ledger)
    assert score["score"] == pytest.approx(2 / 3)

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    runner = CliRunner()
    out = runner.invoke(app, ["promises", "scores"])
    assert out.exit_code == 0 and "LT" in out.stdout and "67% of 3" in out.stdout
    out = runner.invoke(app, ["promises", "list", "LT"])
    assert out.exit_code == 0 and "kept" in out.stdout and "per the Q3 results" in out.stdout
    run = run_job("promises")
    assert run.status == "ok" and run.summary.startswith("skipped")

    at = AppTest.from_string(
        # Earlier tests leave dashboard queries cached for a minute.
        "import streamlit as st\nst.cache_data.clear()\n"
        "from stock_news_analyzer.ui import app\napp.stock_page_body()",
        default_timeout=30,
    )
    at.query_params["symbol"] = "LT"
    at.run()
    assert not at.exception, at.exception
    assert any(m.label == "Promises kept" and m.value == "67%" for m in at.metric)
