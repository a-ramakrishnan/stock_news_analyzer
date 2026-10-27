"""Shareholding patterns (part of Market Signals, agent 4): who owns each watchlist company,
quarter by quarter, and how that changes. Plain code, no LLM.

NSE lists each company's quarterly shareholding-pattern filings with a link to the XBRL file
(sources/shareholding.py reads it). From it: the promoters', foreign and domestic
institutions', mutual funds', insurers' and retail investors' stakes, the number of
shareholders, and the share of the promoters' holding that is pledged or locked in.

Changes feed the Red-flag Monitor: promoters selling (their share count falls) or pledging
more of their holding. A promoter stake that falls only because new shares were issued is
dilution, not selling, and raises nothing.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.models import Company, RedFlag, Shareholding, WatchlistItem
from stock_news_analyzer.sources import shareholding as shp
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.exchange_http import SME_SERIES, ExchangeError

log = logging.getLogger(__name__)

HOLDING_DAYS = 3 * 365 + 100  # quarters read on the first run: about three years
FLAG_DAYS = 400  # quarters ending this recently can raise red flags
MOVE_POINTS = Decimal(1)  # a change of this many percentage points is worth showing
# Red flags. Promoters selling: percentage points of the company, by severity.
SOLD_POINTS = {"high": Decimal(5), "medium": Decimal(2), "low": Decimal(1)}
# Pledged share of the promoters' holding, after a rise of PLEDGE_RISE points or more.
PLEDGED = {"high": Decimal(50), "medium": Decimal(20), "low": Decimal(0)}
PLEDGE_RISE = Decimal(2)
COLUMNS = ("promoter_pct", "fii_pct", "dii_pct", "mf_pct", "retail_pct")
LABELS = {
    "promoter_pct": "promoters",
    "fii_pct": "foreign institutions",
    "dii_pct": "domestic institutions",
    "mf_pct": "mutual funds",
    "retail_pct": "retail",
}


@dataclass
class HoldingsResult:
    filings: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _day(text: str | None) -> date | None:
    """'30-SEP-2026' or '17-OCT-2026 10:11:10' -> the date."""
    if not text:
        return None
    try:
        return datetime.strptime(text[:11], "%d-%b-%Y").date()
    except ValueError:
        return None


def filings(rows: list[dict], since: date) -> list[dict]:
    """One filing per quarter from NSE's listing (the latest, when a filing was revised),
    for quarters ending on or after `since`, oldest first."""
    best: dict[date, dict] = {}
    for row in rows:
        end = _day(row.get("date"))
        link = row.get("xbrl") or ""
        if end is None or end < since or not link.endswith(".xml"):
            continue
        try:
            filed = datetime.strptime(row.get("broadcastDate") or "", "%d-%b-%Y %H:%M:%S")
        except ValueError:
            filed = datetime.combine(_day(row.get("submissionDate")) or end, datetime.min.time())
        filing = {
            "end": end,
            "filed": filed.replace(tzinfo=IST),
            "record_id": str(row.get("recordId") or link),
            "xbrl": link,
            "promoter_pct": row.get("pr_and_prgrp"),
        }
        if end not in best or filing["filed"] > best[end]["filed"]:
            best[end] = filing
    return [best[k] for k in sorted(best)]


def store(session: Session, isin: str, filing: dict, pattern: shp.Pattern) -> Shareholding:
    row = session.get(Shareholding, (isin, filing["end"])) or Shareholding(
        isin=isin, quarter_end=filing["end"]
    )
    promoter = pattern.pct(shp.PROMOTER)
    if promoter is None and filing.get("promoter_pct") not in (None, ""):
        promoter = Decimal(str(filing["promoter_pct"]))  # no promoters: NSE's listing says 0
    row.filed_at = filing["filed"]
    row.record_id = filing["record_id"]
    row.xbrl_url = filing["xbrl"]
    row.total_shares = pattern.shares(shp.TOTAL)
    row.shareholders = pattern.categories.get(shp.TOTAL, {}).get("holders")
    row.promoter_pct = promoter
    row.promoter_shares = pattern.shares(shp.PROMOTER) or (0 if promoter == 0 else None)
    row.public_pct = pattern.pct(shp.PUBLIC)
    for column, name in shp.COLUMNS.items():
        setattr(row, column, pattern.pct(name) or Decimal(0))
    row.pledged_pct = pattern.pledged_pct or (Decimal(0) if row.promoter_shares else None)
    row.locked_pct = pattern.locked_pct
    row.categories = pattern.categories
    session.add(row)
    return row


def import_holdings(
    session: Session,
    client,
    symbol: str | None = None,
    since: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> HoldingsResult:
    """Read the shareholding patterns NSE lists for each watchlist company, from `since`
    (default: about three years), skipping filings already stored."""
    say = progress or (lambda _line: None)
    since = since or datetime.now(IST).date() - timedelta(days=HOLDING_DAYS)
    result = HoldingsResult()
    query = select(Company).join(WatchlistItem, WatchlistItem.isin == Company.isin)
    if symbol:
        query = query.where((Company.nse_symbol == symbol.upper()) | (Company.isin == symbol))
    for company in session.scalars(query.order_by(Company.nse_symbol)):
        if not company.nse_symbol:
            continue
        index = "sme" if company.nse_series in SME_SERIES else "equities"
        try:
            rows = client.nse_shareholdings(company.nse_symbol, index)
        except ExchangeError as exc:
            result.errors.append(f"{company.nse_symbol}: {exc}")
            continue
        stored = dict(
            session.execute(
                select(Shareholding.quarter_end, Shareholding.record_id).where(
                    Shareholding.isin == company.isin
                )
            ).all()
        )
        new = 0
        for filing in filings(rows, since):
            if stored.get(filing["end"]) == filing["record_id"]:
                result.skipped += 1
                continue
            try:
                _, content, _ = client.download("nse", [filing["xbrl"]])
                pattern = shp.parse(content)
            except (ExchangeError, ValueError, SyntaxError) as exc:
                result.errors.append(f"{company.nse_symbol} {filing['end']}: {exc}")
                continue
            if not pattern.categories:
                result.errors.append(
                    f"{company.nse_symbol} {filing['end']}: no categories in {filing['xbrl']}; "
                    "run `sna holdings probe` and send its output"
                )
                continue
            try:
                with session.begin_nested():  # a bad file loses itself, not the run
                    store(session, company.isin, filing, pattern)
            except Exception as exc:
                result.errors.append(f"{company.nse_symbol} {filing['end']}: {exc}")
                continue
            new += 1
        session.commit()
        result.filings += new
        if new:
            say(f"{company.nse_symbol}: {new} quarters")
    return result


def history(session: Session, isin: str, limit: int = 12) -> list[Shareholding]:
    """A company's quarters, newest first."""
    return list(
        session.scalars(
            select(Shareholding)
            .where(Shareholding.isin == isin)
            .order_by(Shareholding.quarter_end.desc())
            .limit(limit)
        )
    )


