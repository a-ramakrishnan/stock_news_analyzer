"""Inputs for the stocks owned: a lean for each, the evidence behind it, and how the
portfolio's sectors compare with the Nifty 50's (no AI; inputs for your decisions, not advice).

A holding's lean adds up its recent events (the last LOOKBACK days) as the event study
(agents/study.py) values them: each event counts for the median move against the Nifty 50
that followed events of its kind across every stock followed, over HORIZON trading days.

- A kind with fewer than study.FEW cases counts in proportion (4 cases of 10: 40% of its
  median), so thin evidence moves the lean little.
- An event's weight halves every HALF_LIFE days: last week's results count more than last
  quarter's.
- The sum is the score. Over +THRESHOLD the lean is positive, under -THRESHOLD negative,
  otherwise neutral. An open high-severity red flag keeps a lean from being positive.

Beside each event is how far the stock has already moved against the Nifty 50 since it: a
move that has already happened may be priced in.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import study, weekly
from stock_news_analyzer.agents.prices import _compound
from stock_news_analyzer.models import (
    Company,
    IndexMember,
    PriceDaily,
    RedFlag,
    StockMove,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

LOOKBACK = 90  # days of events that count
HORIZON = 20  # trading days: the evidence a lean rests on
HALF_LIFE = 45.0  # days
THRESHOLD = 0.01  # a score this far from zero leans


@dataclass
class Reason:
    case: study.Case
    median: float | None  # what followed this kind, over HORIZON days, across all stocks
    cases: int  # how many cases that median rests on
    up: float | None  # share that beat the Nifty 50
    weight: float  # evidence strength x recency
    contribution: float  # median x weight
    since: float | None  # the stock's move against the Nifty 50 since the event


@dataclass
class Holding:
    isin: str
    symbol: str
    name: str
    quantity: float | None
    close: float | None
    value: float | None  # quantity x close
    industry: str | None
    lean: str  # positive, neutral or negative
    score: float
    reasons: list[Reason] = field(default_factory=list)
    flags: list[RedFlag] = field(default_factory=list)  # open, not dismissed
    weeks: dict[str, int] = field(default_factory=dict)  # verdict -> weeks, last 12
    move_12w: float | None = None  # against the Nifty 50, last 12 weeks


def _since(moves: list[StockMove], day0: date | None) -> float | None:
    after = [m for m in moves if day0 is not None and m.trade_date >= day0]
    if not after or any(m.nifty_return is None for m in after):
        return None
    return _compound([m.stock_return for m in after]) - _compound([m.nifty_return for m in after])


def lean_of(score: float, flags: list[RedFlag]) -> str:
    if score <= -THRESHOLD:
        return "negative"
    if score >= THRESHOLD and not any(f.severity == "high" for f in flags):
        return "positive"
    return "neutral"


def holdings(session: Session, today: date | None = None) -> list[Holding]:
    """Each stock owned with its lean and reasons, the strongest lean first."""
    today = today or datetime.now(IST).date()
    cases = study.all_cases(session)
    evidence = {r.kind: r for r in study.summarise(cases, HORIZON)}
    owned = session.execute(
        select(WatchlistItem, Company)
        .join(Company, Company.isin == WatchlistItem.isin)
        .where(WatchlistItem.owned)
    ).all()
    out = []
    for item, company in owned:
        isin = company.isin
        close = session.scalar(
            select(PriceDaily.close)
            .where(PriceDaily.isin == isin)
            .order_by(PriceDaily.trade_date.desc())
            .limit(1)
        )
        moves = list(
            session.scalars(
                select(StockMove).where(StockMove.isin == isin).order_by(StockMove.trade_date)
            )
        )
        reasons = []
        for case in cases:
            if case.isin != isin:
                continue
            age = (today - case.at.astimezone(IST).date()).days
            if age < 0 or age > LOOKBACK:
                continue
            row = evidence.get(case.kind)
            median = row.median if row else None
            n = row.cases if row else 0
            strength = min(n / study.FEW, 1.0)
            weight = strength * 0.5 ** (age / HALF_LIFE)
            reasons.append(
                Reason(
                    case=case,
                    median=median,
                    cases=n,
                    up=row.up if row else None,
                    weight=weight,
                    contribution=(median or 0.0) * weight,
                    since=_since(moves, case.day0),
                )
            )
        reasons.sort(key=lambda r: -abs(r.contribution))
        flags = list(
            session.scalars(
                select(RedFlag).where(RedFlag.isin == isin, RedFlag.dismissed_at.is_(None))
            )
        )
        score = sum(r.contribution for r in reasons)
        ws = weekly.weeks(session, isin, 12, today=today)
        priced = [w for w in ws if w.excess is not None]
        quantity = float(item.quantity) if item.quantity is not None else None
        out.append(
            Holding(
                isin=isin,
                symbol=company.nse_symbol or company.bse_code or isin,
                name=company.name,
                quantity=quantity,
                close=float(close) if close is not None else None,
                value=quantity * float(close) if quantity and close is not None else None,
                industry=company.industry,
                lean=lean_of(score, flags),
                score=score,
                reasons=reasons,
                flags=flags,
                weeks={v: sum(w.verdict == v for w in priced) for v in weekly.VERDICTS},
                move_12w=(
                    _compound([w.stock for w in priced])
                    - _compound([w.stock - w.excess for w in priced])
                    if priced
                    else None
                ),
            )
        )
    return sorted(out, key=lambda h: -abs(h.score))


def sector_weights(session: Session, held: list[Holding]) -> list[dict]:
    """The portfolio's weight in each NSE industry against the Nifty 50's (by market cap, from
    the list `sna watchlist nifty50` saved). Holdings without a quantity count equally when
    none has one. Rows: {industry, mine, nifty}; nifty is None when the list isn't saved."""
    values = [h.value for h in held]
    if held and all(v is None for v in values):
        weights = {h.isin: 1 / len(held) for h in held}
    else:
        total = sum(v for v in values if v)
        weights = {h.isin: (h.value or 0) / total for h in held} if total else {}
    mine: dict[str, float] = {}
    for h in held:
        key = h.industry or "Unknown"
        mine[key] = mine.get(key, 0.0) + weights.get(h.isin, 0.0)

    members = session.execute(
        select(IndexMember.industry, func.sum(Company.market_cap_cr))
        .join(Company, Company.isin == IndexMember.isin)
        .where(IndexMember.index_name == "Nifty 50", Company.market_cap_cr.is_not(None))
        .group_by(IndexMember.industry)
    ).all()
    caps = {industry or "Unknown": float(cap or Decimal(0)) for industry, cap in members}
    total_cap = sum(caps.values())
    nifty = {k: v / total_cap for k, v in caps.items()} if total_cap else {}
    rows = [
        {"industry": k, "mine": mine.get(k, 0.0), "nifty": nifty.get(k) if nifty else None}
        for k in set(mine) | set(nifty)
    ]
    return sorted(rows, key=lambda r: -(max(r["mine"], r["nifty"] or 0)))
