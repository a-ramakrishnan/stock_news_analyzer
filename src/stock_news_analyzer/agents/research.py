"""The facts behind a stock's research brief, each with how far it can be trusted and where it
came from (no AI). The Research brief page lays them out in the briefing grammar: a lede
with key numbers, then folds (ui/app.py research_page).

Every figure carries an evidence badge:
- Filed: taken as filed, from an XBRL file or the exchange's own data;
- Read by AI: read from a filing by an agent, with the QA check passed;
- Market: prices and NSE's index files;
- Stale: older than a quarter by now;
- Not disclosed: the filings don't carry it.

Step 31.1 assembles valuation, the balance sheet and cash flow, peers, the results trend and
what's coming; step 31.2 adds the AI-written view on top.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import valuation as val
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.agents.results import XBRL
from stock_news_analyzer.models import (
    BalanceSheet,
    Company,
    CorporateAction,
    Document,
    DocumentCompany,
    Promise,
    QuarterlyResult,
    RedFlag,
)
from stock_news_analyzer.sources.announcements import IST

FILED, AI, MARKET, STALE, NOT_DISCLOSED = (
    "Filed",
    "Read by AI",
    "Market",
    "Stale",
    "Not disclosed",
)
STALE_AFTER = timedelta(days=200)  # a half year's figures, plus the time to file them
COMING_DAYS = 120  # how far ahead "what's coming" looks
QUARTERS = 8


@dataclass
class Fact:
    label: str
    value: float | None
    unit: str  # "cr", "x", "%", "₹", ""
    badge: str
    when: date | None = None
    source: str | None = None  # a link or a description
    note: str | None = None


@dataclass
class Coming:
    day: date
    what: str
    badge: str
    source: str | None = None


@dataclass
class Peer:
    symbol: str
    name: str
    market_cap_cr: float | None
    return_1y: float | None
    pe: float | None
    revenue_growth: float | None  # latest quarter against a year before
    profit_growth: float | None
    period: str | None
    badge: str
    is_subject: bool = False


@dataclass
class Facts:
    isin: str
    symbol: str
    name: str
    industry: str | None
    sector_index: str | None
    valuation: val.Valuation
    quarters: list[dict] = field(default_factory=list)  # newest first
    balance: list[Fact] = field(default_factory=list)
    balance_end: date | None = None
    peers: list[Peer] = field(default_factory=list)
    peer_basis: str = "none"
    coming: list[Coming] = field(default_factory=list)
    flags: list[RedFlag] = field(default_factory=list)
    filings: int = 0
    news: int = 0
    first_filing: date | None = None


def _badge_for_result(model: str | None) -> str:
    return FILED if model == XBRL else AI


def quarter_trend(session: Session, isin: str) -> list[dict]:
    """The last QUARTERS quarters, newest first, with growth on the year and margins."""
    rows = list(
        session.scalars(
            select(QuarterlyResult)
            .where(
                QuarterlyResult.isin == isin,
                QuarterlyResult.months == 3,
                QuarterlyResult.primary,
            )
            .order_by(QuarterlyResult.period_end.desc())
        )
    )
    by_end = {r.period_end: r for r in rows}
    out = []
    for r in rows[:QUARTERS]:
        before = next(
            (
                by_end[e]
                for e in by_end
                if 350 <= (r.period_end - e).days <= 380 and by_end[e].basis == r.basis
            ),
            None,
        )

        def growth(now, then):
            if now is None or then is None or then <= 0:
                return None
            return float(now) / float(then) - 1

        revenue = float(r.revenue_cr) if r.revenue_cr is not None else None
        pat = float(r.pat_cr) if r.pat_cr is not None else None
        out.append(
            {
                "period": r.period,
                "end": r.period_end,
                "revenue": revenue,
                "pat": pat,
                "eps": float(r.eps) if r.eps is not None else None,
                "margin": pat / revenue if revenue and pat is not None else None,
                "revenue_growth": growth(r.revenue_cr, before.revenue_cr if before else None),
                "pat_growth": growth(r.pat_cr, before.pat_cr if before else None),
                "basis": r.basis,
                "badge": _badge_for_result(r.model),
            }
        )
    return out


def balance_facts(session: Session, isin: str, today: date) -> tuple[list[Fact], date | None]:
    """The latest balance sheet and the year's (or half year's) cash flow, with ratios."""
    row = session.scalars(
        select(BalanceSheet)
        .where(BalanceSheet.isin == isin, BalanceSheet.as_written != {})
        .order_by(BalanceSheet.period_end.desc())
        .limit(1)
    ).first()
    if row is None:
        return [], None
    badge = STALE if today - row.period_end > STALE_AFTER else FILED

    def f(x):
        return float(x) if x is not None else None

    equity, debt, cash = f(row.equity_cr), f(row.borrowings_cr), f(row.cash_cr)
    cfo, capex = f(row.cfo_cr), f(row.capex_cr)
    span = "year" if row.months == 12 else "half year"
    profit = sum(
        float(q.pat_cr)
        for q in session.scalars(
            select(QuarterlyResult).where(
                QuarterlyResult.isin == isin,
                QuarterlyResult.months == 3,
                QuarterlyResult.primary,
                QuarterlyResult.period_end <= row.period_end,
                QuarterlyResult.period_end > row.period_end - timedelta(days=31 * row.months),
                QuarterlyResult.pat_cr.is_not(None),
            )
        )
    )
    facts = []

    def add(label, value, unit, note=None):
        facts.append(
            Fact(
                label,
                value,
                unit,
                badge if value is not None else NOT_DISCLOSED,
                row.period_end,
                row.source,
                note,
            )
        )

    add("Equity", equity, "cr", row.as_written.get("equity"))
    add("Borrowings", debt, "cr", row.as_written.get("borrowings"))
    add("Cash", cash, "cr", row.as_written.get("cash"))
    add(
        "Net debt",
        debt - cash if debt is not None and cash is not None else None,
        "cr",
        "borrowings less cash; negative is net cash",
    )
    add(
        "Debt to equity",
        debt / equity if debt is not None and equity else None,
        "x",
    )
    add(f"Cash from operations, {span}", cfo, "cr", row.as_written.get("cfo"))
    add(f"Capex, {span}", capex, "cr", row.as_written.get("capex"))
    add(
        f"Free cash flow, {span}",
        cfo - capex if cfo is not None and capex is not None else None,
        "cr",
        "cash from operations less capex",
    )
    add(
        "Cash from operations to profit",
        cfo / profit if cfo is not None and profit > 0 else None,
        "x",
        "near 1 or above: profit turns into cash",
    )
    return facts, row.period_end


def _return_1y(session: Session, isin: str, today: date) -> float | None:
    prices = val.closes(session, isin, today - timedelta(days=380))
    if len(prices) < 2:
        return None
    days = list(prices)
    start = next((d for d in days if d >= today - timedelta(days=365)), days[0])
    return prices[days[-1]] / prices[start] - 1  # price only; splits can distort it


def _latest_growth(session: Session, isin: str):
    trend = quarter_trend(session, isin)
    if not trend:
        return None, None, None, NOT_DISCLOSED
    q = trend[0]
    return q["revenue_growth"], q["pat_growth"], q["period"], q["badge"]


def peer_table(session: Session, company: Company, today: date) -> tuple[list[Peer], str]:
    peers, basis = wl.peers_for(session, company)
    rows = []
    for c, is_subject in [(company, True)] + [(p, False) for p in peers]:
        v = val.valuation(session, c.isin, today)
        revenue, profit, period, badge = _latest_growth(session, c.isin)
        rows.append(
            Peer(
                symbol=c.nse_symbol or c.bse_code or c.isin,
                name=c.name,
                market_cap_cr=float(c.market_cap_cr) if c.market_cap_cr else None,
                return_1y=_return_1y(session, c.isin, today),
                pe=v.pe,
                revenue_growth=revenue,
                profit_growth=profit,
                period=period,
                badge=badge if period else "Not tracked",
                is_subject=is_subject,
            )
        )
    return rows, basis


MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
DATE_PATTERNS = (
    # 12th November, 2026 / 12 Nov 2026 / 12-Nov-2026
    re.compile(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/,]*({MONTHS})[a-z]*\.?[\s\-/,]*(20\d\d)\b", re.I
    ),
    # November 12, 2026
    re.compile(rf"\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I),
)


def dates_in(text: str) -> list[date]:
    found = []
    for i, pattern in enumerate(DATE_PATTERNS):
        for m in pattern.finditer(text or ""):
            day, month, year = (
                (m.group(1), m.group(2), m.group(3))
                if i == 0
                else (
                    m.group(2),
                    m.group(1),
                    m.group(3),
                )
            )
            try:
                found.append(datetime.strptime(f"{day} {month[:3]} {year}", "%d %b %Y").date())
            except ValueError:
                continue
    return found


def coming(session: Session, isin: str, symbol: str | None, today: date) -> list[Coming]:
    """What's ahead: board meetings announced, results due, ex-dates, promises falling due."""
    horizon = today + timedelta(days=COMING_DAYS)
    out: list[Coming] = []
    since = datetime.combine(today - timedelta(days=90), datetime.min.time(), IST)
    for doc in session.scalars(
        select(Document)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .where(
            DocumentCompany.isin == isin,
            Document.doc_type == "board_meeting",
            Document.published_at >= since,
        )
    ):
        text = f"{doc.title} {doc.subject or ''}"
        for d in dates_in(text):
            if today <= d <= horizon:
                what = "Board meeting" + (
                    " to approve results" if re.search(r"result", text, re.I) else ""
                )
                out.append(Coming(d, what, FILED, doc.attachment_url))
    last = session.scalar(
        select(QuarterlyResult.period_end)
        .where(QuarterlyResult.isin == isin, QuarterlyResult.months == 3)
        .order_by(QuarterlyResult.period_end.desc())
        .limit(1)
    )
    if last:
        next_end = _quarter_end_after(last)
        due = next_end + timedelta(days=60 if next_end.month == 3 else 45)
        if today <= due <= horizon and not any("results" in c.what for c in out):
            out.append(
                Coming(
                    due,
                    f"Results for the quarter to {next_end:%d %b %Y} due by",
                    FILED,
                    "SEBI LODR: 45 days after a quarter, 60 after the year",
                )
            )
    if symbol:
        for a in session.scalars(
            select(CorporateAction).where(
                CorporateAction.symbol == symbol,
                CorporateAction.ex_date >= today,
                CorporateAction.ex_date <= horizon,
            )
        ):
            out.append(Coming(a.ex_date, f"Ex-date: {a.subject}", FILED, "NSE corporate actions"))
    for p in session.scalars(
        select(Promise).where(
            Promise.isin == isin,
            Promise.status == "open",
            Promise.due_date >= today,
            Promise.due_date <= horizon,
        )
    ):
        out.append(Coming(p.due_date, f"Promise due: {p.metric} {p.target}", AI, p.statement))
    return sorted(out, key=lambda c: c.day)


