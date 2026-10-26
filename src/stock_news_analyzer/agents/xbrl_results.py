"""Results from the exchange's XBRL files.

Besides the PDF, a listed company files each set of results in XBRL: every figure tagged
with what it is, in rupees. NSE lists them per company (Quarterly, Half-Yearly, Annual),
with a link to each file. Read from there, a figure needs no LLM and no check against PDF
text, so it replaces the Results Reader's reading of the same period.

NSE's results listing ends with the results filed in January 2025. Later results are filed
under SEBI's Integrated Filing (Financial), which NSE lists separately (one row per filing,
with the quarter-end date and an XBRL link); those are read the same way. In an integrated
filing the period of each context is read from its dates, so a Q4 filing gives both the
quarter and the year.
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


INTEGRATED_FINANCIALS = "Integrated Filing- Financials"


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


def _best(found: list[dict]) -> list[dict]:
    """One filing per period, the consolidated one when both are filed."""
    best: dict[tuple, dict] = {}
    for f in found:
        key = (f["end"], f["months"])
        if key not in best or f["consolidated"]:
            best[key] = f
    return sorted(best.values(), key=lambda f: f["end"])


def filings(rows: list[dict], since: date) -> list[dict]:
    """NSE's results listing (up to January 2025) as filings ending on or after `since`:
    {end, months, consolidated, xbrl, bank}."""
    found = []
    for row in rows:
        start, end = _day(row.get("fromDate")), _day(row.get("toDate"))
        link = row.get("xbrl") or ""
        if not start or not end or end < since or not link.endswith(".xml"):
            continue
        found.append(
            {
                "end": end,
                "months": _months(start, end),
                "consolidated": (row.get("consolidated") or "").lower() == "consolidated",
                "xbrl": link,
                "bank": row.get("bank") == "B",
            }
        )
    return _best(found)


def integrated(rows: list[dict], since: date) -> list[dict]:
    """NSE's integrated filings (from February 2025) as filings; their periods are read from
    the XBRL file itself (months None)."""
    found = []
    for row in rows:
        end, link = _day(row.get("qe_Date")), row.get("xbrl") or ""
        if row.get("type") != INTEGRATED_FINANCIALS or not end or end < since:
            continue
        if not link.endswith(".xml"):
            continue
        found.append(
            {
                "end": end,
                "months": None,
                "consolidated": (row.get("consolidated") or "").lower() == "consolidated",
                "xbrl": link,
                "bank": False,
            }
        )
    return _best(found)


def contexts_for(content: bytes, filing: dict) -> list[tuple[int, str]]:
    """[(months, context id)] of the periods to take from a file. The results listing's
    files use OneD for the filing's period (their context dates aren't reliable); for an
    integrated filing, every context without dimensions that ends on its quarter-end date."""
    if filing["months"]:
        return [(filing["months"], CONTEXT)]
    chosen: dict[int, str] = {}
    for cid, (start, end, dims) in xbrl.periods(content).items():
        if dims or not start or not end:
            continue
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            continue
        if e != filing["end"]:
            continue
        months = _months(s, e)
        if months not in chosen or cid.startswith("One"):
            chosen[months] = cid
    return sorted(chosen.items())


def figures(content: bytes, bank: bool, context: str = CONTEXT) -> dict[str, tuple[Decimal, str]]:
    """{field: (value, as written)} for one context. Money in Rs crore."""
    facts = {}
    for tag, ctx, value in xbrl.facts(content):
        if ctx == context:
            facts.setdefault(tag, value)
    bank = bank or "RevenueOnInvestments" in facts  # a tag only banks' results carry
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


def _store(session, company, filing: dict, months: int, found: dict) -> bool:
    """Write one period; True if it replaced a Results Reader figure off by more than 1%."""
    end = filing["end"]
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
    stored.basis = "consolidated" if filing["consolidated"] else "standalone"
    stored.unit, stored.model, stored.document_id = "rupees", XBRL, None
    stored.as_written = {
        f: {"as_written": raw, "found": True, "source": filing["xbrl"]}
        for f, (_, raw) in found.items()
    }
    new = stored.revenue_cr
    return bool(old and new and abs(old - new) > abs(new) * Decimal("0.01"))


def _done(session, isin: str, filing: dict) -> bool:
    """The filing's period (its quarter or half year, when not known yet) is from XBRL."""
    months = (filing["months"],) if filing["months"] else (3, 6)
    return bool(
        session.scalar(
            select(QuarterlyResult.id).where(
                QuarterlyResult.isin == isin,
                QuarterlyResult.period_end == filing["end"],
                QuarterlyResult.months.in_(months),
                QuarterlyResult.model == XBRL,
            )
        )
    )


def import_results(
    session: Session,
    client,
    symbol: str | None = None,
    since: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> XbrlResult:
    """Read the XBRL file of each results filing NSE lists for the watchlist (the results
    listing and the integrated filings), and store its figures. Periods already taken from
    XBRL are skipped."""
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
        todo = filings(rows, since)
        try:
            todo += integrated(client.nse_integrated_results(company.nse_symbol, index), since)
        except ExchangeError as exc:
            result.errors.append(f"{company.nse_symbol} integrated filings: {exc}")
        stored = 0
        for filing in todo:
            if _done(session, company.isin, filing):
                result.skipped += 1
                continue
            try:
                _, content, _ = client.download("nse", [filing["xbrl"]])
                periods = contexts_for(content, filing)
                found = [(m, figures(content, filing["bank"], c)) for m, c in periods]
            except (ExchangeError, ValueError, SyntaxError) as exc:
                result.errors.append(f"{company.nse_symbol} {filing['end']}: {exc}")
                continue
            if not found:
                result.errors.append(
                    f"{company.nse_symbol} {filing['end']}: no context in {filing['xbrl']} "
                    "covers that period; run `sna results probe` and send its output"
                )
            for months, figs in found:
                result.corrected += _store(session, company, filing, months, figs)
                result.periods += 1
                stored += 1
        session.commit()
        if stored:
            say(f"{company.nse_symbol}: {stored} periods from XBRL")
    return result
