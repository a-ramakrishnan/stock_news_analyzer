"""Reporter, basic version (agent 16): the daily digest.

Everything since the previous digest, per watchlist company: the latest daily move against the
Nifty 50 and sector index, unusual days, new filings, news headlines, and what recent filings
did to the price; and earnings calls analysed since then. Written as Markdown, printed and
saved under data/digests/.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.deals import watchlist_deals
from stock_news_analyzer.agents.prices import NIFTY, watchlist_benchmarks
from stock_news_analyzer.models import (
    Company,
    Concall,
    Document,
    DocumentCompany,
    EventLabel,
    IndexDaily,
    MoveExplanation,
    NewsTriage,
    Promise,
    PromiseCheck,
    Run,
    StockMove,
    WatchlistItem,
)
from stock_news_analyzer.sources.announcements import IST

MAX_FILINGS = 12
MAX_NEWS = 8
LABEL_TYPES = (
    "order_win",
    "results",
    "concall_transcript",
    "investor_presentation",
    "credit_rating",
)


@dataclass
class Digest:
    markdown: str
    since: datetime
    until: datetime
    filings: int
    news: int
    unusual: int


def pct(x: float | None) -> str:
    return f"{x * 100:+.2f}%" if x is not None else "–"


def _when(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %H:%M")


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def last_digest_time(session: Session) -> datetime | None:
    return session.scalar(
        select(func.max(Run.started_at)).where(Run.job == "digest", Run.status == "ok")
    )


def _index_change(session: Session, name: str) -> tuple[str, float | None, float | None]:
    rows = session.execute(
        select(IndexDaily.trade_date, IndexDaily.close)
        .where(IndexDaily.index_name == name, IndexDaily.close.is_not(None))
        .order_by(IndexDaily.trade_date.desc())
        .limit(2)
    ).all()
    if not rows:
        return "–", None, None
    latest = rows[0]
    change = float(latest.close) / float(rows[1].close) - 1 if len(rows) == 2 else None
    return latest.trade_date.strftime("%d %b"), float(latest.close), change


def _documents(session, isin, since, until, news: bool):
    query = (
        select(Document)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .where(
            DocumentCompany.isin == isin,
            Document.published_at >= since,
            Document.published_at < until,
        )
        .order_by(Document.published_at.desc())
    )
    query = (
        query.where(Document.doc_type == "news")
        if news
        else query.where(Document.doc_type != "news")
    )
    return session.scalars(query).all()


def _dedupe_filings(docs: list[Document]) -> list[Document]:
    """Most announcements are filed on both exchanges; keep one per type within 30 minutes."""
    kept: list[Document] = []
    for doc in sorted(docs, key=lambda d: (d.source != "bse", d.published_at)):
        if not any(
            k.doc_type == doc.doc_type
            and abs((k.published_at - doc.published_at).total_seconds()) < 1800
            for k in kept
        ):
            kept.append(doc)
    return sorted(kept, key=lambda d: d.published_at, reverse=True)


def _dedupe_news(docs: list[Document]) -> list[Document]:
    seen, kept = set(), []
    for doc in docs:
        key = _norm(doc.title)[:80]
        if key not in seen:
            seen.add(key)
            kept.append(doc)
    return kept


def _triaged_news(session: Session, isin: str, docs: list[Document]):
    """Articles with their triage, most important first; off-topic and repeated ones left out.

    Articles not triaged yet (no API key, or triage hasn't run) are kept, after the triaged
    ones. Returns ([(document, triage or None)], number hidden).
    """
    triage = {
        t.document_id: t
        for t in session.scalars(
            select(NewsTriage).where(
                NewsTriage.isin == isin, NewsTriage.document_id.in_([d.id for d in docs])
            )
        )
    }
    kept = [
        (d, triage.get(d.id))
        for d in docs
        if d.id not in triage or (triage[d.id].relevant and triage[d.id].duplicate_of is None)
    ]
    kept.sort(key=lambda pair: -(pair[1].importance if pair[1] else 0))  # stable: newest first
    return kept, len(docs) - len(kept)


def _earnings_calls(session: Session, since: datetime, until: datetime) -> list[str]:
    """Earnings calls analysed since the previous digest: summary, what to watch, changes."""
    rows = session.execute(
        select(Concall, Company)
        .join(Company, Company.isin == Concall.isin)
        .where(
            Concall.status == "analysed",
            Concall.created_at >= since,
            Concall.created_at < until,
        )
        .order_by(Concall.published_at)
    ).all()
    if not rows:
        return []
    lines = ["", "## Earnings calls"]
    for c, company in rows:
        a = c.analysis or {}
        lines += [
            "",
            f"### {company.nse_symbol or company.name} {c.quarter}: {c.tone}",
            "",
            c.summary or "",
            "",
            "To watch:",
            *[f"- {point}" for point in a.get("action_points", [])],
        ]
        if a.get("changes"):
            lines += ["", "Since the previous call:"]
            lines += [f"- {ch['kind']}: {ch['text']}" for ch in a["changes"]]
        if a.get("promises"):
            lines += ["", "Promises made:"]
            lines += [f"- {p['statement']} (due {p['due']})" for p in a["promises"]]
        lines.append(f"\nIn full: `sna concalls show {company.nse_symbol}`")
    return lines


def _promises(session: Session, since: datetime, until: datetime) -> list[str]:
    """Promises settled since the previous digest, and those falling due in the next 30 days."""
    from stock_news_analyzer.agents.promises import UNSETTLED, VERDICT_STATUS

    settled = session.execute(
        select(PromiseCheck, Promise, Company.nse_symbol)
        .join(Promise, Promise.id == PromiseCheck.promise_id)
        .join(Company, Company.isin == Promise.isin)
        .where(
            PromiseCheck.checked_at >= since,
            PromiseCheck.checked_at < until,
            PromiseCheck.verdict.in_(VERDICT_STATUS),
        )
        .order_by(Company.nse_symbol, Promise.due_date)
    ).all()
    today = until.astimezone(IST).date()
    coming = session.execute(
        select(Promise, Company.nse_symbol)
        .join(Company, Company.isin == Promise.isin)
        .where(
            Promise.status.in_(UNSETTLED),
            Promise.due_date >= today,
            Promise.due_date <= today + timedelta(days=30),
        )
        .order_by(Promise.due_date)
    ).all()
    if not settled and not coming:
        return []
    lines = ["", "## Promises"]
    if settled:
        lines += ["", "Settled:"]
        lines += [
            f"- {sym} **{check.verdict.replace('_', ' ')}**: {p.statement} (due "
            f"{p.due_date:%d %b %Y}). {check.note}"
            for check, p, sym in settled
        ]
    if coming:
        lines += ["", "Due in the next 30 days:"]
        lines += [f"- {sym} {p.due_date:%d %b}: {p.statement}" for p, sym in coming]
    return lines


def build_digest(session: Session, since: datetime, until: datetime) -> Digest:
    lines = [
        f"# Daily digest, {until.astimezone(IST):%d %b %Y %H:%M} IST",
        "",
        f"Covers {_when(since)} to {_when(until)} IST.",
        "",
        "## Market",
        "",
        "| Index | Date | Close | Change |",
        "| --- | --- | --- | --- |",
    ]
    companies = watchlist_benchmarks(session)
    for name in [NIFTY] + sorted({s for _, s in companies if s}):
        day, close, change = _index_change(session, name)
        close_s = f"{close:,.2f}" if close is not None else "–"
        lines.append(f"| {name} | {day} | {close_s} | {pct(change)} |")

    lines += _earnings_calls(session, since, until)
    lines += _promises(session, since, until)

    owned = dict(session.execute(select(WatchlistItem.isin, WatchlistItem.owned)).all())
    total_filings = total_news = total_unusual = 0
    unusual_summary = []

    for company, sector in sorted(companies, key=lambda c: c[0].nse_symbol or ""):
        symbol = company.nse_symbol or company.isin
        lines += ["", f"## {symbol}: {company.name}{' (owned)' if owned.get(company.isin) else ''}"]

        latest = session.scalars(
            select(StockMove)
            .where(StockMove.isin == company.isin)
            .order_by(StockMove.trade_date.desc())
            .limit(1)
        ).first()
        if latest:
            z = f", z {latest.zscore:+.1f}" if latest.zscore is not None else ""
            flag = " **unusual**" if latest.unusual else ""
            lines += [
                "",
                f"Last close ({latest.trade_date:%d %b}): {pct(latest.stock_return)}; "
                f"vs Nifty 50 {pct(latest.excess_return)}; "
                f"vs {sector or 'sector'} {pct(latest.sector_excess_return)}{z}{flag}",
            ]

        unusual = session.scalars(
            select(StockMove)
            .where(
                StockMove.isin == company.isin,
                StockMove.unusual,
                StockMove.trade_date >= since.astimezone(IST).date(),
            )
            .order_by(StockMove.trade_date.desc())
        ).all()
        if unusual:
            total_unusual += len(unusual)
            lines += ["", "**Unusual days:**"]
            for m in unusual:
                why = session.get(MoveExplanation, (m.isin, m.trade_date))
                reason = (
                    f"  \n  Likely cause ({why.cause}, {why.confidence} confidence): "
                    f"{why.explanation}"
                    if why
                    else ""
                )
                lines.append(
                    f"- {m.trade_date:%d %b}: {pct(m.stock_return)} "
                    f"({pct(m.excess_return)} vs Nifty 50, z {m.zscore:+.1f}){reason}"
                )
                unusual_summary.append(
                    f"- {symbol} {m.trade_date:%d %b}: {pct(m.excess_return)} vs Nifty 50"
                    + (f" ({why.cause})" if why else " (not explained yet)")
                )

        filings = _dedupe_filings(_documents(session, company.isin, since, until, news=False))
        total_filings += len(filings)
        lines += ["", f"**Filings ({len(filings)}):**" if filings else "No new filings."]
        for doc in filings[:MAX_FILINGS]:
            lines.append(
                f"- {_when(doc.published_at)} {doc.source.upper()} `{doc.doc_type}`: {doc.title}"
            )
        if len(filings) > MAX_FILINGS:
            lines.append(f"- … and {len(filings) - MAX_FILINGS} more (`sna filings list {symbol}`)")

        deals = watchlist_deals(
            session, company.isin, since.astimezone(IST).date(), until.astimezone(IST).date()
        )
        if deals:
            lines += ["", f"**Bulk/block deals ({len(deals)}):**"]
            for deal, share in deals:
                price = f" at Rs {deal.price:,.2f}" if deal.price is not None else ""
                of_volume = f" ({share:.1%} of the day's volume)" if share is not None else ""
                lines.append(
                    f"- {deal.trade_date:%d %b} {deal.kind}: {deal.client} "
                    f"{deal.side.lower()}s {deal.quantity:,} shares{price}{of_volume}"
                )

        news, hidden = _triaged_news(
            session,
            company.isin,
            _dedupe_news(_documents(session, company.isin, since, until, True)),
        )
        total_news += len(news)
        lines += ["", f"**News ({len(news)}):**" if news else "No news."]
        for doc, triage in news[:MAX_NEWS]:
            title = f"[{doc.title}]({doc.url})" if doc.url else doc.title
            if triage:
                lines.append(
                    f"- {'★' * triage.importance} {triage.topic}, {triage.sentiment} · "
                    f"{_when(doc.published_at)} {doc.publisher or ''}: {title}  \n"
                    f"  {triage.summary}"
                )
            else:
                lines.append(f"- {_when(doc.published_at)} {doc.publisher or ''}: {title}")
        if len(news) > MAX_NEWS:
            lines.append(f"- … and {len(news) - MAX_NEWS} more (`sna triage list {symbol}`)")
        if hidden:
            lines.append(f"- {hidden} off-topic or repeated articles hidden")

        labelled = session.execute(
            select(EventLabel, Document)
            .join(Document, Document.id == EventLabel.document_id)
            .where(
                EventLabel.isin == company.isin,
                EventLabel.excess_1d.is_not(None),
                Document.doc_type.in_(LABEL_TYPES),
                Document.published_at >= until - timedelta(days=30),
            )
            .order_by(Document.published_at.desc())
        ).all()
        labelled = [(lb, d) for lb, d in labelled if d in _dedupe_filings([x for _, x in labelled])]
        if labelled:
            lines += [
                "",
                "**What recent filings did to the price (vs Nifty 50):**",
                "",
                "| Filed | Type | 1 day | 5 days | 20 days | Title |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for label, doc in labelled[:6]:
                lines.append(
                    f"| {_when(doc.published_at)} | {doc.doc_type} | {pct(label.excess_1d)} | "
                    f"{pct(label.excess_5d)} | {pct(label.excess_20d)} | {doc.title[:70]} |"
                )

    lines += ["", "## Unusual moves", ""]
    lines += unusual_summary or ["None in this period."]

    lines += [
        "",
        "## Data collection",
        "",
        "| Job | Last run | Status | Result |",
        "| --- | --- | --- | --- |",
    ]
    for job in (
        "filings",
        "news",
        "triage",
        "deals",
        "prices",
        "explain",
        "concalls",
        "promises",
        "securities",
    ):
        run = session.scalars(
            select(Run).where(Run.job == job).order_by(Run.started_at.desc()).limit(1)
        ).first()
        if run:
            result = (run.error or run.summary or "").replace("\n", " ")[:90]
            lines.append(f"| {job} | {_when(run.started_at)} | {run.status} | {result} |")
        else:
            lines.append(f"| {job} | never | – | |")
    lines += ["", "_Not investment advice. Generated by stock_news_analyzer._", ""]

    return Digest(
        markdown="\n".join(lines),
        since=since,
        until=until,
        filings=total_filings,
        news=total_news,
        unusual=total_unusual,
    )


def save_digest(digest: Digest, data_dir: Path) -> Path:
    path = data_dir / "digests" / f"{digest.until.astimezone(IST):%Y-%m-%d_%H%M}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest.markdown, encoding="utf-8")
    return path
