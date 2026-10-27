from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import FIXTURES

from stock_news_analyzer.agents import news as nw
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import Company, Document, DocumentCompany, WatchlistItem
from stock_news_analyzer.sources.news import (
    Article,
    Feed,
    FeedConfig,
    NewsError,
    google_news_range_url,
    google_news_url,
    load_feed_config,
    parse_feed,
)
from stock_news_analyzer.sources.securities import parse_bse_scrips, parse_nse_equity_list

REPO = Path(__file__).parent.parent


def _company(name):
    return Company(isin="X", name=name)


# --- parsing -----------------------------------------------------------------


def test_parse_rss_feed():
    articles = parse_feed((FIXTURES / "rss_et_stocks.xml").read_bytes(), "news:et", "ET")
    first = articles[0]
    assert first.title == "L&T bags 'large' orders for projects in New Delhi and Andhra Pradesh"
    assert first.summary.startswith("Larsen & Toubro said its construction arm")  # HTML gone
    assert first.published_at == datetime(2026, 10, 21, 4, 45, tzinfo=UTC)  # 10:15 IST
    assert first.publisher == "ET" and len(first.source_id) == 40
    undated = articles[3]
    assert undated.raw["date_missing"] is True


def test_parse_google_news_strips_publisher_from_title():
    [article] = parse_feed(
        (FIXTURES / "rss_google_news.xml").read_bytes(), "news:google", "Google News"
    )
    assert article.title == "Motherson Sumi Wiring India Q2 profit rises 12%"
    assert article.publisher == "Business Standard"


def test_parse_feed_repairs_bare_ampersands_and_control_characters():
    content = (FIXTURES / "rss_malformed.xml").read_bytes()
    assert b"L&T, M&M" in content and b"\x0b" in content
    [article] = parse_feed(content, "news:fe_market", "Financial Express")
    assert article.title == "L&T, M&M and Karur Vysya Bank lead gains & volumes rise"


def test_parse_feed_rejects_non_feeds():
    with pytest.raises(NewsError):
        parse_feed(b"<html><body>Access Denied</body></html>", "news:x", "X")


def test_google_news_url():
    url = google_news_url('"Karur Vysya Bank"', 7)
    assert url.startswith("https://news.google.com/rss/search?q=%22Karur+Vysya+Bank%22+when%3A7d")


def test_repo_feed_config_loads():
    config = load_feed_config(REPO / "config" / "news_feeds.yaml")
    assert len(config.feeds) >= 5 and config.google_news
    assert len({f.key for f in config.feeds}) == len(config.feeds)


# --- matching ----------------------------------------------------------------


def test_default_aliases():
    assert nw.default_aliases(_company("Larsen & Toubro Limited")) == ["Larsen & Toubro"]
    assert nw.default_aliases(_company("Motherson Sumi Wiring India Limited")) == [
        "Motherson Sumi Wiring India",
        "Motherson Sumi Wiring",
    ]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Larsen and Toubro bags order", ["LT"]),
        ("L&T wins big", ["LT"]),
        ("l&t wins", []),  # short alias is case-sensitive
        ("KVB Q2 profit up", ["KARURVYSYA"]),
        ("karur vysya bank results", ["KARURVYSYA"]),
        ("Samvardhana Motherson International rallies", []),
        ("L&T and Karur Vysya Bank among gainers", ["LT", "KARURVYSYA"]),
    ],
)
def test_matcher(text, expected):
    lt = Company(isin="A", name="Larsen & Toubro Limited", nse_symbol="LT")
    kvb = Company(isin="B", name="Karur Vysya Bank Limited", nse_symbol="KARURVYSYA")
    msumi = Company(isin="C", name="Motherson Sumi Wiring India Limited", nse_symbol="MSUMI")
    matcher = nw.CompanyMatcher([(lt, ["L&T"]), (kvb, ["KVB"]), (msumi, ["MSWIL"])])
    assert [c.nse_symbol for c in matcher.match(text)] == expected


# --- collecting ----------------------------------------------------------------


EMPTY_FEED = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'


class FakeClient:
    def __init__(self, failing=()):
        self.failing = failing
        self.urls = []

    def fetch(self, url):
        self.urls.append(url)
        if any(f in url for f in self.failing):
            raise NewsError("HTTP 403")
        if "news.google.com" in url:
            if "Motherson" in url:
                return (FIXTURES / "rss_google_news.xml").read_bytes()
            return EMPTY_FEED
        return (FIXTURES / "rss_et_stocks.xml").read_bytes()


CONFIG = FeedConfig(
    feeds=[
        Feed("et_stocks", "Economic Times - Stocks", "https://et.example/stocks.rss"),
        Feed("broken", "Broken feed", "https://broken.example/feed"),
    ]
)


