from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_concalls import LT
from test_llm import settings, usage
from test_orchestrator import loaded  # noqa: F401  (fixture)
from test_orders import KVB, doc

from stock_news_analyzer.agents import ask as qa
from stock_news_analyzer.llm import LLM, BudgetExceeded
from stock_news_analyzer.models import (
    Concall,
    ConcallPoint,
    Event,
    LlmCall,
    Question,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

NOW = datetime.now(IST).replace(microsecond=0)


class FakeClient:
    """Stands in for anthropic.Anthropic's messages.create: plays back `turns`, each a list
    of ('text', str) or ('tool', name, input) blocks."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        blocks = []
        for i, b in enumerate(self.turns.pop(0)):
            if b[0] == "text":
                blocks.append(SimpleNamespace(type="text", text=b[1]))
            else:
                blocks.append(SimpleNamespace(type="tool_use", id=f"t{i}", name=b[1], input=b[2]))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage(3000, 300))


def _llm(session, turns, **kw):
    client = FakeClient(turns)
    return LLM(session, client=client, settings=settings(**kw)), client


def test_only_single_selects_pass():
    assert qa.check_sql(" select 1; ") == "select 1"
    assert qa.check_sql("WITH x AS (SELECT 1) SELECT * FROM x")
    for bad in ("DELETE FROM companies", "select 1; drop table companies", "update x set y=1"):
        with pytest.raises(qa.SqlRefused):
            qa.check_sql(bad)


@pytest.mark.db
def test_sql_is_read_only_and_limited(loaded):  # noqa: F811
    out = qa.run_sql(loaded, "SELECT nse_symbol FROM companies ORDER BY nse_symbol")
    assert out.splitlines()[0] == "nse_symbol" and "LT" in out
    # A write hidden in a CTE passes the first check but PostgreSQL refuses it.
    sneaky = "WITH d AS (DELETE FROM watchlist RETURNING 1) SELECT * FROM d"
    assert "error:" in qa._run_tool(loaded, "run_sql", {"query": sneaky})
    assert loaded.query(WatchlistItem).count() == 3
    many = qa.run_sql(loaded, "SELECT generate_series(1, 500) AS n")
    assert len(many.splitlines()) == qa.MAX_ROWS + 2 and "more than" in many
    assert qa._run_tool(loaded, "run_sql", {"query": "drop table x"}).startswith("refused")
    assert "error:" in qa._run_tool(loaded, "run_sql", {"query": "select nope from companies"})
    # The session still works after a failed query.
    assert "LT" in qa.run_sql(loaded, "SELECT nse_symbol FROM companies")


@pytest.mark.db
def test_search_finds_documents_and_events(loaded):  # noqa: F811
    d = doc(
        loaded,
        KVB,
        NOW - timedelta(days=3),
        "other",
        "Board approves dividend",
        "The board recommended a final dividend of Rs 2 per share.",
    )
    e = Event(
        isin=LT,
        document_id=d.id,
        published_at=NOW,
        event_type="capex",
        headline="New green hydrogen plant at Hazira",
        sentiment="positive",
        importance=4,
        quote="q",
        qa_status="passed",
        model="m",
        prompt_version="events-4",
    )
    loaded.add(e)
    loaded.commit()
    out = qa.search_text(loaded, "dividend")
    assert f"doc:{d.id}" in out and "KARURVYSYA" in out and "<b>dividend</b>" in out.lower()
    assert f"event:{e.id}" in qa.search_text(loaded, "hydrogen plant", symbol="lt")
    assert qa.search_text(loaded, "dividend", symbol="LT", kinds=["doc"]) == "(no matches)"
    assert qa.search_text(loaded, "dividend", since=str(date.today() + timedelta(days=1))) == (
        "(no matches)"
    )
    assert qa.search_text(loaded, "x", symbol="NOPE") == "unknown symbol NOPE"
    assert "final dividend" in qa.read_document(loaded, d.id)


@pytest.mark.db
def test_ask_uses_tools_and_keeps_the_answer(loaded):  # noqa: F811
    d = doc(loaded, KVB, NOW - timedelta(days=3), "other", "Board approves dividend", "Dividend.")
    llm, client = _llm(
        loaded,
        [
            [("text", "Let me check."), ("tool", "search_text", {"query": "dividend"})],
            [
                ("tool", "run_sql", {"query": "SELECT count(*) FROM companies"}),
                ("tool", "read_document", {"doc_id": d.id}),
            ],
            [("text", f"KVB's board approved a dividend [doc:{d.id}] [doc:999999].")],
        ],
    )
    lines = []
    answer = qa.ask(loaded, llm, "Who declared dividends?", name="dividends", progress=lines.append)
    assert answer.text.startswith("KVB's board") and answer.sources == [f"doc:{d.id}"]
    assert answer.steps == 3 and lines[0] == "search: dividend"
    first = client.requests[0]
    assert first["model"] == "claude-sonnet-5-5"
    assert "documents:" in first["system"][0]["text"] and "nse_symbol" in first["system"][0]["text"]
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    # The tool results went back with the matching ids.
    results = client.requests[2]["messages"][-2]["content"]  # before the answer
    assert [r["tool_use_id"] for r in results] == ["t0", "t1"] and "count" in results[0]["content"]
    row = loaded.get(Question, answer.question_id)
    assert row.name == "dividends" and row.sources == [f"doc:{d.id}"] and row.cost_usd > 0
    assert loaded.query(LlmCall).filter_by(task="ask").count() == 3
    assert qa.saved(loaded, "dividends").id == row.id and qa.history(loaded)[0].id == row.id
    assert qa.describe_source(loaded, f"doc:{d.id}").startswith(f"[doc:{d.id}]")


@pytest.mark.db
def test_step_limit_and_budget(loaded, monkeypatch):  # noqa: F811
    monkeypatch.setattr(qa, "MAX_STEPS", 2)
    tool = [("tool", "run_sql", {"query": "SELECT 1"})]
    llm, client = _llm(loaded, [tool, tool, tool, [("text", "Done.")]])
    answer = qa.ask(loaded, llm, "Loop forever?")
    assert answer.text == "Done." and answer.steps == 3 and len(client.requests) == 4
    assert "step limit" in client.requests[-1]["messages"][-2]["content"][0]["content"]
    llm, client = _llm(loaded, [tool] * 4)
    assert qa.ask(loaded, llm, "Never stop?").text.startswith("(no answer")
    llm, _ = _llm(loaded, [[("text", "x")]], llm_monthly_budget_usd=0.0)
    with pytest.raises(BudgetExceeded):
        qa.ask(loaded, llm, "Too expensive?")


@pytest.mark.db
def test_call_points_name_the_company_and_call(loaded):  # noqa: F811
    d = doc(loaded, KVB, NOW - timedelta(days=12), "concall_transcript", "Transcript", "Call.")
    call = Concall(
        isin=KVB,
        document_id=d.id,
        status="done",
        published_at=d.published_at,
        quarter="Q2 FY27",
        call_date=date(2026, 10, 15),
    )
    loaded.add(call)
    loaded.flush()
    point = ConcallPoint(
        concall_id=call.id, category="guidance", text="ROA guidance raised.", sentiment="positive"
    )
    loaded.add(point)
    loaded.commit()
    assert qa.describe_source(loaded, f"point:{point.id}") == (
        f"[point:{point.id}] KARURVYSYA Q2 FY27 call (15 Oct 2026), guidance: ROA guidance raised."
    )
    assert f"point:{point.id}" in qa.search_text(loaded, "ROA guidance", kinds=["point"])
