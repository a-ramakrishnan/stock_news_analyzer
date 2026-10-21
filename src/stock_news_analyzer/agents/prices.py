"""Price & Label (agent 5).

Downloads NSE's daily price and index files, measures each watchlist stock's daily return
against the Nifty 50 and its sector index, flags unusual days, and labels every stored filing
and article with what the stock did afterwards.
"""

import gzip
import logging
import statistics
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.models import (
    Company,
    Document,
    DocumentCompany,
    EventLabel,
    IndexDaily,
    PriceDaily,
    StockMove,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.exchange_http import ExchangeError
from stock_news_analyzer.sources.prices import (
    FULL_BHAVCOPY_URL,
    INDEX_CLOSE_URL,
    parse_full_bhavcopy,
    parse_index_close,
)

log = logging.getLogger(__name__)

NIFTY = "Nifty 50"
# Series that represent a company's ordinary shares; the first one present wins.
MAIN_SERIES = ("EQ", "BE", "BZ", "SM", "ST")
MARKET_CLOSE = time(15, 30)
WINDOW = 60  # trading days used to judge what a normal move is
MIN_HISTORY = 20  # no unusual-move flag until this many days of history exist
THRESHOLD = 2.0  # |excess return| above this many standard deviations is unusual
HORIZONS = (1, 5, 20)


class Client(Protocol):
    def nse_file(self, url: str) -> bytes | None: ...


@dataclass
class PriceResult:
    days: int = 0
    holidays: int = 0
    rows: int = 0
    errors: list[str] = field(default_factory=list)


def weekdays(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


# --- collecting --------------------------------------------------------------


class PriceCollector:
    def __init__(self, session: Session, client: Client, data_dir: Path):
        self.session = session
        self.client = client
        self.data_dir = data_dir

    def resume_date(self, default_days: int = 7) -> date:
        latest = self.session.scalar(select(func.max(IndexDaily.trade_date)))
        today = datetime.now(IST).date()
        return latest + timedelta(days=1) if latest else today - timedelta(days=default_days)

    def collect(self, start: date, end: date | None = None) -> PriceResult:
        end = end or datetime.now(IST).date()
        result = PriceResult()
        isins = dict(
            self.session.execute(
                select(Company.nse_symbol, Company.isin).where(Company.nse_symbol.is_not(None))
            ).all()
        )
        for day in weekdays(start, end):
            try:
                self._collect_day(day, isins, result)
            except ExchangeError as exc:
                result.errors.append(f"{day}: {exc}")
                log.error("%s: %s", day, exc)
        return result

    def _collect_day(self, day: date, isins: dict[str, str], result: PriceResult) -> None:
        index_raw = self.client.nse_file(INDEX_CLOSE_URL.format(d=day))
        if index_raw is None:  # no index file: a holiday, or not published yet today
            result.holidays += 1
            return
        full_raw = self.client.nse_file(FULL_BHAVCOPY_URL.format(d=day))
        if full_raw is None:
            result.errors.append(f"{day}: index file present but no price file")
            return
        indices = [r for r in parse_index_close(index_raw.decode("utf-8", "replace"))]
        prices = parse_full_bhavcopy(full_raw.decode("utf-8", "replace"))
        if not prices or prices[0].trade_date != day:
            # NSE answers a holiday's URL with the previous day's file.
            found = prices[0].trade_date if prices else "nothing"
            log.info("%s: price file holds %s; skipping", day, found)
            result.holidays += 1
            return

        self._keep_raw(day, "sec_bhavdata_full", full_raw)
        self._keep_raw(day, "ind_close_all", index_raw)

        rows = []
        for p in prices:
            values = {k: getattr(p, k) for k in p.__dataclass_fields__}
            values["isin"] = isins.get(p.symbol) if p.series in MAIN_SERIES else None
            rows.append(values)
        stmt = insert(PriceDaily).values(rows)
        self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=["symbol", "series", "trade_date"],
                set_={c: stmt.excluded[c] for c in rows[0] if c not in ("symbol", "series")},
            )
        )
        index_rows = [{k: getattr(i, k) for k in i.__dataclass_fields__} for i in indices]
        if index_rows:
            stmt = insert(IndexDaily).values(index_rows)
            self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["index_name", "trade_date"],
                    set_={c: stmt.excluded[c] for c in index_rows[0] if c != "index_name"},
                )
            )
        self.session.commit()
        result.days += 1
        result.rows += len(rows)

    def _keep_raw(self, day: date, name: str, content: bytes) -> None:
        path = self.data_dir / "prices" / f"{day:%Y}" / f"{name}_{day:%Y%m%d}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(content))


# --- returns and unusual moves -----------------------------------------------


def index_returns(session: Session, index_name: str) -> dict[date, float]:
    closes = session.execute(
        select(IndexDaily.trade_date, IndexDaily.close)
        .where(IndexDaily.index_name == index_name, IndexDaily.close.is_not(None))
        .order_by(IndexDaily.trade_date)
    ).all()
    return {
        d: float(c) / float(prev) - 1
        for (_, prev), (d, c) in zip(closes, closes[1:], strict=False)
        if prev
    }


