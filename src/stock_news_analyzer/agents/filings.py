"""Filings Collector (agent 2).

Pulls corporate announcements from BSE and NSE for every company on the watchlist, stores each
one unchanged with its publication time, downloads the attached file and extracts its text.
"""

import hashlib
import io
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

from pypdf import PdfReader
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.models import Company, Document, DocumentCompany, WatchlistItem
from stock_news_analyzer.sources.announcements import (
    CONCALL_MATERIAL,
    IST,
    Announcement,
    bse_total_rows,
    parse_bse,
    parse_nse,
)
from stock_news_analyzer.sources.exchange_http import ExchangeError

log = logging.getLogger(__name__)

SOURCES = ("bse", "nse")
CHUNK_DAYS = 30
# Attachments downloaded under the 'important' policy (backfills default to this).
IMPORTANT_TYPES = CONCALL_MATERIAL | {"order_win", "credit_rating", "concall_schedule"}


class Client(Protocol):
    def bse_announcements(self, scrip_code: str, start: date, end: date, page: int = 1): ...
    def nse_announcements(self, symbol: str, start: date, end: date): ...
    def download(self, exchange: str, urls: list[str]) -> tuple[str, bytes, bool]: ...


@dataclass
class CollectResult:
    new: int = 0
    already_had: int = 0
    attachments: int = 0
    errors: list[str] = field(default_factory=list)


def date_chunks(start: date, end: date, days: int = CHUNK_DAYS) -> Iterator[tuple[date, date]]:
    """Split [start, end] into windows of at most `days` days, newest first."""
    hi = end
    while hi >= start:
        lo = max(start, hi - timedelta(days=days - 1))
        yield lo, hi
        hi = lo - timedelta(days=1)


def extract_text(content: bytes) -> tuple[str, str]:
    """Text of a PDF and a status: 'ok', 'empty' (no text layer, e.g. scanned) or 'failed'."""
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # malformed PDFs are common; keep the file, record the failure
        log.warning("could not read PDF: %s", exc)
        return "", "failed"
    return text, ("ok" if text else "empty")


def watchlist_companies(session: Session, symbol: str | None = None) -> list[Company]:
    query = select(Company).join(WatchlistItem, WatchlistItem.isin == Company.isin)
    if symbol:
        query = query.where(Company.nse_symbol == symbol.upper())
    return list(session.scalars(query.order_by(Company.name)))


