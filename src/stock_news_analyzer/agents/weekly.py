"""A stock week by week: how it moved against the market, everything that came out about it
that week, and whether the move went the way the news pointed (no AI).

Each week runs Monday to Friday. Its move is the stock's return against the Nifty 50 (and its
sector index), compounded over the week's trading days. An item counts in the week whose
prices could first react to it: news published after Friday's close counts in the next week,
as in the event study (agents/study.py).

The news tone of a week adds up what came out: positive news and events count +importance,
negative ones -importance; results, order wins and red flags count by their kind. Then:

- in line with the news: the stock moved more than in its usual week, the way the tone points;
- against the news: it moved more than usual, the other way;
- moved without news: it moved more than usual with no tone either way;
- quiet: a smaller move than its usual week (the median of its weekly moves in the period).
"""

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import study
from stock_news_analyzer.agents.digest import _dedupe_filings
from stock_news_analyzer.agents.prices import NIFTY, _compound, first_trading_day, index_returns
from stock_news_analyzer.models import (
    Company,
    Document,
    DocumentCompany,
    MoveExplanation,
    NewsTriage,
    PriceDaily,
    StockMove,
)
from stock_news_analyzer.sources.announcements import IST

PERIODS = (12, 24, 52)
MIN_MOVE = 0.01  # a week's move smaller than this is quiet, however calm the stock usually is
NEWS_IMPORTANCE = 3  # news below this importance doesn't count in the tone

VERDICTS = ("In line with the news", "Against the news", "Moved without news", "Quiet")

# How a case from the event study counts in a week's tone.
CASE_TONE = {
    "Results: revenue up, profit up 20%+": 4,
    "Results: revenue and profit up": 3,
    "Results: back to a profit": 3,
    "Results: revenue down, profit up": 1,
    "Results: little change": 0,
    "Results: revenue up, profit down": -2,
    "Results: revenue and profit down": -3,
    "Results: swung to a loss": -4,
    "Order win: large (5%+ of a year's revenue)": 4,
    "Order win: medium (1–5% of a year's revenue)": 2,
    "Order win: small (under 1% of a year's revenue)": 1,
    "Order win: size not given": 1,
}
SENTIMENT_SIGN = {"positive": 1, "negative": -1}


@dataclass
class Item:
    """One thing that came out in a week."""

    kind: str  # news, filing, result, order, event, flag, deal
    title: str
    at: datetime
    tone: int = 0  # what it adds to the week's tone
    sentiment: str | None = None  # for news and events
    importance: int | None = None
    summary: str | None = None
    url: str | None = None
    document_id: int | None = None
    detail: str | None = None  # e.g. the filing's type, the publisher


@dataclass
class Week:
    start: date  # Monday
    end: date  # Friday
    days: int = 0  # trading days with prices
    close: float | None = None
    stock: float | None = None  # the week's return
    excess: float | None = None  # against the Nifty 50
    sector_excess: float | None = None
    unusual: list[dict] = field(default_factory=list)  # {date, excess, cause, explanation}
    items: list[Item] = field(default_factory=list)
    tone: int = 0
    verdict: str = "Quiet"

    def of(self, *kinds: str) -> list[Item]:
        return [i for i in self.items if i.kind in kinds]


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weeks(session: Session, isin: str, count: int = 12, today: date | None = None) -> list[Week]:
    """The last `count` weeks of a stock, newest first (the current week included)."""
    today = today or datetime.now(IST).date()
    first = _monday(today) - timedelta(weeks=count - 1)
    out = {
        first + timedelta(weeks=i): Week(
            first + timedelta(weeks=i), first + timedelta(weeks=i, days=4)
        )
        for i in range(count)
    }
    company = session.get(Company, isin)
    symbol = (company.nse_symbol or company.bse_code or isin) if company else isin
    calendar = sorted(index_returns(session, NIFTY))

    def week_of(at: datetime) -> Week | None:
        day = first_trading_day(at, calendar) if calendar else None
        day = day or at.astimezone(IST).date()  # beyond the stored prices: its own date
        return out.get(_monday(day))

    _prices(session, isin, first, out)
    since = datetime.combine(first - timedelta(days=4), time(), IST)  # last Friday's late news
    _news(session, isin, since, week_of)
    _filings(session, isin, since, week_of)
    for case in (
        study.result_cases(session, {isin: symbol})
        + study.order_cases(session, {isin: symbol})
        + study.event_cases(session, {isin: symbol})
        + study.flag_cases(session, {isin: symbol})
        + study.deal_cases(session, {isin: symbol})
    ):
        if case.at < since or (week := week_of(case.at)) is None:
            continue
        week.items.append(_case_item(case))

    result = sorted(out.values(), key=lambda w: w.start, reverse=True)
    for week in result:
        week.items.sort(key=lambda i: (-(i.importance or 0), i.at))
        week.tone = sum(i.tone for i in week.items)
    _judge(result)
    return result


