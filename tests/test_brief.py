from datetime import date
from types import SimpleNamespace

import pytest
from test_llm import FakeAnthropic, settings, usage
from test_prices import watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import brief as bf
from stock_news_analyzer.llm import LLM
from stock_news_analyzer.models import LlmCall, ResearchBrief

KVB = "INE036D01028"
FACTS = [
    ("F1", "[Market] Trailing P/E 65.2 (trailing EPS ₹47.17)"),
    ("F2", "[Filed] Results Q2 FY27: revenue ₹25,109 cr, +1% on the year; profit +52%"),
    ("F3", "[Filed] Debt to equity at 30 Sep 2026: 1.17×"),
]


def test_numbers_must_come_from_the_facts():
    known = bf.allowed(FACTS)
    ok = "P/E 65 against EPS of ₹47.17; revenue ₹25,109 cr; profit up 52%; debt 1.2×; Q2 FY27"
    assert bf.unknown_numbers(ok, known) == []  # rounded, and Q2 or FY27 are labels
    assert bf.unknown_numbers("3 of 5 quarters in 2026", known) == []  # counts and a fact's year
    assert bf.unknown_numbers("margin 9% and P/E 70, cash ₹900 cr", known) == ["9", "70", "900"]
    assert bf.unknown_numbers("debt 1.3×", known) == ["1.3"]  # 1.17 doesn't round to 1.3


def _view(**changes) -> bf.View:
    base = dict(
        verdict="P/E 65 and debt 1.2× equity.",
        summary="Profit rose 52% on flat revenue.",
        stances=[
            bf.Stance(label="Favor", text="P/E 65"),
            bf.Stance(label="Watch", text="debt"),
            bf.Stance(label="Check", text="margin"),
        ],
        observations=[
            bf.Observation(observed="Profit +52%.", read="Margins did it.", facts=["F2"]),
            bf.Observation(observed="Cash ₹999 cr.", read="Thin.", facts=["F9"]),
        ],
        subject=bf.Note(symbol="KARURVYSYA", why_it_matters="A bank.", key_risk="Debt."),
        peers=[],
        decisions=[
            bf.Decision(tag="Watch", title="Margin", why="Results show +52%.", facts=["F2"]),
            bf.Decision(tag="Check", title="Growth", why="Expect 18% growth.", facts=[]),
        ],
        decide_now=["Is 1.17× debt acceptable?"],
    )
    base.update(changes)
    return bf.View(**base)


def test_parts_with_unknown_numbers_are_dropped():
    view = _view()
    problems = bf.check(view, bf.allowed(FACTS))
    assert problems == {"observation 1": ["999"], "decision 1": ["18"]}
    kept, dropped = bf.drop(view, problems, "fallback")
    assert [o.observed for o in kept.observations] == ["Profit +52%."]
    assert [d.title for d in kept.decisions] == ["Margin"]
    assert {d["part"] for d in dropped} == {"observation", "decision"}
    bad_verdict = _view(verdict="Worth ₹5,000 a share.")
    kept, dropped = bf.drop(bad_verdict, bf.check(bad_verdict, bf.allowed(FACTS)), "fallback")
    assert kept.verdict == "fallback" and dropped[0]["part"] == "verdict"


def _llm(session, views):
    replies = iter(views)

    def reply(kwargs):
        return SimpleNamespace(usage=usage(), parsed_output=next(replies), stop_reason="end_turn")

    client = FakeAnthropic(reply)
    return LLM(session, client=client, settings=settings()), client


@pytest.mark.db
def test_write_checks_retries_and_saves(watchlist, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bf, "fact_lines", lambda f, today: FACTS)
    clean = _view(
        observations=[bf.Observation(observed="Profit +52%.", read="Margins.", facts=["F2"])],
        decisions=[bf.Decision(tag="Watch", title="Margin", why="+52%.", facts=["F2"])],
    )
    llm, client = _llm(watchlist, [clean])
    lines = []
    b = bf.write(
        watchlist,
        llm,
        KVB,
        model="claude-sonnet-5-5",
        today=date(2026, 11, 5),
        progress=lines.append,
    )
    assert len(client.requests) == 1 and b.dropped == []
    prompt = client.requests[0]["messages"][0]["content"]
    assert "F2 [Filed] Results Q2 FY27" in prompt and "Write the view." in prompt
    assert b.facts == [list(x) for x in FACTS] and b.view["verdict"] == clean.verdict
    assert b.cost_usd > 0 and watchlist.query(LlmCall).filter_by(task="brief").count() == 1
    assert any("Checking every number" in line for line in lines)

    # A view with made-up numbers: asked again with the list, then the parts dropped.
    llm, client = _llm(watchlist, [_view(), _view()])
    b2 = bf.write(watchlist, llm, KVB, model="claude-sonnet-5-5", today=date(2026, 11, 5))
    assert len(client.requests) == 2
    assert "999" in client.requests[1]["messages"][0]["content"]
    assert len(b2.dropped) == 2 and len(b2.view["observations"]) == 1
    assert [v.id for v in bf.versions(watchlist, KVB)] == [b2.id, b.id]
    assert bf.latest(watchlist, KVB).id == b2.id


