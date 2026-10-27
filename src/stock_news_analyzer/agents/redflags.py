"""Red-flag Monitor (agent 15): early warnings on governance and balance-sheet risks.

Rules in code, no LLM: the events are already typed and checked (agents/events.py and qa.py),
so the monitor only has to pick out the ones that warn of trouble and say how serious they are.

- An auditor resigning or removed (high); an internal or secretarial auditor (medium).
- The CEO, MD or CFO leaving: resigning or retiring early (high), otherwise ceasing (medium);
  an independent director resigning mid-term (medium).
- A rating downgrade (high); a negative outlook or watch (medium).
- A promoter's pledge invoked (high) or created (medium); a promoter selling (medium); a fund
  or other large holder selling 1% or more (low).
- A penalty, tax demand or regulator's order, by its size against revenue: 1% or more (high),
  0.1% or more (medium), smaller (low); any SEBI order is at least medium; a mixed outcome
  (a hearing adjourned, a stay continuing) one step lower.
- A disruption (fire, strike, shutdown): important ones (4-5) high, others medium.
- Results not filed by the deadline (45 days after a quarter or half year, 60 after the
  year): medium, high when 30 days late.

Each flag is raised once; a later scan re-grades it if the rules changed. Dismissing one
(`sna flags dismiss`) keeps it, with your note, and it is left alone.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.concalls import _month_end
from stock_news_analyzer.agents.events import amount
from stock_news_analyzer.models import (
    Company,
    Document,
    DocumentCompany,
    Event,
    QuarterlyResult,
    RedFlag,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

log = logging.getLogger(__name__)

SEVERITIES = ("high", "medium", "low")
LEAVING = re.compile(r"resign|quit|step(ped|s)? down|early retirement|remov|terminat")
CEASING = re.compile(r"ceas|retir|vacat|exit|demit|leav")
TOP_ROLES = re.compile(
    r"\bceo\b|chief executive|managing director|\bmd\b|\bcfo\b|chief financial|whole[- ]time"
)
AUDITOR = re.compile(r"auditor")
MINOR_AUDITOR = re.compile(r"internal|secretarial|cost auditor|tax auditor")
INDEPENDENT = re.compile(r"independent director")
TERM_ENDS = re.compile(r"completion of (his |her |the )?(tenure|term)|end of (his |her )?term")
DOWNGRADE = re.compile(r"downgrad|lowered|revised downward")
NEGATIVE_OUTLOOK = re.compile(r"negative|watch with developing|credit watch")
PLEDGE = re.compile(r"pledge|encumbr")
INVOKED = re.compile(r"invok|invoc")
CREATED = re.compile(r"creat|increas|additional")
SELLING = re.compile(r"\bsold\b|\bsell|\bsale\b|offload|divest|reduc")
REGULATOR = re.compile(r"\bsebi\b")
RESULTS_LAG = {3: 45, 6: 45}  # days after the period ends (LODR Regulation 33)
YEAR_END_LAG = 60  # the March quarter or half year comes with the annual results


@dataclass
class FlagsResult:
    raised: int = 0
    regraded: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class Flag:
    kind: str
    severity: str
    title: str
    detail: str | None = None


def _text(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).lower()


def _filed(e: Event) -> date:
    return e.published_at.astimezone(IST).date()


def judge(e: Event, symbol: str) -> Flag | None:
    """The red flag an event raises, if any."""
    who = _text(e.role, e.person)
    what = _text(e.action, e.headline)
    if e.event_type == "management_change":
        appointed = "appoint" in _text(e.action) and not CEASING.search(what)
        if appointed or TERM_ENDS.search(what):
            return None
        leaving, ceasing = LEAVING.search(what), CEASING.search(what)
        if not (leaving or ceasing):
            return None
        if AUDITOR.search(who) or (AUDITOR.search(what) and not TOP_ROLES.search(who)):
            if MINOR_AUDITOR.search(_text(who, what)):
                return Flag("auditor_exit", "medium", f"{symbol}: {e.headline}")
            return Flag("auditor_exit", "high", f"{symbol}: auditor exit. {e.headline}")
        if TOP_ROLES.search(who):
            severity = "high" if leaving else "medium"
            return Flag("key_exit", severity, f"{symbol}: {e.headline}")
        if INDEPENDENT.search(who) and leaving:
            return Flag("independent_director_exit", "medium", f"{symbol}: {e.headline}")
        return None
    if e.event_type == "credit_rating":
        rating = _text(e.action, e.rating_to, e.headline)
        if DOWNGRADE.search(rating):
            return Flag("downgrade", "high", f"{symbol}: {e.headline}")
        if NEGATIVE_OUTLOOK.search(_text(e.action, e.rating_to)):
            return Flag("negative_outlook", "medium", f"{symbol}: {e.headline}")
        return None
    if e.event_type == "promoter_action":
        if PLEDGE.search(what):
            if INVOKED.search(what):
                return Flag("pledge", "high", f"{symbol}: pledge invoked. {e.headline}")
            if CREATED.search(what) and "release" not in what:
                return Flag("pledge", "medium", f"{symbol}: {e.headline}")
            return None
        if SELLING.search(what):
            # A promoter selling is a signal; a fund or early investor trimming, much less.
            promoter = "promoter" in _text(e.person, e.counterparty, e.action, e.headline)
            if promoter and (e.stake_pct is None or e.stake_pct >= 1):
                return Flag("promoter_selling", "medium", f"{symbol}: {e.headline}")
            if (e.stake_pct or 0) >= 1:
                return Flag("holder_selling", "low", f"{symbol}: {e.headline}")
        return None
    if e.event_type == "legal_regulatory" and e.sentiment in ("negative", "mixed"):
        m = e.materiality
        if m is not None and m >= 0.01:
            severity = "high"
        elif m is not None and m >= 0.001:
            severity = "medium"
        elif m is None and e.importance >= 4:
            severity = "high"
        elif m is None and e.importance >= 3:
            severity = "medium"
        else:
            severity = "low"
        if REGULATOR.search(_text(e.counterparty, e.headline)) and severity == "low":
            severity = "medium"
        if e.sentiment == "mixed":  # a hearing adjourned, a stay continuing: one step down
            severity = {"high": "medium", "medium": "low"}.get(severity, severity)
        kind = "regulator" if REGULATOR.search(_text(e.counterparty)) else "legal"
        detail = amount(e) or None
        return Flag(kind, severity, f"{symbol}: {e.headline}", detail)
    if e.event_type == "disruption" and e.sentiment == "negative":
        severity = "high" if e.importance >= 4 else "medium" if e.importance >= 3 else "low"
        return Flag("disruption", severity, f"{symbol}: {e.headline}")
    return None


def _event_flags(session: Session, since: date | None) -> list[tuple[RedFlag, Event]]:
    from stock_news_analyzer.agents.qa import shown

    query = (
        select(Event, Company)
        .join(Company, Company.isin == Event.isin)
        .where(shown())
        .order_by(Event.published_at)
    )
    if since:
        query = query.where(Event.published_at >= datetime.combine(since, datetime.min.time(), IST))
    out = []
    for e, company in session.execute(query).all():
        flag = judge(e, company.nse_symbol or company.name)
        if flag is None:
            continue
        out.append(
            RedFlag(
                isin=e.isin,
                kind=flag.kind,
                severity=flag.severity,
                title=flag.title,
                detail=flag.detail,
                flagged_on=_filed(e),
                ref=f"event:{e.id}",
                event_id=e.id,
                document_id=e.document_id,
            )
        )
    return out


def _next_period(end: date, months: int) -> date:
    index = end.year * 12 + end.month - 1 + months
    return _month_end(index // 12, index % 12 + 1)


def overdue_results(session: Session, today: date) -> list[RedFlag]:
    """Watchlist companies whose next results are past the deadline with no results filing
    since the period ended. A company reporting quarterly is checked by quarter, an SME
    reporting half-yearly by half year."""
    from stock_news_analyzer.agents.results import period_label

    out = []
    for company in session.scalars(
        select(Company).join(WatchlistItem, WatchlistItem.isin == Company.isin)
    ):
        latest = session.scalars(
            select(QuarterlyResult)
            .where(QuarterlyResult.isin == company.isin, QuarterlyResult.months.in_((3, 6)))
            .order_by(QuarterlyResult.period_end.desc(), QuarterlyResult.months)
        ).first()
        if latest is None:
            continue  # nothing read yet: no basis for a deadline
        months = latest.months
        end = _next_period(latest.period_end, months)
        lag = YEAR_END_LAG if end.month == 3 else RESULTS_LAG[months]
        due = end + timedelta(days=lag)
        if today <= due:
            continue
        filed = session.scalar(
            select(Document.id)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(
                DocumentCompany.isin == company.isin,
                Document.doc_type == "results",
                Document.published_at > datetime.combine(end, datetime.max.time(), IST),
            )
            .limit(1)
        )
        if filed:
            continue
        label = period_label(end, months) or f"period ending {end:%d %b %Y}"
        late = (today - due).days
        symbol = company.nse_symbol or company.name
        out.append(
            RedFlag(
                isin=company.isin,
                kind="results_overdue",
                severity="high" if late >= 30 else "medium",
                title=f"{symbol}: {label} results not filed; due {due:%d %b %Y}",
                detail=f"{late} days past the deadline",
                flagged_on=due,
                ref=f"results:{label}",
            )
        )
    return out


def scan(session: Session, since: date | None = None, today: date | None = None) -> FlagsResult:
    """Raise the flags not raised yet, and re-grade the open ones whose rule has changed."""
    today = today or datetime.now(IST).date()
    result = FlagsResult()
    existing = {f.ref: f for f in session.scalars(select(RedFlag))}
    for flag in _event_flags(session, since) + overdue_results(session, today):
        old = existing.get(flag.ref)
        if old is None:
            session.add(flag)
            existing[flag.ref] = flag
            result.raised += 1
            result.by_severity[flag.severity] = result.by_severity.get(flag.severity, 0) + 1
        elif old.dismissed_at is None and (old.kind, old.severity) != (flag.kind, flag.severity):
            old.kind, old.severity, old.title, old.detail = (
                flag.kind,
                flag.severity,
                flag.title,
                flag.detail,
            )
            result.regraded += 1
    session.commit()
    return result


def open_flags(
    session: Session,
    days: int = 90,
    severities: tuple[str, ...] = SEVERITIES,
    isin: str | None = None,
    include_dismissed: bool = False,
) -> list[tuple[RedFlag, Company]]:
    """Flags of the last `days` days, most serious and newest first."""
    since = datetime.now(IST).date() - timedelta(days=days)
    query = (
        select(RedFlag, Company)
        .join(Company, Company.isin == RedFlag.isin)
        .where(RedFlag.flagged_on >= since, RedFlag.severity.in_(severities))
    )
    if isin:
        query = query.where(RedFlag.isin == isin)
    if not include_dismissed:
        query = query.where(RedFlag.dismissed_at.is_(None))
    rows = [tuple(r) for r in session.execute(query).all()]
    rows.sort(key=lambda r: (SEVERITIES.index(r[0].severity), -r[0].flagged_on.toordinal()))
    return rows


def dismiss(session: Session, flag_id: int, note: str | None = None) -> RedFlag:
    flag = session.get(RedFlag, flag_id)
    if flag is None:
        raise LookupError(f"no red flag #{flag_id}")
    flag.dismissed_at, flag.note = datetime.now(IST), note
    session.commit()
    return flag