def change(cur: Shareholding, prev: Shareholding | None) -> dict[str, Decimal | None]:
    """Percentage-point change of each column against the quarter before."""
    out = {}
    for c in COLUMNS:
        a, b = getattr(cur, c), getattr(prev, c) if prev else None
        out[c] = a - b if a is not None and b is not None else None
    return out


def moves(
    session: Session, filed_since: datetime | None = None, points: Decimal = MOVE_POINTS
) -> list[dict]:
    """Each watchlist company's latest quarter (or each filed since `filed_since`) with a
    change of `points` or more in any stake, against the quarter before."""
    out = []
    rows = session.execute(
        select(Shareholding, Company.nse_symbol)
        .join(Company, Company.isin == Shareholding.isin)
        .join(WatchlistItem, WatchlistItem.isin == Shareholding.isin)
        .order_by(Company.nse_symbol, Shareholding.quarter_end)
    ).all()
    by_company: dict[str, list] = {}
    for row, symbol in rows:
        by_company.setdefault(symbol, []).append(row)
    for symbol, quarters in by_company.items():
        pairs = list(zip([None, *quarters[:-1]], quarters, strict=True))
        if filed_since is None:
            pairs = pairs[-1:]
        else:
            pairs = [(p, c) for p, c in pairs if c.filed_at and c.filed_at >= filed_since]
        for prev, cur in pairs:
            if prev is None:
                continue
            delta = change(cur, prev)
            big = {c: d for c, d in delta.items() if d is not None and abs(d) >= points}
            pledge = (cur.pledged_pct or 0) - (prev.pledged_pct or 0)
            if big or abs(pledge) >= points:
                out.append(
                    {"symbol": symbol, "row": cur, "prev": prev, "moves": big, "pledge": pledge}
                )
    return out