def _quarter_end_after(end: date) -> date:
    month = end.month + 3
    year = end.year + (month > 12)
    month = month - 12 if month > 12 else month
    first_of_next = date(year + (month == 12), month % 12 + 1, 1)
    return first_of_next - timedelta(days=1)


def facts(session: Session, isin: str, today: date | None = None) -> Facts:
    today = today or datetime.now(IST).date()
    company = session.get(Company, isin)
    v = val.valuation(session, isin, today)
    balance, balance_end = balance_facts(session, isin, today)
    peers, basis = peer_table(session, company, today)
    docs = session.execute(
        select(Document.doc_type, Document.published_at)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .where(DocumentCompany.isin == isin)
    ).all()
    return Facts(
        isin=isin,
        symbol=company.nse_symbol or company.bse_code or isin,
        name=company.name,
        industry=company.industry,
        sector_index=v.sector_index,
        valuation=v,
        quarters=quarter_trend(session, isin),
        balance=balance,
        balance_end=balance_end,
        peers=peers,
        peer_basis=basis,
        coming=coming(session, isin, company.nse_symbol, today),
        flags=list(
            session.scalars(
                select(RedFlag)
                .where(RedFlag.isin == isin, RedFlag.dismissed_at.is_(None))
                .order_by(RedFlag.flagged_on.desc())
            )
        ),
        filings=sum(t != "news" for t, _ in docs),
        news=sum(t == "news" for t, _ in docs),
        first_filing=min((p for _, p in docs), default=None),
    )
