from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel
from test_llm import settings, usage

from stock_news_analyzer import traces as tr
from stock_news_analyzer.llm import LLM, LLMError
from stock_news_analyzer.models import LlmCall, LlmPrompt, LlmTrace

SYSTEM = "You read filings."


class Answer(BaseModel):
    word: str


class Fake:
    """Answers parse() and create() calls; raises when told to."""

    def __init__(self, fail=False):
        self.fail = fail
        self.messages = self

    def parse(self, **kw):
        if self.fail:
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
        return SimpleNamespace(
            usage=usage(1200, 80),
            parsed_output=Answer(word="capex"),
            stop_reason="end_turn",
            model="claude-haiku-5-5",
        )

    def create(self, **kw):
        block = SimpleNamespace(type="text", text="Two filings raised guidance.")
        return SimpleNamespace(
            usage=usage(3000, 200),
            content=[block],
            stop_reason="end_turn",
            model="claude-sonnet-5-5",
        )


def _llm(session, **kw):
    return LLM(
        session,
        client=Fake(**{k: v for k, v in kw.items() if k == "fail"}),
        settings=settings(**{k: v for k, v in kw.items() if k != "fail"}),
    )


@pytest.mark.db
def test_every_structured_call_is_traced(session):
    llm = _llm(session)
    prompt = 'Filings (2):\n<filing id="12" company="L&T">x</filing>\n<filing id="13">y</filing>'
    assert llm.structured("events", "claude-haiku-5-5", SYSTEM, prompt, Answer).word == "capex"
    llm.structured("events", "claude-haiku-5-5", SYSTEM, "Filings (1): none", Answer)
    traces = session.query(LlmTrace).order_by(LlmTrace.id).all()
    assert len(traces) == 2
    t = traces[0]
    assert t.prompt == prompt and t.response == {"word": "capex"}
    assert t.stop_reason == "end_turn" and t.served_model == "claude-haiku-5-5"
    assert t.latency_ms is not None and t.latency_ms >= 0
    assert t.subjects == ["document:12", "document:13"]
    assert session.query(LlmPrompt).count() == 1  # the instructions are stored once
    assert session.get(LlmPrompt, t.system_sha).text == SYSTEM
    assert t.call_id == session.query(LlmCall).order_by(LlmCall.id).first().id


@pytest.mark.db
def test_failed_calls_and_conversations_are_traced(session):
    with pytest.raises(LLMError):
        _llm(session, fail=True).structured("results", "claude-haiku-5-5", SYSTEM, "p", Answer)
    failed = session.query(LlmTrace).one()
    assert failed.response is None and failed.prompt == "p"
    messages = [{"role": "user", "content": "Which companies raised guidance?"}]
    _llm(session).message("ask", "claude-sonnet-5-5", "You answer questions.", messages)
    convo = session.query(LlmTrace).order_by(LlmTrace.id.desc()).first()
    assert "Which companies raised guidance?" in convo.prompt
    assert convo.response == [{"type": "text", "text": "Two filings raised guidance."}]
    assert convo.served_model == "claude-sonnet-5-5"


@pytest.mark.db
def test_traces_can_be_turned_off(session):
    _llm(session, llm_trace_days=0).structured("events", "claude-haiku-5-5", SYSTEM, "p", Answer)
    assert session.query(LlmCall).count() == 1 and session.query(LlmTrace).count() == 0


@pytest.mark.db
def test_listing_detail_and_pruning(session):
    llm = _llm(session)
    llm.structured("events", "claude-haiku-5-5", SYSTEM, '<filing id="7">capex</filing>', Answer)
    llm.structured("triage", "claude-haiku-5-5", "You sort news.", "an article", Answer)
    with pytest.raises(LLMError):
        _llm(session, fail=True).structured("events", "claude-haiku-5-5", SYSTEM, "q", Answer)
    old = session.query(LlmCall).filter_by(task="triage").one()
    old.at = datetime.now(UTC) - timedelta(days=40)
    session.commit()

    assert [r["task"] for r in tr.listing(session, days=7)] == ["events", "events"]
    assert len(tr.listing(session, days=60)) == 3
    assert [r["ok"] for r in tr.listing(session, ["events"], failed_only=True)] == [False]
    assert len(tr.listing(session, text="capex")) == 1
    assert tr.tasks(session)[0] == "events"
    row = tr.listing(session, text="capex")[0]
    d = tr.detail(session, row["call_id"])
    assert d["system"] == SYSTEM and d["response"] == {"word": "capex"}
    assert tr.documents(d["subjects"]) == [7] and tr.detail(session, 999999) is None

    assert tr.prune(session, 30) == 1  # the 40-day-old triage call
    assert session.query(LlmTrace).count() == 2
    assert {p.text for p in session.query(LlmPrompt)} == {SYSTEM}  # its instructions too
    assert session.query(LlmCall).count() == 3  # calls and their costs are kept


def test_answers_become_json():
    class Inner(BaseModel):
        n: int

    assert tr.jsonable(Inner(n=2)) == {"n": 2}
    assert tr.jsonable([SimpleNamespace(a=1, _hidden=2), (3, None)]) == [{"a": 1}, [3, None]]
    assert tr.jsonable(datetime(2026, 1, 1)) == "2026-01-01 00:00:00"


@pytest.mark.db
def test_the_traces_page(session, test_database_url, monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    _llm(session).structured("events", "claude-haiku-5-5", SYSTEM, "a filing", Answer)
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.traces_page()", default_timeout=30
    )
    at.run()
    assert not at.exception, at.exception
    assert any(c.value.startswith("1 calls") for c in at.caption)
    get_settings.cache_clear()
