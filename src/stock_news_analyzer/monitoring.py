"""Live monitoring: how the AI agents are doing on real work, day by day, from what they already
store (no extra AI calls).

Each monitor is a daily rate (what share of a day's work passed a check) read from the tables
the agents write: the QA Checker's verdicts and quotes found for events, your accept and reject
decisions, results PDFs read or not, order amounts found in their filings, earnings-call quotes
found, Research brief parts dropped by the number check, and AI calls that failed. A monitor may
be split (by prompt version, or by task) so a change shows where it came from.

An alert is raised when the last 7 days are worse than the 28 days before by more than chance
explains: at least 5 points, and at least 2.5 standard errors of the difference, with enough
work in both windows (10 and 20). Alerts show on the Monitoring page and in the morning digest.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, case, cast, func, literal, select
from sqlalchemy.orm import Session

from stock_news_analyzer.models import (
    Concall,
    ConcallPoint,
    Event,
    EventFiling,
    LlmCall,
    Order,
    ResearchBrief,
    ResultFiling,
)
from stock_news_analyzer.sources.announcements import IST

RECENT_DAYS = 7
BASE_DAYS = 28
MIN_RECENT, MIN_BASE = 10, 20
MIN_DROP = 0.05
Z = 2.5


@dataclass(frozen=True)
class Monitor:
    id: str
    agent: str | None  # the agent's job on the Agent map; None for all of them
    title: str
    about: str
    query: Callable  # (session, since) -> rows of (day, group, passed, total)
    higher_is_better: bool = True
    split: str = ""  # what the groups are, e.g. "prompt version"


def _day(column):
    return cast(func.timezone("Asia/Kolkata", column), Date)


def _rows(session: Session, day, group, passed, total, where, since, *joins, base=None):
    query = select(
        day.label("day"), group.label("grp"), passed.label("passed"), total.label("total")
    )
    if base is not None:
        query = query.select_from(base)
    for target, on in joins:
        query = query.join(target, on)
    query = query.where(*where, day >= since).group_by(day, group)
    return [
        (r.day, r.grp or "-", int(r.passed or 0), int(r.total or 0)) for r in session.execute(query)
    ]


def _events_checked(session, since):
    day = _day(Event.created_at)
    checked = Event.qa_status.in_(("passed", "flagged", "failed"))
    return _rows(
        session,
        day,
        Event.prompt_version,
        func.sum(case((Event.qa_status == "passed", 1), else_=0)),
        func.sum(case((checked, 1), else_=0)),
        [Event.duplicate_of.is_(None)],
        since,
    )


def _events_quotes(session, since):
    day = _day(Event.created_at)
    return _rows(
        session,
        day,
        Event.prompt_version,
        func.sum(case((Event.quote_found.is_(True), 1), else_=0)),
        func.count(),
        [Event.duplicate_of.is_(None)],
        since,
    )


def _events_rejected(session, since):
    day = _day(Event.reviewed_at)
    return _rows(
        session,
        day,
        Event.prompt_version,
        func.sum(case((Event.review == "rejected", 1), else_=0)),
        func.count(),
        [Event.review.isnot(None), Event.reviewed_at.isnot(None)],
        since,
    )


def _event_filings_failed(session, since):
    day = _day(EventFiling.created_at)
    return _rows(
        session,
        day,
        EventFiling.model,
        func.sum(case((EventFiling.status == "failed", 1), else_=0)),
        func.count(),
        [EventFiling.model.isnot(None)],
        since,
    )


def _results_read(session, since):
    day = _day(ResultFiling.created_at)
    attempted = ResultFiling.status.in_(("read", "failed", "no_figures"))
    return _rows(
        session,
        day,
        ResultFiling.model,
        func.sum(case((ResultFiling.status == "read", 1), else_=0)),
        func.sum(case((attempted, 1), else_=0)),
        [ResultFiling.model.isnot(None), attempted],
        since,
    )


def _orders_amounts(session, since):
    day = _day(Order.created_at)
    return _rows(
        session,
        day,
        Order.model,
        func.sum(case((Order.value_found.is_(True), 1), else_=0)),
        func.count(),
        [Order.value_as_written.isnot(None)],
        since,
    )


def _concall_quotes(session, since):
    day = _day(Concall.created_at)
    return _rows(
        session,
        day,
        Concall.prompt_version,
        func.sum(case((ConcallPoint.quote_found.is_(True), 1), else_=0)),
        func.count(),
        [ConcallPoint.quote.isnot(None)],
        since,
        (Concall, Concall.id == ConcallPoint.concall_id),
        base=ConcallPoint,
    )


def _briefs_dropped(session, since):
    day = _day(ResearchBrief.created_at)
    dropped = func.jsonb_array_length(ResearchBrief.dropped) > 0
    return _rows(
        session,
        day,
        ResearchBrief.model,
        func.sum(case((dropped, 1), else_=0)),
        func.count(),
        [],
        since,
    )


def _ai_failures(session, since):
    day = _day(LlmCall.at)
    return _rows(
        session,
        day,
        LlmCall.task,
        func.sum(case((LlmCall.ok.is_(False), 1), else_=0)),
        func.count(),
        [LlmCall.task != literal("eval-draft")],
        since,
    )


MONITORS = [
    Monitor(
        "events.qa",
        "events",
        "Events passing the QA check",
        "Share of new events the QA Checker passed (not flagged or failed).",
        _events_checked,
        split="prompt version",
    ),
    Monitor(
        "events.quotes",
        "events",
        "Event quotes found",
        "Share of new events whose quote is in the filing's text.",
        _events_quotes,
        split="prompt version",
    ),
    Monitor(
        "events.rejected",
        "events",
        "Events you rejected",
        "Share of the events you reviewed that you rejected.",
        _events_rejected,
        higher_is_better=False,
        split="prompt version",
    ),
    Monitor(
        "events.failed",
        "events",
        "Filings the Event Extractor couldn't read",
        "Share of filings read whose answer was unusable.",
        _event_filings_failed,
        higher_is_better=False,
        split="model",
    ),
    Monitor(
        "results.read",
        "results",
        "Results PDFs read",
        "Share of results PDFs the Results reader got figures from (not failed or empty).",
        _results_read,
        split="model",
    ),
    Monitor(
        "orders.amounts",
        "orders",
        "Order amounts found",
        "Share of orders whose amount, as written, is in the filing.",
        _orders_amounts,
        split="model",
    ),
    Monitor(
        "concalls.quotes",
        "concalls",
        "Earnings-call quotes found",
        "Share of points from earnings calls whose quote is in the transcript.",
        _concall_quotes,
        split="prompt version",
    ),
    Monitor(
        "briefs.dropped",
        "briefs",
        "Research brief views with parts dropped",
        "Share of new views where the number check dropped a part.",
        _briefs_dropped,
        higher_is_better=False,
        split="model",
    ),
    Monitor(
        "ai.failures",
        None,
        "AI calls that failed",
        "Share of AI calls that failed (API errors, cut-off or unusable answers, refusals).",
        _ai_failures,
        higher_is_better=False,
        split="task",
    ),
]
BY_ID = {m.id: m for m in MONITORS}


def today() -> date:
    return datetime.now(IST).date()


def series(session: Session, monitor: Monitor, days: int = 90, now: date | None = None):
    """Daily rows for a monitor: [{day, group, passed, total}], oldest first."""
    since = (now or today()) - timedelta(days=days)
    rows = monitor.query(session, since)
    return sorted(
        ({"day": d, "group": g, "passed": p, "total": t} for d, g, p, t in rows if t),
        key=lambda r: (r["day"], r["group"]),
    )


@dataclass
class Status:
    monitor: Monitor
    recent: float | None  # the last 7 days' rate
    base: float | None  # the 28 days before
    recent_n: int
    base_n: int
    alert: bool
    message: str


def status(session: Session, monitor: Monitor, now: date | None = None) -> Status:
    """The monitor's last 7 days against the 28 before, and whether that is an alert."""
    now = now or today()
    split = now - timedelta(days=RECENT_DAYS)
    start = split - timedelta(days=BASE_DAYS)
    rows = series(session, monitor, RECENT_DAYS + BASE_DAYS, now)
    rp = sum(r["passed"] for r in rows if r["day"] > split)
    rn = sum(r["total"] for r in rows if r["day"] > split)
    bp = sum(r["passed"] for r in rows if start < r["day"] <= split)
    bn = sum(r["total"] for r in rows if start < r["day"] <= split)
    recent = rp / rn if rn else None
    base = bp / bn if bn else None
    if recent is None or base is None or rn < MIN_RECENT or bn < MIN_BASE:
        return Status(monitor, recent, base, rn, bn, False, "not enough work yet to compare")
    pooled = (rp + bp) / (rn + bn)
    se = math.sqrt(max(pooled * (1 - pooled), 1e-9) * (1 / rn + 1 / bn))
    worse = (base - recent) if monitor.higher_is_better else (recent - base)
    alert = worse >= max(MIN_DROP, Z * se)
    verb = "fell" if recent < base else "rose"
    message = (
        f"{monitor.title} {verb} to {recent:.0%} in the last {RECENT_DAYS} days "
        f"({rn} items) from {base:.0%} in the {BASE_DAYS} days before ({bn})"
    )
    if not alert:
        message += "; within what chance explains" if abs(recent - base) >= 0.005 else ""
    return Status(monitor, recent, base, rn, bn, alert, message)


def statuses(session: Session, now: date | None = None) -> list[Status]:
    return [status(session, m, now) for m in MONITORS]


def alerts(session: Session, now: date | None = None) -> list[Status]:
    return [s for s in statuses(session, now) if s.alert]


def spend(session: Session, days: int = 30, now: date | None = None) -> list[dict]:
    """AI spend and calls by day and task."""
    since = (now or today()) - timedelta(days=days)
    day = _day(LlmCall.at)
    rows = session.execute(
        select(day.label("day"), LlmCall.task, func.sum(LlmCall.cost_usd), func.count())
        .where(day >= since)
        .group_by(day, LlmCall.task)
    )
    return [{"day": d, "task": t, "cost_usd": float(c or 0), "calls": n} for d, t, c, n in rows]


def checked_at() -> datetime:
    return datetime.now(UTC)