def stock_returns(session: Session, isin: str) -> dict[date, float]:
    """Daily returns from NSE's previous close, which NSE adjusts on split and bonus ex-dates."""
    rows = session.execute(
        select(PriceDaily.trade_date, PriceDaily.series, PriceDaily.prev_close, PriceDaily.close)
        .where(PriceDaily.isin == isin, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.trade_date)
    ).all()
    best: dict[date, tuple[int, float]] = {}
    for d, series, prev, close in rows:
        if not prev:
            continue
        rank = MAIN_SERIES.index(series) if series in MAIN_SERIES else len(MAIN_SERIES)
        if d not in best or rank < best[d][0]:
            best[d] = (rank, float(close) / float(prev) - 1)
    return {d: r for d, (_, r) in sorted(best.items())}


def watchlist_benchmarks(session: Session) -> list[tuple[Company, str | None]]:
    return [
        (c, s)
        for c, s in session.execute(
            select(Company, WatchlistItem.sector_index).join(
                WatchlistItem, WatchlistItem.isin == Company.isin
            )
        ).all()
    ]


def compute_moves(session: Session) -> list[str]:
    """Recompute daily moves for every watchlist stock. Returns warnings (e.g. unknown index)."""
    warnings = []
    known = set(session.scalars(select(IndexDaily.index_name).distinct()))
    nifty = index_returns(session, NIFTY)
    for company, sector in watchlist_benchmarks(session):
        if sector and sector not in known:
            warnings.append(f"{company.nse_symbol}: sector index '{sector}' not in NSE's file")
            sector = None
        sector_r = index_returns(session, sector) if sector else {}
        history: list[float] = []
        rows = []
        for d, r in stock_returns(session, company.isin).items():
            excess = r - nifty[d] if d in nifty else None
            z = None
            if excess is not None and len(history) >= MIN_HISTORY:
                sd = statistics.pstdev(history[-WINDOW:])
                z = excess / sd if sd else None
            rows.append(
                {
                    "isin": company.isin,
                    "trade_date": d,
                    "stock_return": r,
                    "nifty_return": nifty.get(d),
                    "sector_index": sector,
                    "sector_return": sector_r.get(d),
                    "excess_return": excess,
                    "sector_excess_return": r - sector_r[d] if d in sector_r else None,
                    "zscore": z,
                    "unusual": z is not None and abs(z) >= THRESHOLD,
                }
            )
            if excess is not None:
                history.append(excess)
        if rows:
            stmt = insert(StockMove).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["isin", "trade_date"],
                    set_={c: stmt.excluded[c] for c in rows[0] if c not in ("isin", "trade_date")},
                )
            )
    session.commit()
    return warnings


# --- event labels ------------------------------------------------------------


def first_trading_day(published_at: datetime, calendar: list[date]) -> date | None:
    """The first trading day whose close could reflect news published at this moment."""
    local = published_at.astimezone(IST)
    for d in calendar:
        if d > local.date() or (d == local.date() and local.time() < MARKET_CLOSE):
            # A gap of more than a week means the news predates the stored price history.
            return d if (d - local.date()).days <= 7 else None
    return None


def _compound(returns: list[float]) -> float:
    total = 1.0
    for r in returns:
        total *= 1 + r
    return total - 1


def update_labels(session: Session) -> tuple[int, int]:
    """Compute labels for every filing and article linked to a watchlist company.

    Returns (labels written, labels complete). Complete labels are not recomputed.
    """
    compute_moves(session)
    calendar = sorted(index_returns(session, NIFTY))
    if not calendar:
        return 0, 0
    position = {d: i for i, d in enumerate(calendar)}
    done = set(
        session.execute(
            select(EventLabel.document_id, EventLabel.isin).where(EventLabel.complete)
        ).all()
    )
    written = complete = 0
    for company, _ in watchlist_benchmarks(session):
        moves = {
            m.trade_date: m
            for m in session.scalars(select(StockMove).where(StockMove.isin == company.isin))
        }
        docs = session.execute(
            select(Document.id, Document.published_at)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(DocumentCompany.isin == company.isin)
        ).all()
        rows = []
        for doc_id, published_at in docs:
            if (doc_id, company.isin) in done:
                continue
            day0 = first_trading_day(published_at, calendar)
            row = {"document_id": doc_id, "isin": company.isin, "day0": day0}
            sector = None
            for n in HORIZONS:
                values = _window(moves, calendar, position, day0, n)
                if values is None:
                    row |= {f"return_{n}d": None, f"excess_{n}d": None, f"sector_excess_{n}d": None}
                    continue
                stock = _compound([m.stock_return for m in values])
                row[f"return_{n}d"] = stock
                nifty = [m.nifty_return for m in values]
                row[f"excess_{n}d"] = stock - _compound(nifty) if None not in nifty else None
                sector_r = [m.sector_return for m in values]
                sector = values[0].sector_index
                row[f"sector_excess_{n}d"] = (
                    stock - _compound(sector_r) if sector and None not in sector_r else None
                )
            row["sector_index"] = sector
            row["complete"] = row["return_20d"] is not None
            rows.append(row)
            written += 1
            complete += row["complete"]
        if rows:
            stmt = insert(EventLabel).values(rows)
            session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["document_id", "isin"],
                    set_={c: stmt.excluded[c] for c in rows[0] if c not in ("document_id", "isin")}
                    | {"computed_at": func.now()},
                )
            )
    session.commit()
    return written, complete


def _window(moves, calendar, position, day0, n) -> list[StockMove] | None:
    """The stock's moves for n trading days from day0, or None if not all have happened yet."""
    if day0 is None or day0 not in position:
        return None
    days = calendar[position[day0] : position[day0] + n]
    if len(days) < n or any(d not in moves for d in days):
        return None
    return [moves[d] for d in days]
