"""What the dashboard's Manage stocks page changes: add, edit and remove watchlist stocks, and
load a new stock's history. Plain functions, so they are tested without a browser."""

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import Company, IndexDaily, WatchlistItem
from stock_news_analyzer.sources.announcements import IST

HISTORY_SINCE = date(2023, 10, 1)


def search(session: Session, query: str, limit: int = 8) -> list[dict]:
    """Listed companies matching a name, NSE symbol, BSE code or ISIN, best first."""
    if not query.strip():
        return []
    tracked = set(
        session.scalars(select(WatchlistItem.isin).where(WatchlistItem.isin.is_not(None)))
    )
    return [
        {
            "isin": m.company.isin,
            "symbol": m.company.nse_symbol,
            "bse_code": m.company.bse_code,
            "name": m.company.name,
            "tracked": m.company.isin in tracked,
        }
        for m in wl.find_matches(session, query, limit=limit)
    ]


def index_names(session: Session) -> list[str]:
    """NSE index names with stored closes, for the sector benchmark choice."""
    return list(session.scalars(select(IndexDaily.index_name).distinct().order_by("index_name")))


def _aliases(text: str) -> list[str]:
    return [a.strip() for a in text.split(",") if a.strip()]


def add_stock(
    session: Session, isin: str, owned: bool, aliases: str = "", sector_index: str | None = None
) -> Company:
    """Add (or update) a stock. `aliases` is comma-separated, e.g. "L&T, Larsen"."""
    company = session.get(Company, isin)
    if company is None:
        raise ValueError(f"unknown ISIN {isin}")
    wl.add_equity(
        session, company, owned=owned, aliases=_aliases(aliases), sector_index=sector_index or ""
    )
    return company


def tracked_stocks(session: Session) -> list[dict]:
    """Watchlist stocks (not bullion) as editable rows."""
    rows = session.execute(
        select(WatchlistItem, Company)
        .join(Company, Company.isin == WatchlistItem.isin)
        .order_by(WatchlistItem.owned.desc(), Company.name)
    ).all()
    return [
        {
            "isin": c.isin,
            "symbol": c.nse_symbol or c.bse_code or "",
            "name": c.name,
            "owned": bool(i.owned),
            "sector_index": i.sector_index or "",
            "aliases": ", ".join(i.aliases or []),
            "remove": False,
        }
        for i, c in rows
    ]


def save_changes(session: Session, rows: list[dict]) -> tuple[int, int]:
    """Apply edited rows (owned, sector index, aliases, remove). Returns (updated, removed)."""
    updated = removed = 0
    for row in rows:
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.isin == row["isin"]))
        if item is None:
            continue
        if row.get("remove"):
            session.delete(item)
            removed += 1
            continue
        aliases = _aliases(row.get("aliases") or "")
        sector = (row.get("sector_index") or "").strip() or None
        if (bool(row["owned"]), sector, aliases) != (
            bool(item.owned),
            item.sector_index,
            list(item.aliases or []),
        ):
            item.owned, item.sector_index, item.aliases = bool(row["owned"]), sector, aliases
            updated += 1
    session.commit()
    return updated, removed


def load_history(
    session: Session,
    isin: str,
    data_dir: Path,
    since: date = HISTORY_SINCE,
    progress: Callable[[str], None] | None = None,
    exchange=None,
    news_client=None,
    feeds_file: Path | None = None,
) -> list[str]:
    """Filings, news, corporate actions, daily moves and labels for one stock since `since`.

    Prices are already stored for every listed stock, so only this stock's moves are new.
    Returns error messages (empty when everything worked). Safe to run again.
    """
    from stock_news_analyzer.agents.filings import FilingsCollector, watchlist_companies
    from stock_news_analyzer.agents.news import NewsCollector
    from stock_news_analyzer.agents.orchestrator import FEEDS_FILE
    from stock_news_analyzer.agents.prices import (
        compute_moves,
        refresh_corporate_actions,
        update_labels,
    )
    from stock_news_analyzer.sources.exchange_http import ExchangeClient
    from stock_news_analyzer.sources.news import NewsClient, load_feed_config

    say = progress or (lambda _line: None)
    companies = [c for c in watchlist_companies(session) if c.isin == isin]
    if not companies:
        return [f"{isin} is not on the watchlist"]
    company = companies[0]
    exchange = exchange or ExchangeClient()
    today = datetime.now(IST).date()

    say("Filings (BSE and NSE)...")
    filings = FilingsCollector(session, exchange, data_dir, pdf_policy="important").collect(
        companies, start=since, progress=say
    )
    errors = list(filings.errors)

    say("News (Google News, a month per search)...")
    config = load_feed_config(feeds_file or FEEDS_FILE)
    news = NewsCollector(session, news_client or NewsClient(), config).backfill(
        since, today, symbol=company.nse_symbol or company.isin, progress=say
    )
    errors += [f"{r.key}: {r.error}" for r in news.errors]

    say("Bonus issues, splits and dividends...")
    errors += refresh_corporate_actions(session, exchange, since, today, isins={isin})
    say("Daily moves and labels...")
    errors += compute_moves(session)
    written, complete = update_labels(session)
    say(
        f"Done: {filings.new} filings, {news.new} news articles, {written} labels "
        f"({complete} complete)."
    )
    return errors