@pytest.fixture
def watchlist(session):
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        bse=parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    wl.load_file(session, FIXTURES / "watchlist.yaml")
    return session


@pytest.mark.db
def test_watchlist_file_aliases_are_loaded(watchlist):
    items = {i.display_name: i for i in watchlist.query(WatchlistItem)}
    assert items["Larsen & Toubro Limited"].aliases == ["L&T"]
    assert "L&T Technology" in items["Larsen & Toubro Limited"].exclude


@pytest.mark.db
def test_collect_stores_matching_articles_and_links_companies(watchlist):
    client = FakeClient(failing=("broken",))
    result = nw.NewsCollector(watchlist, client, CONFIG).collect()

    # 4 ET items: 3 mention watchlist companies. Google: 1 article (Motherson), 2 empty searches.
    assert (result.seen, result.matched, result.new) == (5, 4, 4)
    assert [r.key for r in result.errors] == ["broken"]
    assert sum(1 for u in client.urls if "news.google.com" in u) == 3

    links = {
        d.title[:20]: sorted(
            isin for (isin,) in watchlist.query(DocumentCompany.isin).filter_by(document_id=d.id)
        )
        for d in watchlist.query(Document)
    }
    assert links["Larsen and Toubro, K"] == ["INE018A01030", "INE036D01028"]  # two companies
    google = watchlist.query(Document).filter_by(source="news:google").one()
    assert google.publisher == "Business Standard" and google.doc_type == "news"
    assert google.url.startswith("https://news.google.com/rss/articles/")


@pytest.mark.db
def test_collect_twice_stores_nothing_new(watchlist):
    collector = nw.NewsCollector(watchlist, FakeClient(failing=("broken",)), CONFIG)
    collector.collect(google=False)
    result = collector.collect(google=False)
    assert result.new == 0 and result.matched == 3
    assert watchlist.query(Document).count() == 3


@pytest.mark.db
def test_check_feeds_reports_each_feed():
    report = nw.check_feeds(FakeClient(failing=("broken",)), CONFIG)
    assert report[0][0] == "et_stocks" and report[0][2] == 4 and report[0][3] is None
    assert report[1][0] == "broken" and report[1][3] == "HTTP 403"


@pytest.mark.db
def test_cli_news_list(watchlist, test_database_url, monkeypatch):
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app

    nw.NewsCollector(watchlist, FakeClient(), CONFIG).collect(google=False)
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    result = CliRunner().invoke(app, ["news", "list", "KARURVYSYA"])
    assert result.exit_code == 0, result.stdout
    assert "KARURVYSYA" in result.stdout and "KVB and City Union Bank rally" in result.stdout


@pytest.mark.parametrize(
    "text, expected",
    [
        # Headlines from the first live run (21 Oct 2026).
        ("Why L&T Technology shares jumped 11% to hit the Rs 4,000 level after Q2 results", []),
        ("IT stocks on fire, rally up to 15% today; check performance of TCS, L&T Technology", []),
        ("L&T wins large orders for Central Secretariat, Amaravati office towers", ["LT"]),
        ("L&T and L&T Finance shares rise", ["LT"]),  # L&T itself is still mentioned
        ("LTIMindtree, LTTS lead IT gains", []),
    ],
)
def test_matcher_exclusions(text, expected):
    lt = Company(isin="A", name="Larsen & Toubro Limited", nse_symbol="LT")
    exclude = ["L&T Technology", "L&T Tech", "L&T Finance", "LTIMindtree", "LTTS"]
    matcher = nw.CompanyMatcher([(lt, ["L&T"], exclude)])
    assert [c.nse_symbol for c in matcher.match(text)] == expected


@pytest.mark.db
def test_relink_removes_links_that_no_longer_match(watchlist):
    item = watchlist.query(WatchlistItem).filter_by(display_name="Larsen & Toubro Limited").one()
    item.exclude = []
    watchlist.commit()
    lt_tech = Article(
        source="news:mint_markets",
        source_id="a" * 40,
        title="Why L&T Technology shares jumped 11%",
        summary="",
        url="https://example.com/ltts",
        publisher="Mint",
        published_at=datetime(2026, 10, 21, 4, 22, tzinfo=UTC),
    )
    collector = nw.NewsCollector(watchlist, FakeClient(), CONFIG)
    collector._store(lt_tech, nw.watchlist_matcher(watchlist).match(lt_tech.title))
    assert watchlist.query(DocumentCompany).count() == 1

    wl.load_file(watchlist, FIXTURES / "watchlist.yaml")  # brings the exclusions back
    assert nw.relink(watchlist) == (0, 1)
    assert watchlist.query(DocumentCompany).count() == 0
    assert watchlist.query(Document).count() == 1  # the article itself is kept
    assert nw.relink(watchlist) == (0, 0)