def describe(move: dict) -> str:
    """'LT Sep 2026: mutual funds 19.4% (+1.2), foreign institutions 18.5% (-1.0)'."""
    cur = move["row"]
    parts = [f"{LABELS[c]} {getattr(cur, c):.1f}% ({d:+.1f})" for c, d in move["moves"].items()]
    if abs(move["pledge"]) >= MOVE_POINTS:
        parts.append(f"pledged {cur.pledged_pct:.1f}% of promoter shares ({move['pledge']:+.1f})")
    return f"{move['symbol']} {cur.quarter_end:%b %Y}: " + ", ".join(parts)


def _severity(value: Decimal, thresholds: dict[str, Decimal]) -> str | None:
    return next((s for s, t in thresholds.items() if value >= t), None)


def flags(session: Session, today: date | None = None) -> list[RedFlag]:
    """Red flags from the shareholding patterns of the last FLAG_DAYS: promoters selling
    (fewer shares than the quarter before) or pledging more of their holding."""
    today = today or datetime.now(IST).date()
    out = []
    rows = session.execute(
        select(Shareholding, Company.nse_symbol)
        .join(Company, Company.isin == Shareholding.isin)
        .join(WatchlistItem, WatchlistItem.isin == Shareholding.isin)
        .order_by(Shareholding.isin, Shareholding.quarter_end)
    ).all()
    prev: Shareholding | None = None
    for cur, symbol in rows:
        if prev is None or prev.isin != cur.isin:
            prev = cur
            continue
        recent = cur.quarter_end >= today - timedelta(days=FLAG_DAYS)
        on = cur.filed_at.astimezone(IST).date() if cur.filed_at else cur.quarter_end
        quarter = f"{cur.quarter_end:%b %Y}"
        if recent and cur.promoter_shares is not None and prev.promoter_shares:
            fall = (prev.promoter_pct or 0) - (cur.promoter_pct or 0)
            severity = _severity(fall, SOLD_POINTS)
            if cur.promoter_shares < prev.promoter_shares and severity:
                out.append(
                    RedFlag(
                        isin=cur.isin,
                        kind="promoter_selling",
                        severity=severity,
                        title=(
                            f"{symbol}: promoters' stake down to {cur.promoter_pct:.2f}% from "
                            f"{prev.promoter_pct:.2f}% ({quarter})"
                        ),
                        detail=(
                            f"promoter shares {prev.promoter_shares:,} -> "
                            f"{cur.promoter_shares:,} in the shareholding pattern"
                        ),
                        flagged_on=on,
                        ref=f"holdings:selling:{cur.quarter_end}",
                    )
                )
        rise = (cur.pledged_pct or 0) - (prev.pledged_pct or 0)
        if recent and cur.pledged_pct and rise >= PLEDGE_RISE:
            out.append(
                RedFlag(
                    isin=cur.isin,
                    kind="pledge_rising",
                    severity=_severity(cur.pledged_pct, PLEDGED),
                    title=(
                        f"{symbol}: {cur.pledged_pct:.1f}% of promoter shares pledged or "
                        f"encumbered, up from {prev.pledged_pct or 0:.1f}% ({quarter})"
                    ),
                    detail="from the shareholding pattern",
                    flagged_on=on,
                    ref=f"holdings:pledge:{cur.quarter_end}",
                )
            )
        prev = cur
    return out
