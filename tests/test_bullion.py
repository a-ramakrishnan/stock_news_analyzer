import json
import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_concalls import _llm
from test_llm import usage
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import bullion as bu
from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import BullionMove, Document, MarketSeries, PriceDaily
from stock_news_analyzer.sources import markets
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.news import NewsError
from stock_news_analyzer.ui import queries

STOOQ = (
    b"Date,Open,High,Low,Close\n"
    b"2026-10-22,2400,2420,2390,2410.5\n"
    b"2026-10-23,2410,2450,2405,2441.25\n"
)


def yahoo(closes, offset=-14400):
    stamps = [int(datetime(2026, 10, 22 + i, 4, 0, tzinfo=UTC).timestamp()) for i in range(3)]
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"gmtoffset": offset},
                        "timestamp": stamps,
                        "indicators": {"quote": [{"close": closes}]},
                    }
                ],
                "error": None,
            }
        }
    ).encode()


# --- sources ---------------------------------------------------------------------------


def test_parse_stooq_and_yahoo():
    assert markets.parse_stooq(STOOQ) == [
        (date(2026, 10, 22), 2410.5),
        (date(2026, 10, 23), 2441.25),
    ]
    with pytest.raises(markets.MarketError, match="not a stooq CSV"):
        markets.parse_stooq(b"No data")
    # Yahoo: 04:00 UTC minus 4 hours is the previous day in New York; a None close is skipped.
    rows = markets.parse_yahoo(yahoo([2400.0, None, 2450.0]))
    assert rows == [(date(2026, 10, 22), 2400.0), (date(2026, 10, 24), 2450.0)]
    error = json.dumps({"chart": {"result": None, "error": {"code": "Not Found"}}}).encode()
    with pytest.raises(markets.MarketError, match="Not Found"):
        markets.parse_yahoo(error)


def test_falls_back_to_yahoo():
    def fetch(url):
        if "stooq" in url:
            raise NewsError("HTTP 403")
        return yahoo([84.1, 84.2, 84.3], offset=3600)

    rows, source = markets.daily_closes(fetch, "USDINR", date(2026, 10, 1), date(2026, 10, 31))
    assert source == "yahoo" and len(rows) == 3
    assert "INR%3DX" in markets.yahoo_url("USDINR", date(2026, 10, 1), date(2026, 10, 2))

    def broken(url):
        raise NewsError("HTTP 403")

    with pytest.raises(markets.MarketError, match="stooq: HTTP 403; yahoo: HTTP 403"):
        markets.daily_closes(broken, "XAUUSD", date(2026, 10, 1), date(2026, 10, 31))


def test_driver_from_split():
    assert bu.driver_from_split(0.03, 0.028, 0.001, 0.001) == "global_price"
    assert bu.driver_from_split(0.01, 0.002, 0.008, 0.0) == "rupee"
    assert bu.driver_from_split(0.01, -0.005, 0.0, 0.015) == "local"
    assert bu.driver_from_split(0.01, 0.005, 0.005, 0.0) == "mixed"
    assert bu.driver_from_split(0.01, None, 0.005, None) is None


# --- moves -----------------------------------------------------------------------------

START = date(2026, 9, 1)


def weekdays(n):
    out, d = [], START
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = weekdays(30)


def gold_price(i):
    """Global gold: wobbling ±0.2% a day, then up 3% on the last day."""
    base = 2400 * (1 + 0.002 * (-1) ** i)
    return base * (1.03 if i == len(DAYS) - 1 else 1)


def csv_for(series):
    rows = ["Date,Open,High,Low,Close"]
    for i, d in enumerate(DAYS):
        close = gold_price(i) if series == "xauusd" else 84.0
        rows.append(f"{d},{close},{close},{close},{close}")
    return "\n".join(rows).encode()


