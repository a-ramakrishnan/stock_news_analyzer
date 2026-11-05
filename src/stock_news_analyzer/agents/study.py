"""The evidence: what each kind of event did to the stock afterwards (an event study, no AI).

Every event the agents stored becomes a *case*: a stock, the first trading day whose close
could reflect it (day 0) and a *kind*, such as "Order win: large (5%+ of a year's revenue)" or
"Results: revenue up, profit down". A case's reaction is the stock's move against the Nifty 50
(and its sector index) over 1, 5 and 20 trading days from day 0, compounded, as for the event
labels. Grouping the cases by kind gives, for each kind, how many there were, the median move,
the middle half of the moves and how often the stock rose: evidence for or against a rule of
thumb, and an input for the stocks owned.

Kinds come from:
- results: each quarter's revenue and profit growth against the same quarter a year before
  (XBRL or the Results Reader), dated by the results filing;
- orders: each order-win filing, sized against the company's revenue over the last four
  quarters;
- events: the Event Extractor's events of importance 3 or more that passed the QA check, by
  type and sentiment;
- red flags, by kind;
- bulk and block deals, by side.

The cases overlap: a results filing can also carry an event, and the market moves for many
reasons at once. The medians say what usually followed, not what caused it.
"""

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import qa
from stock_news_analyzer.agents.orders import INFLOW_KINDS
from stock_news_analyzer.agents.prices import (
    NIFTY,
    _compound,
    first_trading_day,
    index_returns,
    watchlist_benchmarks,
)
from stock_news_analyzer.models import (
    Deal,
    Document,
    DocumentCompany,
    Event,
    Order,
    QuarterlyResult,
    RedFlag,
    StockMove,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

HORIZONS = (1, 5, 20)
MIN_IMPORTANCE = 3  # events below this are routine
FEW = 10  # fewer cases than this: read the numbers as a hint, not evidence
FLAT = 0.02  # growth within ±2% counts as flat
RESULTS_WITHIN = timedelta(days=100)  # a quarter's results are filed within this of its end

GROUPS = ("Results", "Order wins", "Events", "Red flags", "Deals")

EVENT_NAMES = {
    "capex": "Capex",
    "guidance": "Guidance",
    "management_change": "Management change",
    "credit_rating": "Credit rating",
    "legal_regulatory": "Legal or regulatory",
    "acquisition": "Acquisition",
    "fundraise": "Fundraise",
    "promoter_action": "Promoter action",
    "disruption": "Disruption",
    "agreement": "Agreement",
    "approval": "Approval",
    "other": "Other",
}


@dataclass
class Case:
    group: str  # one of GROUPS
    kind: str  # e.g. "Results: revenue up, profit down"
    isin: str
    symbol: str
    at: datetime  # when the market could first know
    detail: str
    document_id: int | None = None
    day0: date | None = None
    excess: dict[int, float | None] = field(default_factory=dict)  # vs Nifty 50, by horizon
    sector_excess: dict[int, float | None] = field(default_factory=dict)


# --- the cases -------------------------------------------------------------------------


def _growth(now: Decimal | None, before: Decimal | None) -> float | None:
    if now is None or before is None or before <= 0:
        return None
    return float(now) / float(before) - 1


def _direction(g: float) -> str:
    return "up" if g > FLAT else "down" if g < -FLAT else "flat"


def results_kind(revenue: float | None, profit_now, profit_before) -> str | None:
    """The kind of a quarter's results from its growth against the year before."""
    if profit_now is not None and profit_before is not None:
        if profit_before > 0 >= profit_now:
            return "Results: swung to a loss"
        if profit_before <= 0 < profit_now:
            return "Results: back to a profit"
    profit = _growth(profit_now, profit_before)
    if revenue is None or profit is None:
        return None
    r, p = _direction(revenue), _direction(profit)
    if r == "up" and p == "up":
        return (
            "Results: revenue up, profit up 20%+"
            if profit >= 0.2
            else "Results: revenue and profit up"
        )
    if r == "up" and p == "down":
        return "Results: revenue up, profit down"
    if r == "down" and p == "up":
        return "Results: revenue down, profit up"
    if r == "down" and p == "down":
        return "Results: revenue and profit down"
    return "Results: little change"


def _results_filing(session: Session, isin: str, end: date, document_id: int | None):
    """(document id, published at) of the filing that announced a quarter's results."""
    if document_id:
        doc = session.get(Document, document_id)
        if doc is not None:
            return doc.id, doc.published_at
    row = session.execute(
        select(Document.id, Document.published_at)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .where(
            DocumentCompany.isin == isin,
            Document.doc_type == "results",
            Document.published_at > datetime.combine(end, time(), IST),
            Document.published_at < datetime.combine(end + RESULTS_WITHIN, time(), IST),
        )
        .order_by(Document.published_at)
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def result_cases(session: Session, symbols: dict[str, str]) -> list[Case]:
    cases = []
    quarters = session.scalars(
        select(QuarterlyResult)
        .where(
            QuarterlyResult.isin.in_(symbols),
            QuarterlyResult.months == 3,
            QuarterlyResult.primary,
        )
        .order_by(QuarterlyResult.isin, QuarterlyResult.period_end)
    ).all()
    by_company: dict[str, list[QuarterlyResult]] = {}
    for q in quarters:
        by_company.setdefault(q.isin, []).append(q)
    for isin, rows in by_company.items():
        for q in rows:
            before = next(
                (
                    p
                    for p in rows
                    if p.basis == q.basis and 350 <= (q.period_end - p.period_end).days <= 380
                ),
                None,
            )
            if before is None:
                continue
            revenue = _growth(q.revenue_cr, before.revenue_cr)
            kind = results_kind(revenue, q.pat_cr, before.pat_cr)
            if kind is None:
                continue
            doc_id, at = _results_filing(session, isin, q.period_end, q.document_id)
            if at is None:
                continue
            profit = _growth(q.pat_cr, before.pat_cr)
            detail = (
                f"{q.period}: revenue {_pct(revenue)}, profit {_pct(profit)} "
                f"on the year (Rs {q.pat_cr:,.0f} cr against Rs {before.pat_cr:,.0f} cr)"
            )
            cases.append(Case("Results", kind, isin, symbols[isin], at, detail, doc_id))
    return cases


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:+.0%}"


def yearly_revenue(session: Session, isin: str, before: date) -> float | None:
    """Revenue over the four quarters ended before a date, in Rs crore (the last quarter
    times four when fewer are stored)."""
    rows = session.scalars(
        select(QuarterlyResult.revenue_cr)
        .where(
            QuarterlyResult.isin == isin,
            QuarterlyResult.months == 3,
            QuarterlyResult.primary,
            QuarterlyResult.period_end < before,
            QuarterlyResult.revenue_cr.is_not(None),
        )
        .order_by(QuarterlyResult.period_end.desc())
        .limit(4)
    ).all()
    if not rows:
        return None
    return float(sum(rows)) if len(rows) == 4 else float(rows[0]) * 4


def order_kind(share: float | None) -> str:
    if share is None:
        return "Order win: size not given"
    if share >= 0.05:
        return "Order win: large (5%+ of a year's revenue)"
    if share >= 0.01:
        return "Order win: medium (1–5% of a year's revenue)"
    return "Order win: small (under 1% of a year's revenue)"


def order_cases(session: Session, symbols: dict[str, str]) -> list[Case]:
    """One case per order-win filing; its orders' values added up."""
    by_doc: dict[int, list[Order]] = {}
    for o in session.scalars(
        select(Order).where(Order.isin.in_(symbols), Order.kind.in_(INFLOW_KINDS))
    ):
        by_doc.setdefault(o.document_id, []).append(o)
    cases = []
    for doc_id, orders in by_doc.items():
        first = orders[0]
        values = [o.value_cr for o in orders if o.value_cr is not None]
        value = float(sum(values)) if values else None
        revenue = yearly_revenue(session, first.isin, first.announced_at.astimezone(IST).date())
        share = value / revenue if value is not None and revenue else None
        if value is not None and share is None:
            kind = "Order win: size not given"  # a value, but no revenue to compare it with
        else:
            kind = order_kind(share)
        clients = ", ".join(sorted({o.client for o in orders if o.client}))[:120]
        detail = (
            f"Rs {value:,.0f} cr" + (f" ({share:.1%} of a year's revenue)" if share else "")
            if value is not None
            else "value not disclosed"
        ) + (f" from {clients}" if clients else "")
        cases.append(
            Case(
                "Order wins",
                kind,
                first.isin,
                symbols[first.isin],
                first.announced_at,
                detail,
                doc_id,
            )
        )
    return cases


def event_cases(session: Session, symbols: dict[str, str]) -> list[Case]:
    events = session.scalars(
        select(Event).where(
            Event.isin.in_(symbols),
            Event.importance >= MIN_IMPORTANCE,
            Event.duplicate_of.is_(None),
            qa.shown(),
        )
    ).all()
    return [
        Case(
            "Events",
            f"{EVENT_NAMES.get(e.event_type, e.event_type)}: {e.sentiment}",
            e.isin,
            symbols[e.isin],
            e.published_at,
            e.headline,
            e.document_id,
        )
        for e in events
    ]


def flag_cases(session: Session, symbols: dict[str, str]) -> list[Case]:
    cases = []
    for f in session.scalars(select(RedFlag).where(RedFlag.isin.in_(symbols))):
        doc = session.get(Document, f.document_id) if f.document_id else None
        if doc is None:
            continue  # a deadline, not news the market saw at a known time
        kind = "Red flag: " + f.kind.replace("_", " ")
        cases.append(
            Case("Red flags", kind, f.isin, symbols[f.isin], doc.published_at, f.title, doc.id)
        )
    return cases


def deal_cases(session: Session, symbols: dict[str, str]) -> list[Case]:
    cases = []
    for d in session.scalars(select(Deal).where(Deal.isin.in_(symbols))):
        side = "buy" if d.side.upper() == "BUY" else "sell"
        # Deals are published after the close: the next session is the first to react.
        at = datetime.combine(d.trade_date, time(18, 0), IST)
        value = f", Rs {float(d.price) * d.quantity / 1e7:,.0f} cr" if d.price else ""
        detail = f"{d.client} {side}s {d.quantity:,} shares{value}"
        cases.append(
            Case("Deals", f"{d.kind.title()} deal: {side}", d.isin, symbols[d.isin], at, detail)
        )
    return cases


# --- the reactions ---------------------------------------------------------------------


def react(session: Session, cases: list[Case]) -> list[Case]:
    """Fill in each case's day 0 and its moves; cases whose window hasn't passed keep None."""
    calendar = sorted(index_returns(session, NIFTY))
    position = {d: i for i, d in enumerate(calendar)}
    moves_by_isin: dict[str, dict[date, StockMove]] = {}
    for case in cases:
        moves = moves_by_isin.get(case.isin)
        if moves is None:
            moves = moves_by_isin[case.isin] = {
                m.trade_date: m
                for m in session.scalars(select(StockMove).where(StockMove.isin == case.isin))
            }
        case.day0 = first_trading_day(case.at, calendar) if calendar else None
        for n in HORIZONS:
            case.excess[n] = case.sector_excess[n] = None
            if case.day0 is None or case.day0 not in position:
                continue
            days = calendar[position[case.day0] : position[case.day0] + n]
            if len(days) < n or any(d not in moves for d in days):
                continue
            window = [moves[d] for d in days]
            stock = _compound([m.stock_return for m in window])
            nifty = [m.nifty_return for m in window]
            if None not in nifty:
                case.excess[n] = stock - _compound(nifty)
            sector = [m.sector_return for m in window]
            if window[0].sector_index and None not in sector:
                case.sector_excess[n] = stock - _compound(sector)
    return cases


def all_cases(session: Session) -> list[Case]:
    """Every case for every watchlist stock, with its reactions, oldest first."""
    symbols = {
        c.isin: c.nse_symbol or c.bse_code or c.isin for c, _ in watchlist_benchmarks(session)
    }
    if not symbols:
        return []
    cases = (
        result_cases(session, symbols)
        + order_cases(session, symbols)
        + event_cases(session, symbols)
        + flag_cases(session, symbols)
        + deal_cases(session, symbols)
    )
    return sorted(react(session, cases), key=lambda c: c.at)


def owned_isins(session: Session) -> set[str]:
    return set(session.scalars(select(WatchlistItem.isin).where(WatchlistItem.owned)))


# --- the evidence ----------------------------------------------------------------------


@dataclass
class KindSummary:
    group: str
    kind: str
    cases: int  # with a reaction over the horizon
    waiting: int  # too recent for the horizon
    median: float | None
    low: float | None  # the middle half of the moves: 25th to 75th percentile
    high: float | None
    up: float | None  # share of cases where the stock beat the benchmark
    few: bool


def summarise(cases: list[Case], horizon: int = 5, sector: bool = False) -> list[KindSummary]:
    """One row per kind: the moves against the Nifty 50 (or the sector index) over `horizon`
    trading days. Kinds with the most cases first within each group."""
    by_kind: dict[tuple[str, str], list[Case]] = {}
    for c in cases:
        by_kind.setdefault((c.group, c.kind), []).append(c)
    rows = []
    for (group, kind), members in by_kind.items():
        moves = [
            m
            for c in members
            if (m := (c.sector_excess if sector else c.excess).get(horizon)) is not None
        ]
        quartiles = statistics.quantiles(moves, n=4) if len(moves) >= 2 else None
        rows.append(
            KindSummary(
                group=group,
                kind=kind,
                cases=len(moves),
                waiting=len(members) - len(moves),
                median=statistics.median(moves) if moves else None,
                low=quartiles[0] if quartiles else None,
                high=quartiles[2] if quartiles else None,
                up=sum(m > 0 for m in moves) / len(moves) if moves else None,
                few=len(moves) < FEW,
            )
        )
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(rows, key=lambda r: (order.get(r.group, 99), -r.cases, r.kind))


# --- by the size of the move -----------------------------------------------------------

# Bands of the move against the benchmark, finer near zero where most cases fall:
# (low, high), low included; None is open-ended.
MOVE_BANDS = (
    (None, -0.05),
    (-0.05, -0.02),
    (-0.02, -0.01),
    (-0.01, -0.005),
    (-0.005, 0.0),
    (0.0, 0.005),
    (0.005, 0.01),
    (0.01, 0.02),
    (0.02, 0.05),
    (0.05, None),
)


def band_label(low: float | None, high: float | None) -> str:
    def p(x: float) -> str:
        if x == 0:
            return "0%"
        return f"{x:+.1%}".replace(".0%", "%").replace("-", "−")

    if low is None:
        return f"{p(high)} or worse"
    if high is None:
        return f"{p(low)} or better"
    return f"{p(low)} to {p(high)}"


@dataclass
class MoveBand:
    label: str
    low: float | None
    high: float | None
    cases: list[Case]  # largest move first
    kinds: list[tuple[str, int, int]]  # (kind, cases in this band, cases of the kind in all)
    stocks: list[tuple[str, int]]  # (symbol, cases in this band), most first


def move_of(case: Case, horizon: int, sector: bool = False) -> float | None:
    return (case.sector_excess if sector else case.excess).get(horizon)


def by_move(cases: list[Case], horizon: int = 5, sector: bool = False) -> list[MoveBand]:
    """The cases grouped by how far the stock moved against the benchmark, from the biggest
    fall to the biggest rise: what kinds of event, and which stocks, lie behind moves of each
    size. Kinds are listed most frequent first, with how many cases of that kind there are in
    all, so "5 of 15" says a third of that kind's cases moved this much."""
    measured = [(c, m) for c in cases if (m := move_of(c, horizon, sector)) is not None]
    totals = Counter(c.kind for c, _ in measured)
    bands = []
    for low, high in MOVE_BANDS:
        inside = [
            (c, m) for c, m in measured if (low is None or m >= low) and (high is None or m < high)
        ]
        inside.sort(key=lambda cm: -abs(cm[1]))
        kinds = Counter(c.kind for c, _ in inside)
        bands.append(
            MoveBand(
                label=band_label(low, high),
                low=low,
                high=high,
                cases=[c for c, _ in inside],
                kinds=[(k, n, totals[k]) for k, n in kinds.most_common()],
                stocks=Counter(c.symbol for c, _ in inside).most_common(),
            )
        )
    return bands
