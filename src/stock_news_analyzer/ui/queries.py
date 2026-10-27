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
    Concall,
    ConcallPoint,
    CorporateAction,
    Document,
    DocumentCompany,
    Event,
    EventLabel,
    IndexDaily,
    LlmCall,
    MoveExplanation,
    NewsTriage,
    Order,
    PriceDaily,
    Promise,
    PromiseCheck,
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
    for company, sector in sorted(
        watchlist_benchmarks(session), key=lambda c: c[0].nse_symbol or c[0].name
    ):
        latest = session.scalars(
            select(StockMove)
            .where(StockMove.isin == company.isin)
            .order_by(StockMove.trade_date.desc())
            .limit(1)
        ).first()
        why = (
            session.get(MoveExplanation, (latest.isin, latest.trade_date))
            if latest and latest.unusual
            else None
        )
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
                "symbol": company.nse_symbol or company.bse_code,
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
                "cause": why.cause if why else None,
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
    rows = session.execute(
        select(StockMove, MoveExplanation)
        .outerjoin(
            MoveExplanation,
            (MoveExplanation.isin == StockMove.isin)
            & (MoveExplanation.trade_date == StockMove.trade_date),
        )
        .where(StockMove.isin == isin, StockMove.trade_date >= start)
        .order_by(StockMove.trade_date)
    ).all()
    moves = [m for m, _ in rows]
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
            "cause": [e.cause if e else None for _, e in rows],
            "explanation": [e.explanation if e else None for _, e in rows],
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
    hide_noise: bool = False,
    min_importance: int = 1,
    topics: list[str] | None = None,
) -> pd.DataFrame:
    """Articles with their triage (empty until `sna triage run` has seen them).

    `hide_noise` leaves out articles triaged as off-topic or as a repeat of an earlier story;
    `min_importance` and `topics` filter on the triage, so they also leave out untriaged ones.
    """
    query = (
        select(Document, Company.nse_symbol, NewsTriage)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .join(Company, Company.isin == DocumentCompany.isin)
        .outerjoin(
            NewsTriage,
            (NewsTriage.document_id == Document.id) & (NewsTriage.isin == DocumentCompany.isin),
        )
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
    if hide_noise:
        query = query.where(
            NewsTriage.document_id.is_(None)
            | (NewsTriage.relevant & NewsTriage.duplicate_of.is_(None))
        )
    if min_importance > 1:
        query = query.where(NewsTriage.importance >= min_importance)
    if topics:
        query = query.where(NewsTriage.topic.in_(topics))
    return pd.DataFrame(
        [
            {
                "published": d.published_at.astimezone(IST).replace(tzinfo=None),
                "symbol": s,
                "importance": t.importance if t else None,
                "topic": t.topic if t else None,
                "sentiment": t.sentiment if t else None,
                "title": d.title,
                "summary": t.summary if t else None,
                "publisher": d.publisher,
                "url": d.url,
            }
            for d, s, t in session.execute(query).all()
        ],
        columns=[
            "published",
            "symbol",
            "importance",
            "topic",
            "sentiment",
            "title",
            "summary",
            "publisher",
            "url",
        ],
    )


def llm_usage(session: Session) -> dict:
    """This month's LLM spend against the budget, by task and model."""
    from stock_news_analyzer.config import get_settings
    from stock_news_analyzer.llm import month_spend

    now = datetime.now(IST)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = session.execute(
        select(
            LlmCall.task,
            LlmCall.model,
            func.count(),
            func.count().filter(~LlmCall.ok),
            func.sum(LlmCall.input_tokens),
            func.sum(LlmCall.output_tokens),
            func.sum(LlmCall.cost_usd),
        )
        .where(LlmCall.at >= start)
        .group_by(LlmCall.task, LlmCall.model)
        .order_by(LlmCall.task)
    ).all()
    return {
        "month": f"{now:%B %Y}",
        "spent": float(month_spend(session)),
        "budget": get_settings().llm_monthly_budget_usd,
        "pending_triage": session.scalar(
            select(func.count())
            .select_from(DocumentCompany)
            .join(Document, Document.id == DocumentCompany.document_id)
            .join(WatchlistItem, WatchlistItem.isin == DocumentCompany.isin)
            .outerjoin(
                NewsTriage,
                (NewsTriage.document_id == DocumentCompany.document_id)
                & (NewsTriage.isin == DocumentCompany.isin),
            )
            .where(Document.doc_type == "news", NewsTriage.document_id.is_(None))
        ),
        "by_task": pd.DataFrame(
            [
                {
                    "task": task,
                    "model": model,
                    "calls": calls,
                    "failed": failed,
                    "input tokens": tin or 0,
                    "output tokens": tout or 0,
                    "cost $": float(usd or 0),
                }
                for task, model, calls, failed, tin, tout, usd in rows
            ],
            columns=[
                "task",
                "model",
                "calls",
                "failed",
                "input tokens",
                "output tokens",
                "cost $",
            ],
        ),
    }


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


def unusual_days(session: Session, isin: str) -> pd.DataFrame:
    """Every unusual day of a stock, newest first, with its explanation when there is one."""
    rows = session.execute(
        select(StockMove, MoveExplanation)
        .outerjoin(
            MoveExplanation,
            (MoveExplanation.isin == StockMove.isin)
            & (MoveExplanation.trade_date == StockMove.trade_date),
        )
        .where(StockMove.isin == isin, StockMove.unusual)
        .order_by(StockMove.trade_date.desc())
    ).all()
    titles = {}
    ids = {i for _, e in rows if e for i in e.evidence}
    if ids:
        titles = dict(
            session.execute(select(Document.id, Document.title).where(Document.id.in_(ids))).all()
        )
    return pd.DataFrame(
        [
            {
                "date": m.trade_date,
                "stock": m.stock_return,
                "vs_nifty": m.excess_return,
                "zscore": m.zscore,
                "cause": e.cause if e else None,
                "confidence": e.confidence if e else None,
                "explanation": e.explanation if e else None,
                "evidence": " | ".join(titles[i] for i in e.evidence if i in titles) if e else None,
            }
            for m, e in rows
        ],
        columns=[
            "date",
            "stock",
            "vs_nifty",
            "zscore",
            "cause",
            "confidence",
            "explanation",
            "evidence",
        ],
    )


def deals(session: Session, isin: str) -> pd.DataFrame:
    """A stock's bulk and block deals, newest first, with their share of the day's volume."""
    from stock_news_analyzer.agents.deals import watchlist_deals

    rows = watchlist_deals(session, isin, date(2000, 1, 1), date.today())
    return pd.DataFrame(
        [
            {
                "date": d.trade_date,
                "kind": d.kind,
                "side": d.side,
                "quantity": d.quantity,
                "price": float(d.price) if d.price is not None else None,
                "of_volume": share,
                "client": d.client,
            }
            for d, share in sorted(
                rows, key=lambda r: (r[0].trade_date, r[0].quantity), reverse=True
            )
        ],
        columns=["date", "kind", "side", "quantity", "price", "of_volume", "client"],
    )


def concalls(session: Session, isin: str) -> list[dict]:
    """A stock's analysed earnings calls, newest first, each with its points."""
    calls = session.scalars(
        select(Concall)
        .where(Concall.isin == isin, Concall.status == "analysed")
        .order_by(Concall.published_at.desc())
    ).all()
    points: dict[int, list[dict]] = {}
    if calls:
        for p in session.scalars(
            select(ConcallPoint)
            .where(ConcallPoint.concall_id.in_([c.id for c in calls]))
            .order_by(ConcallPoint.id)
        ):
            points.setdefault(p.concall_id, []).append(
                {
                    "category": p.category,
                    "point": p.text,
                    "sentiment": p.sentiment,
                    "quote": p.quote if p.quote_found else None,
                }
            )
    return [
        {
            "id": c.id,
            "quarter": c.quarter,
            "filed": c.published_at.astimezone(IST).replace(tzinfo=None),
            "call_date": c.call_date,
            "tone": c.tone,
            "summary": c.summary,
            "action_points": (c.analysis or {}).get("action_points", []),
            "changes": (c.analysis or {}).get("changes", []),
            "concerns": (c.analysis or {}).get("analyst_concerns", []),
            "points": points.get(c.id, []),
            "document_id": c.document_id,
            "note": c.note,
        }
        for c in calls
    ]


def concall_text(session: Session, doc_id: int) -> str:
    """The transcript a call was read from: the filing's text, or the linked transcript's."""
    call = session.scalars(select(Concall).where(Concall.document_id == doc_id)).first()
    if call and call.linked_text:
        return call.linked_text
    return document_text(session, doc_id)


def concall_gaps(session: Session, isin: str) -> pd.DataFrame:
    """Transcript filings that were not analysed, and why (copies are left out)."""
    rows = session.scalars(
        select(Concall)
        .where(Concall.isin == isin, Concall.status.in_(("no_text", "skipped")))
        .order_by(Concall.published_at.desc())
    ).all()
    return pd.DataFrame(
        [
            {
                "filed": r.published_at.astimezone(IST).replace(tzinfo=None),
                "status": r.status,
                "why": r.note,
            }
            for r in rows
        ],
        columns=["filed", "status", "why"],
    )


def promises(session: Session, isin: str | None = None) -> pd.DataFrame:
    """The promise ledger, soonest due first; `overdue` when the date passed while still open."""
    query = (
        select(Promise, Concall.quarter, Company.nse_symbol)
        .join(Concall, Concall.id == Promise.concall_id)
        .join(Company, Company.isin == Promise.isin)
        .order_by(Promise.due_date.nulls_last(), Promise.id)
    )
    if isin:
        query = query.where(Promise.isin == isin)
    today = datetime.now(IST).date()
    return pd.DataFrame(
        [
            {
                "symbol": sym,
                "promise": p.statement,
                "target": p.target,
                "due": p.due,
                "due_date": p.due_date,
                "status": p.status,
                "overdue": bool(
                    p.due_date and p.due_date < today and p.status in ("open", "on_track")
                ),
                "note": p.status_note,
                "said_in": quarter,
                "quote": p.quote if p.quote_found else None,
            }
            for p, quarter, sym in session.execute(query).all()
        ],
        columns=[
            "symbol",
            "promise",
            "target",
            "due",
            "due_date",
            "status",
            "overdue",
            "note",
            "said_in",
            "quote",
        ],
    )


def credibility(session: Session) -> list[dict]:
    """Per company: promises kept, kept late, partly kept, missed, dropped, overdue, still to
    come, and the credibility score (see agents/promises.py)."""
    from stock_news_analyzer.agents.promises import credibility as score

    return score(session)


def promise_checks(session: Session, isin: str) -> pd.DataFrame:
    """Every check of a stock's promises, newest first, with the documents it rested on."""
    rows = session.execute(
        select(PromiseCheck, Promise)
        .join(Promise, Promise.id == PromiseCheck.promise_id)
        .where(Promise.isin == isin)
        .order_by(PromiseCheck.checked_at.desc())
    ).all()
    ids = {i for c, _ in rows for i in c.evidence}
    titles = (
        dict(session.execute(select(Document.id, Document.title).where(Document.id.in_(ids))).all())
        if ids
        else {}
    )
    return pd.DataFrame(
        [
            {
                "checked": c.checked_at.astimezone(IST).replace(tzinfo=None),
                "promise": p.statement,
                "verdict": c.verdict,
                "note": c.note,
                "based_on": " | ".join(titles[i] for i in c.evidence if i in titles),
            }
            for c, p in rows
        ],
        columns=["checked", "promise", "verdict", "note", "based_on"],
    )


def order_book(session: Session, isin: str) -> dict:
    """A company's order data: quarterly rows, the last-four-quarters summary, and its orders
    (newest first). Empty `quarters` when it has none."""
    from stock_news_analyzer.agents import orders as ob

    rows = session.scalars(
        select(Order).where(Order.isin == isin).order_by(Order.announced_at.desc())
    ).all()
    return {
        "quarters": pd.DataFrame(ob.quarterly(session, isin)),
        "summary": ob.summary(session, isin),
        "orders": pd.DataFrame(
            [
                {
                    "announced": o.announced_at.astimezone(IST).replace(tzinfo=None),
                    "kind": o.kind,
                    "value_cr": float(o.value_cr) if o.value_cr is not None else None,
                    "range": (
                        f"{o.value_low_cr:,.0f}-{o.value_high_cr:,.0f}"
                        if o.value_low_cr is not None and o.value_high_cr is not None
                        else None
                    ),
                    "client": o.client,
                    "client_type": o.client_type,
                    "segment": o.segment,
                    "months": o.execution_months,
                    "description": o.description,
                }
                for o in rows
            ],
            columns=[
                "announced",
                "kind",
                "value_cr",
                "range",
                "client",
                "client_type",
                "segment",
                "months",
                "description",
            ],
        ),
    }


RESULT_COLUMNS = [
    "period",
    "revenue_cr",
    "revenue_yoy",
    "ebitda_cr",
    "ebitda_margin",
    "pat_cr",
    "pat_yoy",
    "pat_margin",
    "eps",
    "basis",
    "checked",
]


def results(session: Session, isin: str) -> pd.DataFrame:
    """A company's results by quarter (or half year), oldest first (see agents/results.table)."""
    from stock_news_analyzer.agents.results import table

    return pd.DataFrame(table(session, isin), columns=RESULT_COLUMNS)


EVENT_COLUMNS = [
    "id",
    "filed",
    "type",
    "importance",
    "sentiment",
    "headline",
    "value_cr",
    "materiality",
    "qa",
    "qa_notes",
    "quote",
    "link",
]


def events(session: Session, isin: str, days: int = 730) -> pd.DataFrame:
    """A company's events, newest first: those shown (see agents/qa.shown), with their QA
    status ('unchecked' for flagged ones not reviewed)."""
    from stock_news_analyzer.agents.qa import shown

    since = datetime.now(IST) - timedelta(days=days)
    rows = session.execute(
        select(Event, Document.attachment_url)
        .join(Document, Document.id == Event.document_id)
        .where(Event.isin == isin, Event.published_at >= since, shown())
        .order_by(Event.published_at.desc(), Event.id)
    ).all()
    out = []
    for e, url in rows:
        qa = "unchecked" if e.qa_status == "flagged" and e.review is None else "checked"
        out.append(
            {
                "id": e.id,
                "filed": e.published_at.astimezone(IST).date(),
                "type": e.event_type.replace("_", " "),
                "importance": e.importance,
                "sentiment": e.sentiment,
                "headline": e.headline,
                "value_cr": float(e.value_cr) if e.value_cr is not None else None,
                "materiality": e.materiality,
                "qa": "you accepted it" if e.review == "accepted" else qa,
                "qa_notes": "; ".join(e.qa_notes),
                "quote": e.quote,
                "link": url,
            }
        )
    return pd.DataFrame(out, columns=EVENT_COLUMNS)


def order_peers(session: Session) -> pd.DataFrame:
    """Order-driven watchlist companies side by side (see agents/orders.peers)."""
    from stock_news_analyzer.agents.orders import peers

    return pd.DataFrame(
        peers(session),
        columns=[
            "symbol",
            "book_to_bill",
            "years_of_revenue",
            "execution",
            "announced_growth",
            "order_book_cr",
            "government_share",
            "top_client_share",
            "orders_last_year",
        ],
    )


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
    for job in (
        "filings",
        "news",
        "triage",
        "deals",
        "prices",
        "explain",
        "securities",
        "digest",
    ):
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
        "earnings calls analysed": session.scalar(
            select(func.count()).select_from(Concall).where(Concall.status == "analysed")
        ),
        "promises": session.scalar(select(func.count()).select_from(Promise)),
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
