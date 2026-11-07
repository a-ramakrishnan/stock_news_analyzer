import json
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session
from test_eval_events import SPEC, _reply_with, _verified, event
from test_llm import FakeAnthropic, settings
from test_orchestrator import loaded  # noqa: F401  (fixture)
from typer.testing import CliRunner

from stock_news_analyzer.evals import framework as fw
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import EvalResult, EvalRun


@pytest.mark.db
def test_a_variant_runs_with_other_instructions_and_says_why(loaded, tmp_path):  # noqa: F811
    items = _verified(loaded)
    found = {c.input["document_id"]: [event()] if c.reference["events"] else [] for c in items}
    client = FakeAnthropic(_reply_with(found))
    bind = loaded.get_bind()
    fw.run(
        lambda: Session(bind),
        lambda s: LLM(s, client=client, settings=settings()),
        SPEC,
        items,
        variant="v1",
        model="claude-haiku-5-5",
        reps=1,
        flow=tmp_path,
        approve_harness=True,
        system="Read filings. Be strict about amounts.",
        system_file="v1.txt",
        note="stricter about amounts",
        say=lambda _: None,
    )
    assert client.requests[0]["system"][0]["text"] == "Read filings. Be strict about amounts."
    with Session(bind) as check:
        run = check.query(EvalRun).one()
        assert run.variant == "v1" and run.note == "stricter about amounts"
        assert run.config["instructions"].startswith("changed (") and run.config["file"] == "v1.txt"
        assert run.scores["correct"] == 1.0
    change = (tmp_path / "v1" / "change.md").read_text()
    assert change.startswith("stricter about amounts") and "from v1.txt" in change
    trace = json.loads(next((tmp_path / "v1" / "traces").glob("*.json")).read_text())
    assert trace[0]["content"] == "Read filings. Be strict about amounts."
    assert fw.run_config(SPEC, "m", None, None) == {"model": "m", "instructions": "the agent's own"}
    assert fw.run_config(SPEC, "m", SPEC.system, "same.txt")["instructions"] == "the agent's own"


def _run(session, variant, correct_by_case, cost="0.0004", model="claude-haiku-5-5"):
    run = EvalRun(
        flow="events",
        variant=variant,
        model=model,
        cases=len(correct_by_case),
        cases_verified=len(correct_by_case),
        attempts=0,
        scores={},
        config={"model": model, "instructions": "the agent's own"},
    )
    session.add(run)
    session.flush()
    for key, values in correct_by_case.items():
        for rep, v in enumerate(values):
            session.add(
                EvalResult(
                    run_id=run.id,
                    case_id=key,
                    rep=rep,
                    title=f"Filing {key}",
                    grade={"correct": v, "detect": 1, "types": v, "amounts": v, "quotes": 1},
                    detail={
                        "expected": ["capex Rs 14 cr"],
                        "found": [f"capex Rs {14 if v else 1400} cr"],
                    },
                    latency_s=2.0 if variant == "baseline" else 3.0,
                    cost_usd=Decimal(cost),
                )
            )
    session.commit()
    return run


@pytest.mark.db
def test_a_variant_that_fixes_cases_is_better(loaded):  # noqa: F811
    base = _run(loaded, "baseline", {f"doc{i}": [1, 1] if i < 4 else [0, 0] for i in range(10)})
    fixed = _run(
        loaded,
        "v1",
        {f"doc{i}": [1, 1] if i < 9 else [0, 0] for i in range(10)},
        cost="0.0008",
        model="claude-sonnet-5-5",
    )
    c = fw.compare(loaded, SPEC, base.id, fixed.id)
    assert c["verdict"] == "better" and c["cases"] == 10
    assert c["difference"] == pytest.approx(0.5) and c["interval"][0] > 0
    assert [x["case"] for x in c["improved"]] == ["doc4", "doc5", "doc6", "doc7", "doc8"]
    assert c["regressed"] == [] and c["same"] == 5
    assert c["a"]["correct"] == pytest.approx(0.4) and c["b"]["correct"] == pytest.approx(0.9)
    assert c["b"]["cost_per_case"] == pytest.approx(0.0008) and c["b"]["latency_median"] == 3.0
    assert c["improved"][0]["a_detail"]["found"] == ["capex Rs 1400 cr"]
    md = fw.comparison_markdown(SPEC, c)
    assert "**Verdict: better.** Correct +50.0 points" in md
    assert "| Model | claude-haiku-5-5 | claude-sonnet-5-5 |" in md
    assert "- doc4 (Filing doc4): 0% → 100%" in md


@pytest.mark.db
def test_worse_unclear_and_too_few(loaded):  # noqa: F811
    base = _run(loaded, "baseline", {f"doc{i}": [1] for i in range(10)})
    broke = _run(loaded, "v1", {f"doc{i}": [0] if i < 6 else [1] for i in range(10)})
    assert fw.compare(loaded, SPEC, base.id, broke.id)["verdict"] == "worse"
    mixed = _run(loaded, "v2", {f"doc{i}": [0] if i in (1, 2) else [1] for i in range(10)})
    mixed_base = _run(loaded, "v3", {f"doc{i}": [0] if i in (3, 4) else [1] for i in range(10)})
    c = fw.compare(loaded, SPEC, mixed_base.id, mixed.id)
    assert c["verdict"] == "no clear difference" and len(c["regressed"]) == 2
    gone = fw.add_case(  # excluded after both runs: left out of the comparison
        loaded, SPEC, fw.NewCase(key="doc1", title="x", input={}, reference={"events": []})
    )
    fw.set_answer(gone, gone.reference, "excluded", "test")
    loaded.commit()
    c = fw.compare(loaded, SPEC, mixed_base.id, mixed.id)
    assert c["cases"] == 9 and c["excluded"] == ["doc1"] and len(c["regressed"]) == 1
    assert "Left out, excluded since: doc1" in fw.comparison_markdown(SPEC, c)
    small_a = _run(loaded, "v4", {"x": [1], "y": [0]})
    small_b = _run(loaded, "v5", {"x": [1], "y": [1], "z": [1]})
    c = fw.compare(loaded, SPEC, small_a.id, small_b.id)
    assert c["verdict"] == "too few cases to tell" and c["only_b"] == ["z"]
    assert list(fw.latest_runs(loaded, SPEC))[:1] == ["v5"]


def test_the_instructions_command_prints_the_agents_own():
    from stock_news_analyzer.cli import app

    out = CliRunner().invoke(app, ["eval", "events", "instructions"])
    assert out.exit_code == 0 and out.stdout.strip() == SPEC.system.strip()


@pytest.mark.db
def test_the_page_compares_variants(loaded, test_database_url, monkeypatch, tmp_path):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    _run(loaded, "baseline", {f"doc{i}": [1] if i < 4 else [0] for i in range(10)})
    v1 = _run(loaded, "v1", {f"doc{i}": [1] if i < 9 else [0] for i in range(10)})
    v1.note = "stricter about amounts"
    loaded.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.evals_page()", default_timeout=30
    )
    at.run()
    assert not at.exception, at.exception
    assert "**v1 is better** than baseline" in at.success[-1].value
    captions = " ".join(c.value for c in at.caption)
    assert "Why v1: stricter about amounts" in captions
    assert any(e.label.startswith("doc4: Filing doc4 (0% → 100%)") for e in at.expander)
    get_settings.cache_clear()
