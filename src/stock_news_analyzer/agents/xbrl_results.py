"""Results from the exchange's XBRL files.

Besides the PDF, a listed company files each set of results in XBRL: every figure tagged
with what it is, in rupees. NSE lists them per company (Quarterly, Half-Yearly, Annual),
with a link to each file. Read from there, a figure needs no LLM and no check against PDF
text, so it replaces the Results Reader's reading of the same period.

NSE's listing ends with the results filed in January 2025: later results come under SEBI's
Integrated Filing (Financial) and are listed elsewhere. For those the Results Reader (an
LLM reading the PDF) still does the work.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.results import FIELDS, RESULT_DAYS, XBRL, period_label
from stock_news_analyzer.models import Company, QuarterlyResult, WatchlistItem
from stock_news_analyzer.sources import xbrl
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.exchange_http import SME_SERIES, ExchangeError

log = logging.getLogger(__name__)

PERIODS = ("Quarterly", "Half-Yearly", "Annual")
RUPEES_PER_CRORE = Decimal(10_000_000)
# The period the filing is for. "Four" contexts are the year to date; other contexts are
# segments and expense lines.
CONTEXT = "OneD"
# Tags for each figure, first match wins: Ind AS companies, older (non-Ind AS) SME
# companies, banks.
TAGS = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "finance_costs": ("FinanceCosts",),
    "depreciation": (
        "DepreciationDepletionAndAmortisationExpense",
        "DepreciationAndAmortisationExpense",
    ),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "pat": (
        "ProfitOrLossAttributableToOwnersOfParent",
        "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
        "ProfitLossForPeriod",
        "ProfitLossForThePeriod",
    ),
    "eps": (
        "BasicEarningsPerShareAfterExtraordinaryItems",
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShare",
    ),
}
# A bank's revenue is its total income (interest earned plus other income), as the Results
# Reader records it.
BANK_REVENUE = ("Income",)


@dataclass
class XbrlResult:
    periods: int = 0  # stored or replaced
    corrected: int = 0  # replaced a Results Reader figure that differed by more than 1%
    skipped: int = 0  # already from XBRL
    errors: list[str] = field(default_factory=list)


def _day(text: str | None) -> date | None:
    try:
        return datetime.strptime((text or "").strip().title(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _months(start: date, end: date) -> int:
    return round(((end - start).days + 1) / 30.44)


def filings(rows: list[dict], since: date) -> list[dict]:
    """One listing row per period (consolidated when both are filed), with an XBRL file,
    ending on or after `since`."""
    best: dict[tuple, dict] = {}
    for row in rows:
        start, end = _day(row.get("fromDate")), _day(row.get("toDate"))
        link = row.get("xbrl") or ""
        if not start or not end or end < since or not link.endswith(".xml"):
            continue
        key = (start, end)
        consolidated = (row.get("consolidated") or "").lower() == "consolidated"
        if key not in best or consolidated:
            best[key] = {**row, "_start": start, "_end": end, "_consolidated": consolidated}
    return sorted(best.values(), key=lambda r: r["_end"])


def figures(content: bytes, bank: bool) -> dict[str, tuple[Decimal, str]]:
    """{field: (value, as written)} for the filing's own period. Money in Rs crore."""
    facts = {}
    for tag, context, value in xbrl.facts(content):
        if context == CONTEXT:
            facts.setdefault(tag, value)
    out = {}
    for f, tags in TAGS.items():
        if f == "revenue" and bank:
            tags = BANK_REVENUE + tags
        for tag in tags:
            raw = facts.get(tag)
            if raw is None:
                continue
            try:
                value = Decimal(raw)
            except ArithmeticError:
                continue
            if f == "pat" and tag.endswith("OwnersOfParent") and value == 0:
                continue  # a standalone filing leaves the attributable line at zero
            out[f] = (value if f == "eps" else value / RUPEES_PER_CRORE, raw)
            break
    return out


def _store(session, company, row, found: dict) -> bool:
    """Write the period; True if it replaced a Results Reader figure off by more than 1%."""
    end, months = row["_end"], _months(row["_start"], row["_end"])
    label = period_label(end, months)
    if not label or "revenue" not in found and "pat" not in found:
        return False
    stored = session.scalars(
        select(QuarterlyResult).where(
            QuarterlyResult.isin == company.isin,
            QuarterlyResult.period_end == end,
            QuarterlyResult.months == months,
        )
    ).first()
    old = stored.revenue_cr if stored else None
    stored = stored or QuarterlyResult(isin=company.isin, period_end=end, months=months)
    session.add(stored)
    for f in FIELDS:
        value = found.get(f, (None, None))[0]
        rounded = None if value is None else round(value, 2)
        setattr(stored, "eps" if f == "eps" else f"{f}_cr", rounded)
    stored.period, stored.primary = label, True
    stored.basis = "consolidated" if row["_consolidated"] else "standalone"
    stored.unit, stored.model, stored.document_id = "rupees", XBRL, None
    stored.as_written = {
        f: {"as_written": raw, "found": True, "source": row.get("xbrl")}
        for f, (_, raw) in found.items()
    }
    new = stored.revenue_cr
    return bool(old and new and abs(old - new) > abs(new) * Decimal("0.01"))


def import_results(
    session: Session,
    client,
    symbol: str | None = None,
    since: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> XbrlResult:
    """Read the XBRL file of each results filing NSE lists for the watchlist, and store its
    figures. Periods already taken from XBRL are skipped."""
    say = progress or (lambda _line: None)
    since = since or datetime.now(IST).date() - timedelta(days=RESULT_DAYS)
    result = XbrlResult()
    query = select(Company).join(WatchlistItem, WatchlistItem.isin == Company.isin)
    if symbol:
        query = query.where((Company.nse_symbol == symbol.upper()) | (Company.isin == symbol))
    for company in session.scalars(query.order_by(Company.nse_symbol)):
        if not company.nse_symbol:
            continue
        index = "sme" if company.nse_series in SME_SERIES else "equities"
        rows = []
        for period in PERIODS:
            try:
                rows += client.nse_financial_results(company.nse_symbol, period, index)
            except ExchangeError as exc:
                result.errors.append(f"{company.nse_symbol} {period}: {exc}")
        stored = 0
        for row in filings(rows, since):
            months = _months(row["_start"], row["_end"])
            done = session.scalar(
                select(QuarterlyResult.id).where(
                    QuarterlyResult.isin == company.isin,
                    QuarterlyResult.period_end == row["_end"],
                    QuarterlyResult.months == months,
                    QuarterlyResult.model == XBRL,
                )
            )
            if done:
                result.skipped += 1
                continue
            try:
                _, content, _ = client.download("nse", [row["xbrl"]])
                found = figures(content, bank=row.get("bank") == "B")
            except (ExchangeError, ValueError, SyntaxError) as exc:
                result.errors.append(f"{company.nse_symbol} {row['_end']}: {exc}")
                continue
            result.corrected += _store(session, company, row, found)
            result.periods += 1
            stored += 1
        session.commit()
        if stored:
            say(f"{company.nse_symbol}: {stored} periods from XBRL")
    return result
