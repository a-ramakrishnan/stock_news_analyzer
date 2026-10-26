from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from stock_news_analyzer.config import Settings
from stock_news_analyzer.llm import (
    LLM,
    BudgetExceeded,
    LLMError,
    LLMNotConfigured,
    cost,
    month_spend,
)
from stock_news_analyzer.models import LlmCall


class Answer(BaseModel):
    word: str


def usage(inp=1000, out=200, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: `reply(kwargs)` returns the response."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []
        self.messages = self

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        return self.reply(kwargs)


def ok(_kwargs):
    return SimpleNamespace(usage=usage(), parsed_output=Answer(word="hi"), stop_reason="end_turn")


def settings(**kw):
    return Settings(**{"anthropic_api_key": "test", "llm_monthly_budget_usd": 1.0, **kw})


def test_cost_per_model():
    # Haiku 5.5: $0.10 in, $0.50 out per million; cache reads 0.1x, cache writes 1.25x input.
    assert cost("claude-haiku-5-5", usage(1_000_000, 1_000_000)) == Decimal("0.60000")
    assert cost("claude-sonnet-5-5", usage(1000, 200)) == Decimal("0.00400")
    assert cost("claude-sonnet-5-5", usage(0, 0, cache_read=1_000_000)) == Decimal("0.20000")
    assert cost("claude-sonnet-5-5", usage(0, 0, cache_write=1_000_000)) == Decimal("2.50000")
    assert cost("some-new-model", usage(1_000_000, 0)) == Decimal("4.00000")  # priced as Opus


@pytest.mark.db
def test_structured_call_is_logged_with_cost(session):
    client = FakeAnthropic(ok)
    llm = LLM(session, client=client, settings=settings())
    answer = llm.structured("triage", "claude-sonnet-5-5", "Be brief.", "Say hi", Answer)
    assert answer.word == "hi"
    req = client.requests[0]
    assert req["model"] == "claude-sonnet-5-5" and req["output_format"] is Answer
    assert req["output_config"] == {"effort": "low"}
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    call = session.query(LlmCall).one()
    assert (call.task, call.ok, call.input_tokens, call.output_tokens) == (
        "triage",
        True,
        1000,
        200,
    )
    assert call.cost_usd == Decimal("0.00400") and month_spend(session) == Decimal("0.004")


@pytest.mark.db
def test_refusal_cutoff_and_api_errors_are_logged_and_raised(session):
    def refused(_kw):
        return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="refusal")

    def cut_off(_kw):
        return SimpleNamespace(usage=usage(), parsed_output=None, stop_reason="max_tokens")

    def down(_kw):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.APIConnectionError(request=request)

    def broken_json(_kw):
        Answer.model_validate_json('{"word": "h')  # what the SDK raises on a cut-off answer

    replies = (
        (refused, "declined"),
        (cut_off, "cut off"),
        (down, "Connection"),
        (broken_json, "did not match the schema"),
    )
    for reply, message in replies:
        llm = LLM(session, client=FakeAnthropic(reply), settings=settings())
        with pytest.raises(LLMError, match=message):
            llm.structured("triage", "claude-haiku-5-5", "s", "p", Answer)
    calls = session.query(LlmCall).order_by(LlmCall.id).all()
    assert [c.ok for c in calls] == [False, False, False, False]
    assert calls[0].cost_usd > 0 and calls[2].cost_usd == 0  # tokens used vs nothing sent


@pytest.mark.db
def test_budget_stops_calls_for_the_rest_of_the_month(session):
    session.add(LlmCall(at=datetime.now(UTC), task="triage", model="m", cost_usd=Decimal("1.0")))
    session.add(  # last month's spend does not count
        LlmCall(at=datetime(2020, 1, 15, tzinfo=UTC), task="triage", model="m", cost_usd=9)
    )
    session.commit()
    client = FakeAnthropic(ok)
    with pytest.raises(BudgetExceeded, match=r"\$1.00 has reached the \$1.00 budget"):
        LLM(session, client=client, settings=settings()).structured("t", "m", "s", "p", Answer)
    assert client.requests == []  # nothing was sent


@pytest.mark.db
def test_missing_api_key(session):
    with pytest.raises(LLMNotConfigured, match="ANTHROPIC_API_KEY"):
        LLM(session, settings=Settings(anthropic_api_key=None)).structured(
            "t", "claude-haiku-5-5", "s", "p", Answer
        )
