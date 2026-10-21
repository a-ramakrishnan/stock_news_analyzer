"""News from RSS/Atom feeds and Google News search."""

import calendar
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import yaml
from curl_cffi import requests as creq

from stock_news_analyzer.text import clean

log = logging.getLogger(__name__)

GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


class NewsError(Exception):
    pass


@dataclass
class Feed:
    key: str
    name: str
    url: str


@dataclass
class FeedConfig:
    feeds: list[Feed]
    google_news: bool = True
    google_days: int = 7


@dataclass
class Article:
    source: str  # 'news:<feed key>' or 'news:google'
    source_id: str  # feed guid, or a hash of the link
    title: str
    summary: str
    url: str
    publisher: str
    published_at: datetime
    raw: dict = field(default_factory=dict)


def load_feed_config(path: Path) -> FeedConfig:
    data = yaml.safe_load(path.read_text()) or {}
    google = data.get("google_news") or {}
    return FeedConfig(
        feeds=[Feed(key=f["key"], name=f["name"], url=f["url"]) for f in data.get("feeds") or []],
        google_news=bool(google.get("enabled", True)),
        google_days=int(google.get("days", 7)),
    )


def google_news_url(query: str, days: int) -> str:
    return GOOGLE_NEWS_URL.format(q=quote_plus(f"{query} when:{days}d"))


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)


def repair_xml(content: bytes) -> bytes:
    """Fix the two mistakes that most often make a feed unreadable: control characters and
    bare '&' (e.g. "M&M" written without escaping). Seen in the Financial Express feed."""
    content = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", content)
    return re.sub(rb"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]*;)", b"&amp;", content)


def parse_feed(content: bytes, source: str, publisher: str) -> list[Article]:
    """Parse RSS or Atom. Items without a link or title are skipped."""
    parsed = feedparser.parse(content)
    if parsed.bozo:
        # feedparser's lenient fallback garbles text ("L&T" becomes "L&T;"), so prefer the
        # repaired document whenever it parses at least as well.
        repaired = feedparser.parse(repair_xml(content))
        if repaired.entries and (not repaired.bozo or len(repaired.entries) >= len(parsed.entries)):
            parsed = repaired
    if not parsed.entries and (not parsed.get("version") or parsed.bozo):
        # e.g. an "Access Denied" web page served with HTTP 200
        reason = parsed.get("bozo_exception") or "no RSS/Atom content"
        raise NewsError(f"not a readable feed: {reason}")
    out = []
    now = datetime.now(UTC)
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = clean(entry.get("title"))
        if not link or not title:
            continue
        # Google News titles end in " - <Publisher>"; the publisher is also given separately.
        item_publisher = clean((entry.get("source") or {}).get("title")) or publisher
        if source == "news:google" and title.endswith(f" - {item_publisher}"):
            title = title[: -len(f" - {item_publisher}")]
        published = _published(entry)
        guid = (entry.get("id") or link).strip()
        out.append(
            Article(
                source=source,
                source_id=hashlib.sha1(guid.encode()).hexdigest(),
                title=title,
                summary=clean(entry.get("summary")),
                url=link,
                publisher=item_publisher,
                # Feeds without dates get the time we saw them; flagged in raw.
                published_at=published or now,
                raw={
                    "id": guid,
                    "link": link,
                    "title": entry.get("title"),
                    "summary": entry.get("summary"),
                    "published": entry.get("published") or entry.get("updated"),
                    "publisher": item_publisher,
                    "date_missing": published is None,
                },
            )
        )
    return out


class NewsClient:
    """Fetches feeds with a browser-like client, one request per `delay` seconds."""

    def __init__(self, delay: float = 1.0, timeout: float = 30):
        self.delay = delay
        self.timeout = timeout
        self._session = creq.Session(impersonate="chrome")
        self._last = 0.0

    def fetch(self, url: str) -> bytes:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except Exception as exc:  # network errors from curl_cffi
            raise NewsError(f"{type(exc).__name__}: {exc}") from exc
        if resp.status_code != 200:
            raise NewsError(f"HTTP {resp.status_code}")
        return resp.content