class FilingsCollector:
    def __init__(
        self, session: Session, client: Client, data_dir: Path, pdf_policy: str = "all"
    ) -> None:
        if pdf_policy not in ("all", "important", "none"):
            raise ValueError(f"unknown pdf policy: {pdf_policy}")
        self.session = session
        self.client = client
        self.data_dir = data_dir
        self.pdf_policy = pdf_policy

    # --- fetching listings ---------------------------------------------------

    def collect(
        self,
        companies: list[Company],
        start: date | None = None,
        end: date | None = None,
        default_days: int = 7,
        sources: tuple[str, ...] = SOURCES,
        progress: Callable[[str], None] | None = None,
    ) -> CollectResult:
        """Fetch announcements for each company and source.

        Without `start`, each company/source continues from its latest stored filing (minus a
        day of overlap), or goes back `default_days` the first time. `progress` receives one
        line per company, exchange and 30-day window.
        """
        end = end or datetime.now(IST).date()
        result = CollectResult()
        for company in companies:
            for source in sources:
                code = company.bse_code if source == "bse" else company.nse_symbol
                if not code:
                    continue
                since = start or self._resume_date(company.isin, source, end, default_days)
                label = f"{company.nse_symbol or company.isin} {source.upper()}"
                try:
                    for lo, hi in date_chunks(since, end):
                        new, had, pdfs = result.new, result.already_had, result.attachments
                        for ann in self._chunk(source, code, lo, hi):
                            self._store(ann, company, result)
                        if progress:
                            progress(
                                f"{label} {lo}..{hi}: {result.new - new} new, "
                                f"{result.already_had - had} already stored, "
                                f"{result.attachments - pdfs} PDFs"
                            )
                except ExchangeError as exc:
                    msg = f"{company.nse_symbol or company.isin} {source.upper()}: {exc}"
                    log.error(msg)
                    result.errors.append(msg)
        return result

    def _resume_date(self, isin: str, source: str, end: date, default_days: int) -> date:
        latest = self.session.scalar(
            select(func.max(Document.published_at))
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(DocumentCompany.isin == isin, Document.source == source)
        )
        if latest is None:
            return end - timedelta(days=default_days)
        return latest.astimezone(IST).date() - timedelta(days=1)

    def _chunk(self, source: str, code: str, lo: date, hi: date) -> Iterator[Announcement]:
        if source == "nse":
            yield from parse_nse(self.client.nse_announcements(code, lo, hi))
            return
        page, seen = 1, 0
        while True:
            data = self.client.bse_announcements(code, lo, hi, page)
            rows = parse_bse(data)
            yield from rows
            seen += len(data.get("Table") or [])
            if not rows or seen >= bse_total_rows(data):
                break
            page += 1

    # --- storing -------------------------------------------------------------

    def _store(self, ann: Announcement, company: Company, result: CollectResult) -> None:
        doc_id = self.session.scalar(
            insert(Document)
            .values(
                source=ann.source,
                source_id=ann.source_id,
                doc_type=ann.doc_type,
                title=ann.title,
                subject=ann.subject,
                category=ann.category,
                published_at=ann.published_at,
                attachment_url=ann.attachment_urls[0] if ann.attachment_urls else None,
                attachment_bytes=ann.attachment_bytes,
                text_status="pending" if ann.attachment_urls else "skipped",
                raw=ann.raw,
            )
            .on_conflict_do_nothing(constraint="documents_source_id")
            .returning(Document.id)
        )
        if doc_id is None:
            result.already_had += 1
            self.session.rollback()
            return
        self.session.execute(
            insert(DocumentCompany)
            .values(document_id=doc_id, isin=company.isin)
            .on_conflict_do_nothing()
        )
        self.session.commit()
        result.new += 1

        doc = self.session.get(Document, doc_id)
        if self._wants_attachment(doc) and self._fetch_attachment(doc, company.isin, ann):
            result.attachments += 1

    def _wants_attachment(self, doc: Document) -> bool:
        if doc.attachment_url is None or self.pdf_policy == "none":
            return False
        return self.pdf_policy == "all" or doc.doc_type in IMPORTANT_TYPES

    # --- attachments ---------------------------------------------------------

    def _fetch_attachment(self, doc: Document, isin: str, ann: Announcement | None = None) -> bool:
        urls = ann.attachment_urls if ann else [doc.attachment_url]
        try:
            url, content, complete = self.client.download(doc.source, urls)
        except ExchangeError as exc:
            log.warning("attachment for document %s: %s", doc.id, exc)
            doc.text_status = "failed"
            self.session.commit()
            return False

        suffix = PurePosixPath(url.split("?")[0]).suffix.lower() or ".pdf"
        month = doc.published_at.astimezone(IST).strftime("%Y-%m")
        rel = Path("filings") / isin / doc.source / month / f"{doc.source_id}{suffix}"
        path = self.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        doc.attachment_url = url
        doc.attachment_path = str(rel)
        doc.attachment_sha256 = hashlib.sha256(content).hexdigest()
        doc.attachment_bytes = len(content)
        if suffix == ".pdf":
            doc.text, doc.text_status = extract_text(content)
            if not complete:
                # Broken at the source: keep whatever text could be recovered.
                doc.text_status = "partial" if doc.text else "failed"
        else:
            doc.text_status = "skipped"
        self.session.commit()
        return True

    def fetch_missing_attachments(
        self, isin: str | None = None, limit: int = 200, retry_failed: bool = False
    ) -> int:
        """Download attachments skipped earlier (e.g. after a backfill), and optionally re-download
        ones whose PDF could not be read (often a download that was cut short)."""
        missing = Document.attachment_path.is_(None)
        if retry_failed:
            missing = or_(missing, Document.text_status == "failed")
        query = (
            select(Document, DocumentCompany.isin)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(Document.attachment_url.is_not(None), missing)
            .order_by(Document.published_at.desc())
            .limit(limit)
        )
        if isin:
            query = query.where(DocumentCompany.isin == isin)
        fetched = 0
        for doc, doc_isin in self.session.execute(query).all():
            if self._wants_attachment(doc) and self._fetch_attachment(doc, doc_isin):
                fetched += 1
        return fetched


def reclassify(session: Session) -> int:
    """Re-derive type, title, subject and category from each stored raw record.

    These are derived fields; the raw record is the source of truth and is never changed.
    """
    changed = 0
    for doc in session.scalars(select(Document)):
        parsed = parse_bse({"Table": [doc.raw]}) if doc.source == "bse" else parse_nse([doc.raw])
        if not parsed:
            continue
        ann = parsed[0]
        new = (ann.doc_type, ann.title, ann.subject, ann.category)
        if new != (doc.doc_type, doc.title, doc.subject, doc.category):
            doc.doc_type, doc.title, doc.subject, doc.category = new
            changed += 1
    session.commit()
    return changed


def recent_documents(
    session: Session, isin: str | None = None, doc_type: str | None = None, limit: int = 20
) -> list[tuple[Document, Company]]:
    query = (
        select(Document, Company)
        .join(DocumentCompany, DocumentCompany.document_id == Document.id)
        .join(Company, Company.isin == DocumentCompany.isin)
        .order_by(Document.published_at.desc())
        .limit(limit)
    )
    if isin:
        query = query.where(Company.isin == isin)
    if doc_type:
        query = query.where(Document.doc_type == doc_type)
    return [(d, c) for d, c in session.execute(query).all()]
