"""Deals Collector: NSE bulk and block deals, for every listed stock.

Large trades by funds and promoters often explain a small company's unusual day better than
any news. All deals are kept (not only the watchlist's), linked to a company by NSE symbol.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.models import Company, Deal
from stock_news_analyzer.sources.deals import KINDS, DealsFormatError, parse_deals
from stock_news_analyzer.sources.exchange_http import ExchangeError

log = logging.getLogger(__name__)

CHUNK_DAYS = 30  # one request covers this many days
OVERLAP_DAYS = 3  # re-read the last few days: NSE sometimes adds deals late
# NSE's JSON answers stopped at this many rows; a response of exactly this size is suspect.
SUSPECT_ROWS = 70


@dataclass
class DealsResult:
    new: int = 0
    seen: int = 0
    errors: list[str] = field(default_factory=list)


def store(session: Session, deals) -> int:
    """Insert deals (once each). Returns how many were new."""
    isins = dict(
        session.execute(
            select(Company.nse_symbol, Company.isin).where(
                Company.nse_symbol.in_({d.symbol for d in deals})
            )
        ).all()
    )
    new = 0
    for d in deals:
        inserted = session.scalar(
            insert(Deal)
            .values(
                kind=d.kind,
                trade_date=d.trade_date,
                symbol=d.symbol,
                isin=isins.get(d.symbol),
                security_name=d.security_name,
                client=d.client,
                side=d.side,
                quantity=d.quantity,
                price=d.price,
                remarks=d.remarks,
            )
            .on_conflict_do_nothing(constraint="deals_key")
            .returning(Deal.id)
        )
        new += inserted is not None
    session.commit()
    return new


def resume_date(session: Session, default_days: int = 7) -> date:
    latest = session.scalar(select(func.max(Deal.trade_date)))
    if latest is None:
        return date.today() - timedelta(days=default_days)
    return latest - timedelta(days=OVERLAP_DAYS)


def collect(
    session: Session,
    client,
    start: date,
    end: date | None = None,
    kinds: tuple[str, ...] = KINDS,
    progress: Callable[[str], None] | None = None,
) -> DealsResult:
    """Fetch deals from `start` to `end` (default today), a month per request."""
    end = end or date.today()
    say = progress or (lambda _line: None)
    result = DealsResult()
    lo = start
    while lo <= end:
        hi = min(end, lo + timedelta(days=CHUNK_DAYS - 1))
        for kind in kinds:
            label = f"{kind} deals {lo:%d %b %Y}-{hi:%d %b %Y}"
            try:
                deals = parse_deals(client.nse_deals(kind, lo, hi), kind)
            except (ExchangeError, DealsFormatError, ValueError) as exc:
                result.errors.append(f"{label}: {exc}")
                say(f"{label}: FAILED {exc}")
                continue
            new = store(session, deals)
            result.seen += len(deals)
            result.new += new
            if len(deals) == SUSPECT_ROWS:
                result.errors.append(f"{label}: exactly {SUSPECT_ROWS} rows, possibly cut short")
            say(
                f"{label}: {len(deals)} read, {new} new"
                + (
                    f" (exactly {SUSPECT_ROWS} rows: NSE may have cut it short)"
                    if len(deals) == SUSPECT_ROWS
                    else ""
                )
            )
        lo = hi + timedelta(days=1)
    return result


def watchlist_deals(session: Session, isin: str, start: date, end: date) -> list[tuple]:
    """(deal, share of that day's traded volume or None) for one stock, oldest first."""
    from stock_news_analyzer.models import PriceDaily

    rows = session.execute(
        select(Deal, PriceDaily.volume)
        .outerjoin(
            PriceDaily,
            (PriceDaily.isin == Deal.isin) & (PriceDaily.trade_date == Deal.trade_date),
        )
        .where(Deal.isin == isin, Deal.trade_date >= start, Deal.trade_date <= end)
        .order_by(Deal.trade_date, Deal.kind, Deal.quantity.desc())
    ).all()
    return [(d, (d.quantity / volume) if volume else None) for d, volume in rows]
