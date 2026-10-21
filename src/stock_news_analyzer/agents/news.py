"""News Collector (agent 3).

Reads business news feeds and a Google News search per company, keeps the articles that
mention a watchlist company, and links each article to the companies it mentions.
"""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.models import Company, Document, DocumentCompany, WatchlistItem
from stock_news_analyzer.sources.news import (
    Article,
    FeedConfig,
    NewsError,
    google_news_url,
    parse_feed,
)

log = logging.getLogger(__name__)

LEGAL_SUFFIX = re.compile(r"\s+(limited|ltd\.?)$", re.IGNORECASE)
# Aliases shorter than this, or written in capitals ("L&T", "KVB"), match case-sensitively.
CASE_INSENSITIVE_MIN = 6


class Client(Protocol):
    def fetch(self, url: str) -> bytes: ...


def default_aliases(company: Company) -> list[str]:
    """Names the press uses without help: the name without 'Limited', and without 'India'."""
    base = LEGAL_SUFFIX.sub("", company.name.strip())
    names = [base]
    if base.lower().endswith(" india"):
        names.append(base[: -len(" india")])
    return names


def _pattern(alias: str) -> re.Pattern:
    """Whole-word pattern; '&' also matches 'and', and any spacing is allowed between words."""
    parts = re.findall(r"&|[^\s&]+", alias.strip())
    escaped = ""
    for i, part in enumerate(parts):
        if i:
            escaped += r"\s*" if "&" in (part, parts[i - 1]) else r"\s+"
        escaped += r"(?:&|and)" if part == "&" else re.escape(part)
    flags = 0
    if len(alias) >= CASE_INSENSITIVE_MIN and not alias.isupper():
        flags = re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", flags)


class CompanyMatcher:
    """Finds which watchlist companies a piece of text mentions."""

    def __init__(
        self, companies: Iterable[tuple[Company, list[str]] | tuple[Company, list[str], list[str]]]
    ):
        self.entries = []
        for company, extra, *rest in companies:
            aliases = default_aliases(company) + [a for a in extra if a.strip()]
            exclude = [_pattern(e) for e in (rest[0] if rest else []) if e.strip()]
            self.entries.append((company, [_pattern(a) for a in aliases], exclude))

    def match(self, text: str) -> list[Company]:
        found = []
        for company, patterns, exclude in self.entries:
            checked = text
            for pattern in exclude:  # "L&T Technology" is not L&T
                checked = pattern.sub(" ", checked)
            if any(p.search(checked) for p in patterns):
                found.append(company)
        return found


def watchlist_matcher(session: Session) -> CompanyMatcher:
    rows = session.execute(
        select(Company, WatchlistItem.aliases, WatchlistItem.exclude).join(
            WatchlistItem, WatchlistItem.isin == Company.isin
        )
    ).all()
    return CompanyMatcher(
        (company, list(aliases or []), list(exclude or [])) for company, aliases, exclude in rows
    )


@dataclass
class FeedReport:
    key: str
    items: int = 0
    error: str | None = None


@dataclass
class NewsResult:
    new: int = 0
    matched: int = 0  # articles that mention a watchlist company (new or already stored)
    seen: int = 0
    feeds: list[FeedReport] = field(default_factory=list)

    @property
    def errors(self) -> list[FeedReport]:
        return [f for f in self.feeds if f.error]


class NewsCollector:
    def __init__(self, session: Session, client: Client, config: FeedConfig):
        self.session = session
        self.client = client
        self.config = config

    def collect(
        self,
        feed_keys: list[str] | None = None,
        google: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> NewsResult:
        """Read every feed (and Google News per company). `progress` gets one line per feed."""
        self.progress = progress
        matcher = watchlist_matcher(self.session)
        result = NewsResult()
        for feed in self.config.feeds:
            if feed_keys and feed.key not in feed_keys:
                continue
            self._read(f"news:{feed.key}", feed.key, feed.url, feed.name, matcher, result)

        if google and self.config.google_news and not feed_keys:
            for company, *_ in matcher.entries:
                query = f'"{default_aliases(company)[0]}"'
                url = google_news_url(query, self.config.google_days)
                key = f"google:{company.nse_symbol or company.isin}"
                self._read("news:google", key, url, "Google News", matcher, result)
        return result

    def _read(self, source, key, url, publisher, matcher, result: NewsResult) -> None:
        report = FeedReport(key=key)
        result.feeds.append(report)
        try:
            articles = parse_feed(self.client.fetch(url), source, publisher)
        except NewsError as exc:
            report.error = str(exc)
            log.warning("%s: %s", key, exc)
            self._report(f"{key}: FAILED {exc}")
            return
        report.items = len(articles)
        matched = new = 0
        for article in articles:
            result.seen += 1
            companies = matcher.match(f"{article.title}\n{article.summary}")
            if not companies:
                continue
            matched += 1
            if self._store(article, companies):
                new += 1
        result.matched += matched
        result.new += new
        self._report(f"{key}: {len(articles)} read, {matched} about your stocks, {new} new")

    def _report(self, line: str) -> None:
        log.debug(line)
        if getattr(self, "progress", None):
            self.progress(line)

    def _store(self, article: Article, companies: list[Company]) -> bool:
        """Store the article (once) and link it to the companies. True if it was new."""
        doc_id = self.session.scalar(
            insert(Document)
            .values(
                source=article.source,
                source_id=article.source_id,
                doc_type="news",
                title=article.title,
                published_at=article.published_at,
                url=article.url,
                publisher=article.publisher,
                text=article.summary,
                text_status="ok" if article.summary else "empty",
                raw=article.raw,
            )
            .on_conflict_do_nothing(constraint="documents_source_id")
            .returning(Document.id)
        )
        is_new = doc_id is not None
        if not is_new:
            doc_id = self.session.scalar(
                select(Document.id).where(
                    Document.source == article.source, Document.source_id == article.source_id
                )
            )
        for company in companies:
            self.session.execute(
                insert(DocumentCompany)
                .values(document_id=doc_id, isin=company.isin)
                .on_conflict_do_nothing()
            )
        self.session.commit()
        return is_new


def relink(session: Session) -> tuple[int, int]:
    """Re-match every stored news article to the watchlist with the current names, aliases and
    exclusions. Returns (links added, links removed). Articles themselves are never deleted."""
    matcher = watchlist_matcher(session)
    watched = {c.isin for c, *_ in matcher.entries}
    added = removed = 0
    for doc in session.scalars(select(Document).where(Document.doc_type == "news")):
        wanted = {c.isin for c in matcher.match(f"{doc.title}\n{doc.text or ''}")}
        current = set(
            session.scalars(
                select(DocumentCompany.isin).where(DocumentCompany.document_id == doc.id)
            )
        )
        for isin in (current & watched) - wanted:
            session.execute(
                delete(DocumentCompany).where(
                    DocumentCompany.document_id == doc.id, DocumentCompany.isin == isin
                )
            )
            removed += 1
        for isin in wanted - current:
            session.add(DocumentCompany(document_id=doc.id, isin=isin))
            added += 1
    session.commit()
    return added, removed


def check_feeds(client: Client, config: FeedConfig) -> list[tuple[str, str, int, str | None]]:
    """Fetch every configured feed once: (key, url, items, error)."""
    out = []
    for feed in config.feeds:
        try:
            items = len(parse_feed(client.fetch(feed.url), f"news:{feed.key}", feed.name))
            out.append((feed.key, feed.url, items, None))
        except NewsError as exc:
            out.append((feed.key, feed.url, 0, str(exc)))
    return out