@pytest.mark.db
def test_brief_page_and_cli_show_the_view(watchlist, test_database_url, monkeypatch):  # noqa: F811
    from streamlit.testing.v1 import AppTest
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app
    from stock_news_analyzer.models import WatchlistItem

    for item in watchlist.query(WatchlistItem):
        watchlist.add(
            ResearchBrief(
                isin=item.isin,
                model="claude-sonnet-5-5",
                cost_usd=0.04,
                facts=[list(x) for x in FACTS],
                view=_view().model_dump(),
                dropped=[{"part": "decision", "text": "x", "numbers": ["18"]}],
            )
        )
    watchlist.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    from stock_news_analyzer.config import get_settings

    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.research_page()", default_timeout=30
    )
    at.run()
    assert not at.exception, at.exception
    labels = [e.label for e in at.expander]
    assert labels[0] == "1. The view · 2 points"
    assert any("What to watch and decide" in x for x in labels)
    assert labels[-1] == f"{len(labels)}. Sources · 3 facts"

    result = CliRunner().invoke(app, ["brief", "KARURVYSYA"])
    assert result.exit_code == 0, result.stdout
    assert "P/E 65 and debt 1.2× equity." in result.stdout
    assert "dropped decision: numbers 18 not in the facts" in result.stdout


def test_what_changed_between_briefs():
    old = [
        ("F1", "[Filed] Company: X; brief of 01 Nov 2026"),
        ("F2", "[Market] Close ₹100.00 on 31 Oct 2026"),
        ("F3", "[Filed] Results Q2 FY27 (to 30 Sep 2026): revenue ₹100 cr"),
        ("F4", "[AI] Promise: margin 15% by FY27: open"),
        ("F5", "[AI] Promise: capex ₹500 cr by FY28: open"),
    ]
    new = [
        ("F1", "[Filed] Company: X; brief of 05 Nov 2026"),  # not compared
        ("F2", "[Market] Close ₹104.00 on 04 Nov 2026"),
        ("F3", "[Filed] Results Q2 FY27 (to 30 Sep 2026): revenue ₹101 cr"),
        ("F4", "[AI] Promise: margin 15% by FY27: kept"),
        ("F5", "[Filed] Open red flag 04 Nov 2026 (medium): a pledge"),
    ]
    assert bf.fact_key(new[1][1]) == "Close"
    d = bf.diff_facts(old, new)
    assert [k for k, _, _ in d["changed"]] == ["Close", "Results Q2 FY27 (to 30 Sep 2026)"]
    assert d["added"] == [
        "Promise: margin 15% by FY27: kept",
        "Open red flag 04 Nov 2026 (medium): a pledge",
    ]
    assert len(d["removed"]) == 2  # promises share a label: compared by their whole text
    filed = bf.diff_facts(old, new, filed_only=True)
    assert [k for k, _, _ in filed["changed"]] == ["Results Q2 FY27 (to 30 Sep 2026)"]

    before = _view().model_dump()
    after = _view(
        verdict="New verdict.",
        stances=[
            bf.Stance(label="Favor", text="P/E 65"),
            bf.Stance(label="Avoid", text="the pledge"),
            bf.Stance(label="Check", text="margin"),
        ],
        decisions=[bf.Decision(tag="Review now", title="Margin", why="+52%.", facts=["F2"])],
    ).model_dump()
    assert bf.diff_views(before, after) == [
        'Verdict: was "P/E 65 and debt 1.2× equity."',
        "New stance: Avoid, the pledge",
        "Stance dropped: Watch, debt",
        "Margin: Watch → Review now",
    ]


@pytest.mark.db
def test_refresh_writes_due_briefs_and_the_digest_lists_them(watchlist, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from stock_news_analyzer.agents import digest
    from stock_news_analyzer.agents import orchestrator as orch
    from stock_news_analyzer.models import RedFlag, WatchlistItem

    monkeypatch.setattr(bf, "fact_lines", lambda f, today: FACTS)
    watchlist.query(WatchlistItem).filter_by(isin=KVB).update({"owned": True})
    watchlist.commit()
    assert bf.due(watchlist, KVB) == "no view yet"
    llm, client = _llm(watchlist, [_view(observations=[], decisions=[])] * 3)
    written, errors = bf.refresh(watchlist, llm)
    assert [(s, why) for s, why, _ in written] == [("KARURVYSYA", "no view yet")]
    assert errors == [] and bf.due(watchlist, KVB) is None
    assert bf.refresh(watchlist, llm)[0] == []  # nothing new: nothing written

    watchlist.add(
        RedFlag(
            isin=KVB,
            kind="pledge",
            severity="high",
            title="Pledge",
            flagged_on=date(2026, 11, 4),
            ref="t",
        )
    )
    watchlist.commit()
    assert bf.due(watchlist, KVB) == "a new red flag"
    written, _ = bf.refresh(watchlist, llm)
    assert len(written) == 1
    # The second view was given the first one and asked what changed.
    assert "Your previous view" in client.requests[-1]["messages"][0]["content"]

    now = datetime.now(UTC)
    lines = digest._briefs(watchlist, now - timedelta(days=1), now + timedelta(minutes=1))
    assert lines[1] == "## Research briefs" and lines[3].startswith("- **KARURVYSYA**: P/E 65")
    assert "briefs" in orch.JOBS and orch.RUN_ALL.index("briefs") < orch.RUN_ALL.index("digest")