def fake_fetch(url):
    if "stooq.com" in url:
        return csv_for(url.split("s=")[1].split("&")[0])
    if "news.google.com" in url:
        return b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    raise NewsError("HTTP 404")


@pytest.fixture
def gold(loaded):  # noqa: F811
    """Gold on the watchlist, and GOLDBEES closes that follow the global price exactly."""
    wl.add_commodity(loaded, "gold", owned=True)
    prev = None
    for i, d in enumerate(DAYS):
        close = round(60 * gold_price(i) / 2400, 4)
        loaded.add(
            PriceDaily(symbol="GOLDBEES", series="EQ", trade_date=d, close=close, prev_close=prev)
        )
        prev = close
    loaded.commit()
    return loaded


@pytest.mark.db
def test_each_day_split_into_global_rupee_and_other(gold):
    result = bu.run(gold, None, fake_fetch, today=DAYS[-1], notes=False)
    assert result.errors == [] and result.series == {"XAUUSD": "stooq", "USDINR": "stooq"}
    assert gold.query(MarketSeries).count() == 60
    assert result.days == 29 and result.unusual == 1
    last = gold.get(BullionMove, ("GOLD", DAYS[-1]))
    assert last.unusual and last.driver == "global_price" and last.zscore > 2
    assert last.inr_return == pytest.approx(math.log(1.03 * 0.998 / 1.002), abs=1e-4)
    assert last.global_return == pytest.approx(last.inr_return, abs=1e-4)
    assert last.fx_return == 0 and abs(last.other_return) < 1e-4
    assert "global +" in bu.summary(last) and "rupee +0.00%" in bu.summary(last)
    df = queries.bullion(gold, "GOLD", days=3650)
    assert len(df) == 29 and df.iloc[0]["driver"] == "global price"


@pytest.mark.db
def test_a_note_for_an_unusual_day(gold):
    bu.run(gold, None, fake_fetch, today=DAYS[-1], notes=False)
    article = Document(
        source="news:bullion",
        source_id="a1",
        doc_type="bullion_news",
        title="Gold jumps 3% as Fed signals cuts",
        published_at=datetime.combine(DAYS[-1], datetime.min.time(), IST) + timedelta(hours=20),
        text="Gold prices rose after the Fed chair hinted at rate cuts.",
        text_status="ok",
        raw={"metal": "GOLD"},
    )
    gold.add(article)
    gold.commit()
    note = bu.BullionNote(
        driver="global_price",
        note="Almost all of the 3% rise came from the global price, after the Fed hinted at cuts.",
        evidence=[article.id, 999999],
    )

    def reply(kwargs):
        assert f'<article id="{article.id}"' in kwargs["messages"][0]["content"]
        return SimpleNamespace(usage=usage(2000, 200), parsed_output=note, stop_reason="end_turn")

    llm, client = _llm(gold, reply)
    result = bu.run(gold, llm, fake_fetch, today=DAYS[-1])
    assert result.notes == 1 and client.requests[0]["model"] == "claude-sonnet-5-5"
    last = gold.get(BullionMove, ("GOLD", DAYS[-1]))
    assert last.note.startswith("Almost all") and last.evidence == [article.id]
    # A later run recomputes the split but keeps the note and its driver.
    bu.compute_moves(gold, "GOLD")
    gold.refresh(last)
    assert last.note.startswith("Almost all") and last.driver == "global_price"
    since = datetime.now(IST) - timedelta(hours=1)
    md = dg.build_digest(gold, since, datetime.now(IST) + timedelta(minutes=1)).markdown
    assert "## Bullion" in md and f"- Gold {DAYS[-1]:%d %b}: +" in md
    assert "**(unusual)**" in md and "Almost all of the 3% rise" in md


@pytest.mark.db
def test_nothing_to_do_without_bullion_on_the_watchlist(loaded):  # noqa: F811
    result = bu.run(loaded, None, fake_fetch)
    assert (result.days, result.points, result.errors) == (0, 0, [])
