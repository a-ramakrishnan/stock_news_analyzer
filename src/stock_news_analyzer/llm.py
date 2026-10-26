"""The one place that calls an LLM (Claude), so every Phase 2 agent shares the same rules.

Each call asks for a structured answer (a pydantic model), is logged in `llm_calls` with its
tokens and cost, and is refused once this month's spend reaches LLM_MONTHLY_BUDGET_USD.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_news_analyzer.config import Settings, get_settings
from stock_news_analyzer.models import LlmCall
from stock_news_analyzer.sources.announcements import IST

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# US dollars per million tokens: (input, output). Cache reads cost 0.1x input and 5-minute
# cache writes 1.25x. Haiku 5.5's rate is for prompts up to 100K tokens; ours are far smaller.
PRICES = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
}


class LLMError(Exception):
    """The call failed or gave no usable answer."""


class LLMNotConfigured(LLMError):
    """No API key in .env."""


class BudgetExceeded(LLMError):
    """This month's spend has reached LLM_MONTHLY_BUDGET_USD."""


def cost(model: str, usage) -> Decimal:
    """Dollar cost of one response's `usage`. Unknown models are priced as Opus (the highest)."""
    inp, out = PRICES.get(model, PRICES["claude-opus-5-5"])
    tokens = (
        Decimal(usage.input_tokens or 0) * inp
        + Decimal(usage.output_tokens or 0) * out
        + Decimal(getattr(usage, "cache_read_input_tokens", 0) or 0) * inp * Decimal("0.1")
        + Decimal(getattr(usage, "cache_creation_input_tokens", 0) or 0) * inp * Decimal("1.25")
    )
    return (tokens / Decimal(1_000_000)).quantize(Decimal("0.00001"))


def month_spend(session: Session, now: datetime | None = None) -> Decimal:
    """Dollars spent on LLM calls since the 1st of this month (India time)."""
    now = (now or datetime.now(UTC)).astimezone(IST)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(select(func.sum(LlmCall.cost_usd)).where(LlmCall.at >= start))
    return Decimal(total or 0)


class LLM:
    def __init__(self, session: Session, client=None, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self):
        if self._client is None:
            if not self.settings.anthropic_api_key:
                raise LLMNotConfigured("ANTHROPIC_API_KEY is not set in .env")
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._client

    def check_budget(self) -> None:
        spent = month_spend(self.session)
        budget = Decimal(str(self.settings.llm_monthly_budget_usd))
        if spent >= budget:
            raise BudgetExceeded(
                f"this month's LLM spend ${spent:.2f} has reached the ${budget:.2f} budget "
                "(LLM_MONTHLY_BUDGET_USD in .env)"
            )

    def structured(
        self,
        task: str,
        model: str,
        system: str,
        prompt: str,
        schema: type[T],
        effort: str = "low",
        max_tokens: int = 8000,
    ) -> T:
        """Ask `model` for an answer shaped like `schema`. Logs the call; raises LLMError."""
        self.check_budget()
        import anthropic

        call = LlmCall(at=datetime.now(UTC), task=task, model=model)
        try:
            response = self.client.messages.parse(
                model=model,
                max_tokens=max_tokens,
                # The instructions are the same on every call of a task: let them be cached.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": effort},
            )
        except anthropic.APIError as exc:
            call.ok, call.error = False, f"{type(exc).__name__}: {exc}"[:2000]
            self._record(call)
            raise LLMError(call.error) from exc
        except ValidationError as exc:
            # The SDK parses the answer before returning: a cut-off or malformed answer raises
            # here, without the response (so its tokens can't be logged).
            call.ok, call.error = False, f"answer did not match the schema: {exc}"[:2000]
            self._record(call)
            raise LLMError(call.error) from exc

        usage = response.usage
        call.input_tokens = usage.input_tokens or 0
        call.output_tokens = usage.output_tokens or 0
        call.cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
        call.cache_write_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
        call.cost_usd = cost(model, usage)
        parsed = response.parsed_output
        if response.stop_reason == "refusal":
            call.ok, call.error = False, "declined by the model's safety checks"
        elif response.stop_reason == "max_tokens":
            call.ok, call.error = False, f"answer cut off at max_tokens={max_tokens}"
        elif parsed is None:
            call.ok, call.error = False, "no structured answer in the response"
        self._record(call)
        if not call.ok:
            raise LLMError(call.error)
        return parsed

    def _record(self, call: LlmCall) -> None:
        self.session.add(call)
        self.session.commit()
        log.debug("%s %s: $%s %s", call.task, call.model, call.cost_usd, call.error or "")
