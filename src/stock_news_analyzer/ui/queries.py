"""Read-only queries behind the dashboard. Each returns plain data (DataFrames / dicts) so it
can be tested without Streamlit."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.digest import _dedupe_filings, _index_change
from stock_news_analyzer.agents.prices import NIFTY, watchlist_benchmarks
from stock_news_analyzer.models import (
    Company,
    CorporateAction,
    Document,
    DocumentCompany,
    EventLabel,
    IndexDaily,
    PriceDaily,
    Run,
    StockMove,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

# Filing types worth marking on the price chart.
KEY_TYPES = (
    "order_win",
    "results",
    "concall_transcript",
    "investor_presentation",
    "credit_rating",
    "concall_audio",
)


def watchlist(session: Session) -> list[dict]:
    """One dict per watchlist stock: identity, benchmark and its latest daily move."""
    owned = dict(session.execute(select(WatchlistItem.isin, WatchlistItem.owned)).all())
    week_ago = datetime.now(IST) - timedelta(days=7)
    out = []
    for company, sector in sorted(watchlist_benchmarks(session), key=lambda c: c[0].nse_symbol):
        latest = session.scalars(
            select(StockMove)
            .where(StockMove.isin == company.isin)
            .order_by(StockMove.trade_date.desc())
            .limit(1)
        ).first()
        close = session.scalar(
            select(PriceDaily.close)
            .where(PriceDaily.isin == company.isin)
            .order_by(PriceDaily.trade_date.desc())
            .limit(1)
        )

        def count(doc_filter, isin=company.isin):
            return session.scalar(
                select(func.count(Document.id))
                .join(DocumentCompany, DocumentCompany.document_id == Document.id)
                .where(DocumentCompany.isin == isin, Document.published_at >= week_ago, doc_filter)
            )

        out.append(
            {
                "isin": company.isin,
                "symbol": company.nse_symbol,
                "name": company.name,
                "owned": bool(owned.get(company.isin)),
                "sector_index": sector,
                "close": float(close) if close is not None else None,
                "date": latest.trade_date if latest else None,
                "stock_return": latest.stock_return if latest else None,
                "excess_return": latest.excess_return if latest else None,
                "sector_excess_return": latest.sector_excess_return if latest else None,
                "zscore": latest.zscore if latest else None,
                "unusual": bool(latest and latest.unusual),
                "filings_7d": count(Document.doc_type != "news"),
                "news_7d": count(Document.doc_type == "news"),
            }
        )
    return out


def market(session: Session) -> list[dict]:
    """Nifty 50 and each watchlist sector index: latest close and daily change."""
    names = [NIFTY] + sorted({s for _, s in watchlist_benchmarks(session) if s})
    rows = []
    for name in names:
        day, close, change = _index_change(session, name)
        rows.append({"index": name, "date": day, "close": close, "change": change})
    return rows


def performance(session: Session, isin: str, start: date) -> pd.DataFrame:
    """Stock, Nifty 50 and sector index, each indexed to 100 on the first day shown.

    Built from the adjusted daily returns, so bonus issues and dividends don't show as drops.
    """
    moves = session.scalars(
        select(StockMove)
        .where(StockMove.isin == isin, StockMove.trade_date >= start)
        .order_by(StockMove.trade_date)
    ).all()
    if not moves:
        return pd.DataFrame(columns=["date", "stock", "nifty", "sector"])
    df = pd.DataFrame(
        {
            "date": [m.trade_date for m in moves],
            "stock": [m.stock_return for m in moves],
            "nifty": [m.nifty_return for m in moves],
            "sector": [m.sector_return for m in moves],
            "excess": [m.excess_return for m in moves],
            "zscore": [m.zscore for m in moves],
            "unusual": [m.unusual for m in moves],
        }
    )
    for col in ("stock", "nifty", "sector"):
        r = df[col].astype(float).fillna(0.0)
        r.iloc[0] = 0.0  # the first day is the base
        df[col] = 100 * (1 + r).cumprod() if df[col].notna().any() else None
    return df


def filings(
    session: Session,
    isin: str | None = None,
    doc_types: list[str] | None = None,
    search: str | None = None,
    since: date | None = None,
    dedupe: bool = False,
    limit: int = 500,
) -> pd.DataFrame:
    query = (
        select(Document, Company.nse_symbol)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .join(Company, Company.isin == DocumentCompany.isin)
        .where(Document.doc_type != "news")
        .order_by(Document.published_at.desc())
        .limit(limit)
    )
    if isin:
        query = query.where(DocumentCompany.isin == isin)
    if doc_types:
        query = query.where(Document.doc_type.in_(doc_types))
    if since:
        query = query.where(
            Document.published_at >= datetime.combine(since, datetime.min.time(), tzinfo=IST)
        )
    if search:
        like = f"%{search}%"
        query = query.where(or_(Document.title.ilike(like), Document.text.ilike(like)))
    rows = session.execute(query).all()
    docs = [d for d, _ in rows]
    symbols = {d.id: s for d, s in rows}
    if dedupe:
        docs = _dedupe_filings(docs)
    return pd.DataFrame(
        [
            {
                "id": d.id,
                "published": d.published_at.astimezone(IST).replace(tzinfo=None),
                "symbol": symbols[d.id],
                "exchange": d.source.upper(),
                "type": d.doc_type,
                "title": d.title,
                "text_status": d.text_status,
                "attachment_path": d.attachment_path,
                "attachment_url": d.attachment_url,
            }
            for d in docs
        ],
        columns=[
            "id",
            "published",
            "symbol",
            "exchange",
            "type",
            "title",
            "text_status",
            "attachment_path",
            "attachment_url",
        ],
    )


def doc_types(session: Session) -> list[str]:
    """Filing types present in the database, for the filter."""
    return list(
        session.scalars(
            select(Document.doc_type)
            .where(Document.doc_type != "news")
            .distinct()
            .order_by(Document.doc_type)
        )
    )


def document_text(session: Session, doc_id: int) -> str:
    doc = session.get(Document, doc_id)
    return (doc.text or "") if doc else ""


def news(
    session: Session,
    isin: str | None = None,
    search: str | None = None,
    since: date | None = None,
    limit: int = 500,
) -> pd.DataFrame:
    query = (
        select(Document, Company.nse_symbol)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .join(Company, Company.isin == DocumentCompany.isin)
        .where(Document.doc_type == "news")
        .order_by(Document.published_at.desc())
        .limit(limit)
    )
    if isin:
        query = query.where(DocumentCompany.isin == isin)
    if since:
        query = query.where(
            Document.published_at >= datetime.combine(since, datetime.min.time(), tzinfo=IST)
        )
    if search:
        query = query.where(Document.title.ilike(f"%{search}%"))
    return pd.DataFrame(
        [
            {
                "published": d.published_at.astimezone(IST).replace(tzinfo=None),
                "symbol": s,
                "publisher": d.publisher,
                "title": d.title,
                "url": d.url,
            }
            for d, s in session.execute(query).all()
        ],
        columns=["published", "symbol", "publisher", "title", "url"],
    )


def labels(session: Session, isin: str | None = None, news_too: bool = False) -> pd.DataFrame:
    query = (
        select(EventLabel, Document, Company.nse_symbol)
        .join(Document, Document.id == EventLabel.document_id)
        .join(Company, Company.isin == EventLabel.isin)
        .where(EventLabel.day0.is_not(None))
        .order_by(Document.published_at.desc())
    )
    if isin:
        query = query.where(EventLabel.isin == isin)
    if not news_too:
        query = query.where(Document.doc_type != "news")
    return pd.DataFrame(
        [
            {
                "document_id": d.id,
                "isin": lb.isin,
                "symbol": s,
                "published": d.published_at.astimezone(IST).replace(tzinfo=None),
                "day0": lb.day0,
                "type": d.doc_type,
                "exchange": d.source.upper() if d.doc_type != "news" else None,
                "title": d.title,
                "excess_1d": lb.excess_1d,
                "excess_5d": lb.excess_5d,
                "excess_20d": lb.excess_20d,
                "sector_excess_1d": lb.sector_excess_1d,
                "sector_excess_5d": lb.sector_excess_5d,
                "sector_excess_20d": lb.sector_excess_20d,
            }
            for lb, d, s in session.execute(query).all()
        ],
        columns=[
            "document_id",
            "isin",
            "symbol",
            "published",
            "day0",
            "type",
            "exchange",
            "title",
            "excess_1d",
            "excess_5d",
            "excess_20d",
            "sector_excess_1d",
            "sector_excess_5d",
            "sector_excess_20d",
        ],
    )


def event_study(session: Session, isin: str | None = None) -> pd.DataFrame:
    """Average return vs Nifty 50 after each filing type, over 1, 5 and 20 trading days.

    The BSE and NSE copies of one announcement count once (same stock, type and day0).
    """
    df = labels(session, isin)
    if df.empty:
        return pd.DataFrame(columns=["type", "events", "avg_1d", "avg_5d", "avg_20d", "n_20d"])
    df = df.sort_values("exchange").drop_duplicates(["isin", "type", "day0"])
    out = (
        df.groupby("type")
        .agg(
            events=("document_id", "count"),
            avg_1d=("excess_1d", "mean"),
            avg_5d=("excess_5d", "mean"),
            avg_20d=("excess_20d", "mean"),
            n_20d=("excess_20d", "count"),
        )
        .reset_index()
        .sort_values("events", ascending=False)
    )
    return out


def corporate_actions(session: Session, symbol: str) -> pd.DataFrame:
    rows = session.scalars(
        select(CorporateAction)
        .where(CorporateAction.symbol == symbol)
        .order_by(CorporateAction.ex_date.desc())
    ).all()
    return pd.DataFrame(
        [
            {
                "ex_date": a.ex_date,
                "kind": a.kind,
                "subject": a.subject,
                "price_factor": a.price_factor if a.price_factor != 1 else None,
                "dividend": float(a.dividend) if a.dividend is not None else None,
            }
            for a in rows
        ],
        columns=["ex_date", "kind", "subject", "price_factor", "dividend"],
    )


def runs(session: Session, limit: int = 100) -> pd.DataFrame:
    rows = session.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit)).all()
    return pd.DataFrame(
        [
            {
                "started": r.started_at.astimezone(IST).replace(tzinfo=None),
                "job": r.job,
                "status": r.status,
                "seconds": (r.finished_at - r.started_at).total_seconds()
                if r.finished_at
                else None,
                "summary": r.summary,
                "error": r.error,
            }
            for r in rows
        ],
        columns=["started", "job", "status", "seconds", "summary", "error"],
    )


def last_runs(session: Session) -> dict[str, dict]:
    out = {}
    for job in ("filings", "news", "prices", "securities", "digest"):
        r = session.scalars(
            select(Run).where(Run.job == job).order_by(Run.started_at.desc()).limit(1)
        ).first()
        out[job] = (
            {
                "started": r.started_at.astimezone(IST),
                "status": r.status,
                "summary": r.summary,
                "error": r.error,
            }
            if r
            else None
        )
    return out


def data_counts(session: Session) -> dict[str, object]:
    first, last = session.execute(
        select(func.min(IndexDaily.trade_date), func.max(IndexDaily.trade_date))
    ).one()
    return {
        "trading days": session.scalar(select(func.count(func.distinct(IndexDaily.trade_date)))),
        "price history": f"{first} to {last}" if first else "none",
        "price rows": session.scalar(select(func.count()).select_from(PriceDaily)),
        "filings": session.scalar(
            select(func.count()).select_from(Document).where(Document.doc_type != "news")
        ),
        "news articles": session.scalar(
            select(func.count()).select_from(Document).where(Document.doc_type == "news")
        ),
        "labels": session.scalar(select(func.count()).select_from(EventLabel)),
        "complete labels": session.scalar(
            select(func.count()).select_from(EventLabel).where(EventLabel.complete)
        ),
        "companies": session.scalar(select(func.count()).select_from(Company)),
    }


def latest_digest(data_dir: Path) -> tuple[str, str] | None:
    """(file name, Markdown) of the newest saved digest."""
    files = sorted((data_dir / "digests").glob("*.md"))
    if not files:
        return None
    return files[-1].name, files[-1].read_text(encoding="utf-8")