def _prices(session: Session, isin: str, first: date, out: dict[date, Week]) -> None:
    moves = session.scalars(
        select(StockMove)
        .where(StockMove.isin == isin, StockMove.trade_date >= first)
        .order_by(StockMove.trade_date)
    ).all()
    by_week: dict[date, list[StockMove]] = {}
    for m in moves:
        by_week.setdefault(_monday(m.trade_date), []).append(m)
    explained = {
        e.trade_date: e
        for e in session.scalars(
            select(MoveExplanation).where(
                MoveExplanation.isin == isin, MoveExplanation.trade_date >= first
            )
        )
    }
    closes = dict(
        session.execute(
            select(PriceDaily.trade_date, PriceDaily.close).where(
                PriceDaily.isin == isin, PriceDaily.trade_date >= first
            )
        ).all()
    )
    for monday, days in by_week.items():
        week = out.get(monday)
        if week is None:
            continue
        week.days = len(days)
        week.stock = _compound([m.stock_return for m in days])
        nifty = [m.nifty_return for m in days]
        if None not in nifty:
            week.excess = week.stock - _compound(nifty)
        sector = [m.sector_return for m in days]
        if days[0].sector_index and None not in sector:
            week.sector_excess = week.stock - _compound(sector)
        last = closes.get(days[-1].trade_date)
        week.close = float(last) if last is not None else None
        for m in days:
            if m.unusual:
                why = explained.get(m.trade_date)
                week.unusual.append(
                    {
                        "date": m.trade_date,
                        "excess": m.excess_return,
                        "cause": why.cause if why else None,
                        "explanation": why.explanation if why else None,
                    }
                )


def _news(session: Session, isin: str, since: datetime, week_of) -> None:
    rows = session.execute(
        select(Document, NewsTriage)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .outerjoin(
            NewsTriage,
            (NewsTriage.document_id == Document.id) & (NewsTriage.isin == DocumentCompany.isin),
        )
        .where(
            DocumentCompany.isin == isin,
            Document.doc_type == "news",
            Document.published_at >= since,
        )
    ).all()
    for doc, triage in rows:
        if triage is not None and (not triage.relevant or triage.duplicate_of is not None):
            continue  # off-topic, or a repeat of a story already counted
        week = week_of(doc.published_at)
        if week is None:
            continue
        tone = 0
        if triage is not None and triage.importance >= NEWS_IMPORTANCE:
            tone = SENTIMENT_SIGN.get(triage.sentiment, 0) * triage.importance
        week.items.append(
            Item(
                kind="news",
                title=doc.title,
                at=doc.published_at,
                tone=tone,
                sentiment=triage.sentiment if triage else None,
                importance=triage.importance if triage else None,
                summary=triage.summary if triage else None,
                url=doc.url,
                document_id=doc.id,
                detail=doc.publisher,
            )
        )


def _filings(session: Session, isin: str, since: datetime, week_of) -> None:
    docs = session.scalars(
        select(Document)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .where(
            DocumentCompany.isin == isin,
            Document.doc_type != "news",
            Document.published_at >= since,
        )
    ).all()
    for doc in _dedupe_filings(list(docs)):
        week = week_of(doc.published_at)
        if week is not None:
            week.items.append(
                Item(
                    kind="filing",
                    title=doc.title,
                    at=doc.published_at,
                    document_id=doc.id,
                    url=doc.attachment_url,
                    detail=doc.doc_type.replace("_", " "),
                )
            )


def _case_item(case: study.Case) -> Item:
    kinds = {"Results": "result", "Order wins": "order", "Events": "event", "Red flags": "flag"}
    kind = kinds.get(case.group, "deal")
    if kind == "event":
        sentiment = case.kind.rsplit(": ", 1)[-1]
        importance = case.importance or study.MIN_IMPORTANCE
        return Item(
            kind="event",
            title=case.detail,
            at=case.at,
            tone=SENTIMENT_SIGN.get(sentiment, 0) * importance,
            sentiment=sentiment,
            importance=importance,
            document_id=case.document_id,
            detail=case.kind,
        )
    tone = CASE_TONE.get(case.kind, -3 if kind == "flag" else 0)
    return Item(
        kind=kind,
        title=case.detail,
        at=case.at,
        tone=tone,
        sentiment="positive" if tone > 0 else "negative" if tone < 0 else "neutral",
        document_id=case.document_id,
        detail=study.short_kind(case.kind),
    )


def usual_move(weeks_: list[Week]) -> float:
    """The stock's usual week: the median size of its weekly moves against the Nifty, at least
    MIN_MOVE."""
    sizes = [abs(w.excess) for w in weeks_ if w.excess is not None]
    return max(statistics.median(sizes), MIN_MOVE) if sizes else MIN_MOVE


def _judge(weeks_: list[Week]) -> None:
    usual = usual_move(weeks_)
    for w in weeks_:
        if w.excess is None or abs(w.excess) < usual:
            w.verdict = "Quiet"
        elif w.tone == 0:
            w.verdict = "Moved without news"
        elif (w.tone > 0) == (w.excess > 0):
            w.verdict = "In line with the news"
        else:
            w.verdict = "Against the news"
