"""First-run setup: what the dashboard's setup screens do, as plain functions.

A new copy starts with an empty database: no list of listed companies to search, no prices,
no stocks. The setup downloads the company list, lets the user pick stocks (or start from a
few large ones), and loads their history. It is shown until it is finished or skipped, and
never to a copy that already has stocks.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_news_analyzer import settings_store as store
from stock_news_analyzer.models import Company, IndexDaily, WatchlistItem
from stock_news_analyzer.sources.announcements import IST

DONE = "setup_done"
STARTED = "setup_started"  # so adding the first stock doesn't end the setup halfway
# Fewer companies than this means the list was never downloaded (NSE alone lists ~2,500).
ENOUGH_COMPANIES = 1000
# A few large, well-covered companies to start from: name, NSE symbol, news aliases.
EXAMPLES = [
    ("RELIANCE", "Reliance, RIL"),
    ("HDFCBANK", "HDFC Bank"),
    ("INFY", "Infosys"),
    ("LT", "L&T"),
    ("ITC", ""),
]
HISTORY_CHOICES = {"1 year": 365, "2 years": 730, "Since October 2023": None}


def needs_setup(session: Session) -> bool:
    """True for a new copy (no stocks yet), or one whose setup was started and not finished
    or skipped."""
    if store.get_flag(session, DONE):
        return False
    if store.get_flag(session, STARTED):
        return True
    return not session.scalar(
        select(func.count()).select_from(WatchlistItem).where(WatchlistItem.kind == "equity")
    )


def start(session: Session) -> None:
    store.set_flag(session, STARTED, True)
    store.set_flag(session, DONE, False)


def finish(session: Session) -> None:
    store.set_flag(session, DONE, True)
    store.set_flag(session, STARTED, False)


def has_companies(session: Session) -> bool:
    return (session.scalar(select(func.count()).select_from(Company)) or 0) >= ENOUGH_COMPANIES


def download_companies(session: Session, data_dir: Path) -> list[str]:
    """The NSE and BSE lists of listed companies, so stocks can be searched. Returns warnings."""
    from stock_news_analyzer.agents.watchlist import refresh_master

    _, warnings = refresh_master(session, data_dir)
    return warnings


def add_examples(session: Session) -> list[str]:
    """Add the example stocks to the watchlist (as watchlist, not owned). Returns their names."""
    from stock_news_analyzer.ui import actions

    added = []
    for symbol, aliases in EXAMPLES:
        company = session.scalars(select(Company).where(Company.nse_symbol == symbol)).first()
        if company is not None:
            actions.add_stock(session, company.isin, owned=False, aliases=aliases)
            added.append(company.name)
    return added


def history_start(choice: str, today: date | None = None) -> date:
    from stock_news_analyzer.ui.actions import HISTORY_SINCE

    days = HISTORY_CHOICES[choice]
    today = today or datetime.now(IST).date()
    return max(today - timedelta(days=days), HISTORY_SINCE) if days else HISTORY_SINCE


def load_prices(
    session: Session,
    data_dir: Path,
    since: date,
    progress: Callable[[str], None] | None = None,
    client=None,
) -> list[str]:
    """Daily prices and index levels for every listed stock since `since` (days already stored
    are skipped). About two requests per trading day. Returns errors."""
    from stock_news_analyzer.agents.prices import PriceCollector, compute_moves
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    say = progress or (lambda _line: None)

    def each_day(done, total, day, status, eta):
        if done == 1 or done == total or done % 20 == 0:
            left = f", about {eta / 60:.0f} min left" if eta and eta >= 60 else ""
            say(f"Prices: day {done} of {total} ({day:%d %b %Y}){left}")

    collector = PriceCollector(session, client or ExchangeClient(), data_dir)
    result = collector.collect(since, skip_stored=True, progress=each_day)
    return result.errors + compute_moves(session)


def prices_from(session: Session) -> date | None:
    """The first day with index levels stored, if any."""
    return session.scalar(select(func.min(IndexDaily.trade_date)))
