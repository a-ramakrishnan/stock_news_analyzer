"""What the market pays for a stock's earnings: trailing P/E, point in time, against its own
history, its sector index and the Nifty 50 (no AI).

Trailing EPS on a day is the sum of the last four quarters' basic EPS whose results were out
by then (dated by the results filing, else 45 days after the quarter ended, the SEBI
deadline). A bonus issue or split after a quarter's results scales that quarter's EPS by the
action's price factor, the same factor the daily returns use, so EPS and price stay on one
footing. P/E is the close over trailing EPS, and is left out while EPS is not positive.
NSE's index files give the sector index's and the Nifty 50's own P/E each day.
"""

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import study
from stock_news_analyzer.agents.prices import MAIN_SERIES, NIFTY
from stock_news_analyzer.models import (
    Company,
    CorporateAction,
    IndexDaily,
    PriceDaily,
    QuarterlyResult,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

YEARS = 3  # the history a P/E is compared with
RESULTS_DEADLINE = timedelta(days=45)  # LODR: quarterly results within 45 days


@dataclass
class Quarter:
    end: date
    eps: float
    known: date  # when the market had it


@dataclass
class Valuation:
    isin: str
    close: float | None = None
    close_date: date | None = None
    eps_ttm: float | None = None  # trailing twelve months, rupees
    eps_growth: float | None = None  # trailing EPS against a year earlier
    pe: float | None = None
    pe_median: float | None = None  # over the last YEARS years
    pe_low: float | None = None  # 10th percentile
    pe_high: float | None = None  # 90th percentile
    pe_percentile: float | None = None  # where today's P/E sits in its history, 0..1
    sector_index: str | None = None
    sector_pe: float | None = None
    sector_pe_median: float | None = None
    nifty_pe: float | None = None
    nifty_pe_median: float | None = None
    market_cap_cr: float | None = None  # BSE's figure
    quarters: list[Quarter] = field(default_factory=list)  # newest first, the four in eps_ttm
    series: list[tuple[date, float]] = field(default_factory=list)  # weekly P/E, oldest first
    note: str | None = None  # why there is no P/E


def closes(session: Session, isin: str, since: date) -> dict[date, float]:
    """The main series' close each day."""
    rows = session.execute(
        select(PriceDaily.trade_date, PriceDaily.series, PriceDaily.close).where(
            PriceDaily.isin == isin, PriceDaily.trade_date >= since, PriceDaily.close.is_not(None)
        )
    ).all()
    best: dict[date, tuple[int, float]] = {}
    for d, series, close in rows:
        rank = MAIN_SERIES.index(series) if series in MAIN_SERIES else len(MAIN_SERIES)
        if d not in best or rank < best[d][0]:
            best[d] = (rank, float(close))
    return {d: c for d, (_, c) in sorted(best.items())}


def quarters(session: Session, isin: str) -> list[Quarter]:
    """Each quarter's basic EPS and the day it became known, oldest first."""
    out = []
    for q in session.scalars(
        select(QuarterlyResult)
        .where(
            QuarterlyResult.isin == isin,
            QuarterlyResult.months == 3,
            QuarterlyResult.primary,
            QuarterlyResult.eps.is_not(None),
        )
        .order_by(QuarterlyResult.period_end)
    ):
        _, at = study._results_filing(session, isin, q.period_end, q.document_id)
        known = at.astimezone(IST).date() if at else q.period_end + RESULTS_DEADLINE
        out.append(Quarter(q.period_end, float(q.eps), known))
    return out


def _factors(session: Session, symbol: str | None) -> list[tuple[date, float]]:
    """(ex-date, price factor) of the bonus issues and splits."""
    if not symbol:
        return []
    return [
        (a.ex_date, a.price_factor)
        for a in session.scalars(select(CorporateAction).where(CorporateAction.symbol == symbol))
        if a.price_factor and a.price_factor != 1.0
    ]


def eps_ttm(qs: list[Quarter], day: date, factors: list[tuple[date, float]]):
    """(trailing EPS, the four quarters) as known on `day`, adjusted to that day's shares;
    None when four consecutive quarters aren't known."""
    known = [q for q in qs if q.known <= day][-4:]
    if len(known) < 4 or (known[-1].end - known[0].end).days > 300:
        return None, known
    total = 0.0
    for q in known:
        eps = q.eps
        for ex, factor in factors:
            if q.known < ex <= day:
                eps *= factor  # earned on the old share count
        total += eps
    return total, known


def _percentile(values: list[float], x: float) -> float:
    return sum(v <= x for v in values) / len(values)


def _index_pe(session: Session, name: str | None, since: date) -> tuple[float | None, float | None]:
    if not name:
        return None, None
    rows = [
        float(pe)
        for (pe,) in session.execute(
            select(IndexDaily.pe)
            .where(
                IndexDaily.index_name == name,
                IndexDaily.trade_date >= since,
                IndexDaily.pe.is_not(None),
            )
            .order_by(IndexDaily.trade_date)
        )
    ]
    return (rows[-1], statistics.median(rows)) if rows else (None, None)


def valuation(session: Session, isin: str, today: date | None = None) -> Valuation:
    today = today or datetime.now(IST).date()
    since = today - timedelta(days=365 * YEARS)
    company = session.get(Company, isin)
    v = Valuation(isin=isin)
    if company is None:
        v.note = "unknown company"
        return v
    v.market_cap_cr = float(company.market_cap_cr) if company.market_cap_cr else None
    v.sector_index = session.scalar(
        select(WatchlistItem.sector_index).where(WatchlistItem.isin == isin)
    )
    v.sector_pe, v.sector_pe_median = _index_pe(session, v.sector_index, since)
    v.nifty_pe, v.nifty_pe_median = _index_pe(session, NIFTY, since)

    prices = closes(session, isin, since)
    if prices:
        v.close_date, v.close = list(prices.items())[-1]
    qs = quarters(session, isin)
    factors = _factors(session, company.nse_symbol)
    day = v.close_date or today
    v.eps_ttm, used = eps_ttm(qs, day, factors)
    v.quarters = list(reversed(used))
    year_ago, _ = eps_ttm(qs, day - timedelta(days=365), factors)
    if v.eps_ttm is not None and year_ago and year_ago > 0:
        v.eps_growth = v.eps_ttm / year_ago - 1
    if v.eps_ttm is None:
        v.note = "fewer than four quarters of EPS stored"
    elif v.eps_ttm <= 0:
        v.note = "trailing EPS is not positive: no P/E"
    elif v.close is not None:
        v.pe = v.close / v.eps_ttm

    history = []
    last_week = None
    for d, close in prices.items():
        eps, _ = eps_ttm(qs, d, factors)
        if not eps or eps <= 0:
            continue
        pe = close / eps
        history.append(pe)
        week = d.isocalendar()[:2]
        if week != last_week:
            v.series.append((d, pe))
            last_week = week
        else:
            v.series[-1] = (d, pe)
    if len(history) >= 20:
        ordered = sorted(history)
        v.pe_median = statistics.median(ordered)
        v.pe_low = ordered[int(0.1 * (len(ordered) - 1))]
        v.pe_high = ordered[int(0.9 * (len(ordered) - 1))]
        if v.pe is not None:
            v.pe_percentile = _percentile(ordered, v.pe)
    return v