@pytest.mark.db
def test_progress_line_per_feed(watchlist):
    lines = []
    nw.NewsCollector(watchlist, FakeClient(failing=("broken",)), CONFIG).collect(
        google=False, progress=lines.append
    )
    assert lines == [
        "et_stocks: 4 read, 3 about your stocks, 3 new",
        "broken: FAILED HTTP 403",
    ]


# --- history from Google News --------------------------------------------------


def test_google_news_range_url_includes_the_last_day():
    url = google_news_range_url('"Karur Vysya Bank"', date(2023, 10, 1), date(2023, 10, 30))
    assert parse_qs(urlparse(url).query)["q"] == [
        '"Karur Vysya Bank" after:2023-10-01 before:2023-10-31'
    ]


def test_month_windows_cover_the_range_without_gaps():
    windows = list(nw.month_windows(date(2023, 10, 1), date(2024, 1, 15)))
    assert windows[0] == (date(2023, 10, 1), date(2023, 10, 30))
    assert windows[-1][1] == date(2024, 1, 15)
    for (_, hi), (lo, _) in zip(windows, windows[1:], strict=False):
        assert (lo - hi).days == 1


def _query(url):
    return parse_qs(urlparse(url).query)["q"][0]


class HistoryClient:
    """Google News with one Motherson article; a full page (100 items) for 1-30 Oct 2023."""

    def __init__(self):
        self.queries = []

    def fetch(self, url):
        q = _query(url)
        self.queries.append(q)
        if "after:2023-10-01 before:2023-10-31" in q:
            item = (FIXTURES / "rss_google_news.xml").read_text()
            head, rest = item.split("<item>", 1)
            body, tail = rest.split("</item>", 1)
            items = "".join(
                f"<item>{body.replace('CBMiSGh0', f'CBMi{i:03d}')}</item>" for i in range(100)
            )
            return f"{head}{items}{tail}".encode()
        if "Motherson" in q:
            return (FIXTURES / "rss_google_news.xml").read_bytes()
        return EMPTY_FEED


@pytest.mark.db
def test_backfill_searches_each_month_and_splits_full_windows(watchlist):
    client = HistoryClient()
    lines = []
    result = nw.NewsCollector(watchlist, client, CONFIG).backfill(
        date(2023, 10, 1), date(2023, 11, 29), symbol="MSUMI", progress=lines.append
    )
    # Two monthly windows; the first returned 100 items, so it was searched again in halves.
    assert [q.split('" ', 1)[1] for q in client.queries] == [
        "after:2023-10-01 before:2023-10-31",
        "after:2023-10-01 before:2023-10-16",
        "after:2023-10-16 before:2023-10-31",
        "after:2023-10-31 before:2023-11-30",
    ]
    assert all(q.startswith('"Motherson Sumi Wiring India"') for q in client.queries)
    # 100 distinct articles from the full page, plus the fixture article found in the halves
    # and again in November (stored once).
    assert result.new == 101 and not result.errors
    assert lines[0].startswith("google:MSUMI 01 Oct 2023-30 Oct 2023: 100 read")


@pytest.mark.db
def test_backfill_all_companies_and_reruns_store_nothing_new(watchlist):
    client = HistoryClient()
    collector = nw.NewsCollector(watchlist, client, CONFIG)
    collector.backfill(date(2023, 11, 1), date(2023, 11, 30))
    assert len(client.queries) == 3  # one month, three companies
    again = collector.backfill(date(2023, 11, 1), date(2023, 11, 30))
    assert again.new == 0 and again.matched == 1


def test_a_feed_refusing_the_browser_client_is_tried_with_a_plain_one():
    from stock_news_analyzer.sources.news import NewsClient, NewsError

    class Session:
        def __init__(self, status, body=b"<rss/>"):
            self.status, self.body, self.calls = status, body, 0

        def get(self, url, timeout=None):
            self.calls += 1
            return SimpleNamespace(status_code=self.status, content=self.body)

    # Google News answered the Chrome imitation with 503 and a plain client with 200 (Oct 2026).
    client = NewsClient(delay=0)
    client._session, client._plain = Session(503), Session(200, b"<rss>ok</rss>")
    assert client.fetch("https://news.google.com/rss/search?q=x") == b"<rss>ok</rss>"
    # A feed the browser client reads is not fetched twice.
    client._session, client._plain = Session(200, b"<rss>1</rss>"), Session(200)
    assert client.fetch("https://example.com/feed") == b"<rss>1</rss>"
    assert client._plain.calls == 0
    client._session, client._plain = Session(503), Session(503)
    with pytest.raises(NewsError, match="HTTP 503"):
        client.fetch("https://news.google.com/rss/search?q=x")
