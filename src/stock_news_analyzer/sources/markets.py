"""Daily closes of global bullion prices and USD/INR, for the Bullion Analyst.

Two free sources, tried in order: Yahoo Finance's chart API and stooq's CSV download (which
in Oct 2026 answered with a web page instead). Neither needs a key. Indian prices come from
NSE's own bhavcopy (the gold and silver ETFs), already stored by the Price & Label agent.

A daily close is New York's, hours after India's 15:30 IST close, so half of a day's global
move would land on the wrong Indian day. Yahoo's hourly prices (kept for the last two years)
give the price at the Indian close instead: `at_indian_close`.
"""

import csv
import io
import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

log = logging.getLogger(__name__)

# Our name -> (stooq symbol, Yahoo symbol).
SERIES = {
    "XAUUSD": ("xauusd", "GC=F"),  # gold, US$ per troy ounce (Yahoo: COMEX futures)
    "XAGUSD": ("xagusd", "SI=F"),  # silver, US$ per troy ounce
    "USDINR": ("usdinr", "INR=X"),  # rupees per US$
}
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?period1={start}&period2={end}&interval={interval}"
)
INTRADAY_DAYS = 729  # Yahoo keeps hourly prices for the last 730 days
INDIAN_CLOSE_UTC = time(10, 0)  # 15:30 IST


class MarketError(Exception):
    pass


def stooq_url(series: str, start: date, end: date) -> str:
    return STOOQ_URL.format(symbol=SERIES[series][0], start=start, end=end)


def yahoo_url(series: str, start: date, end: date, interval: str = "1d") -> str:
    def ts(d: date) -> int:
        return int(datetime.combine(d, time.min, tzinfo=UTC).timestamp())

    return YAHOO_URL.format(
        symbol=SERIES[series][1].replace("=", "%3D"),
        start=ts(start),
        end=ts(end + timedelta(1)),
        interval=interval,
    )


def parse_stooq(content: bytes) -> list[tuple[date, float]]:
    """stooq's CSV: Date,Open,High,Low,Close[,Volume]. Anything else (a 'No data' page, a
    limit message) is an error."""
    text = content.decode("utf-8", errors="replace").strip()
    if not text.lower().startswith("date,"):
        raise MarketError(f"not a stooq CSV: {text[:80]!r}")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out.append((date.fromisoformat(row["Date"]), float(row["Close"])))
        except (KeyError, ValueError):
            continue
    if not out:
        raise MarketError("stooq returned no rows")
    return out


def _yahoo_bars(content: bytes) -> tuple[int, list[int], list[float | None]]:
    """(gmtoffset, timestamps, closes) from Yahoo's chart JSON."""
    try:
        data = json.loads(content)
        result = data["chart"]["result"][0]
        offset = int(result["meta"].get("gmtoffset") or 0)
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        error = None
        try:
            error = json.loads(content)["chart"]["error"]
        except Exception:
            pass
        raise MarketError(f"not a Yahoo chart: {error or exc}") from exc
    return offset, stamps, closes


def parse_yahoo(content: bytes) -> list[tuple[date, float]]:
    """Yahoo's daily chart: timestamps (UTC) with the exchange's offset, and closes (None on
    days without trading)."""
    offset, stamps, closes = _yahoo_bars(content)
    out = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is not None:
            out[datetime.fromtimestamp(ts + offset, UTC).date()] = float(close)
    if not out:
        raise MarketError("Yahoo returned no closes")
    return sorted(out.items())


def daily_closes(
    fetch: Callable[[str], bytes], series: str, start: date, end: date
) -> tuple[list[tuple[date, float]], str]:
    """(rows, source): from Yahoo, else stooq. Raises MarketError naming both failures."""
    errors = []
    for source, url, parse in (
        ("yahoo", yahoo_url(series, start, end), parse_yahoo),
        ("stooq", stooq_url(series, start, end), parse_stooq),
    ):
        try:
            rows = [(d, c) for d, c in parse(fetch(url)) if start <= d <= end]
        except Exception as exc:  # network errors arrive as the client's own exception
            errors.append(f"{source}: {exc}")
            continue
        if rows:
            return rows, source
        errors.append(f"{source}: no rows from {start} to {end}")
    raise MarketError(f"{series}: " + "; ".join(errors))


def parse_yahoo_at(content: bytes, cutoff: time = INDIAN_CLOSE_UTC) -> list[tuple[date, float]]:
    """From Yahoo's hourly chart, each day's price at `cutoff` (UTC): the close of the last
    hourly bar that ends by then."""
    _, stamps, closes = _yahoo_bars(content)
    out: dict[date, tuple[int, float]] = {}
    for ts, close in zip(stamps, closes, strict=False):
        if close is None:
            continue
        end = datetime.fromtimestamp(ts + 3600, UTC)
        if end.time() > cutoff or end.date() != datetime.fromtimestamp(ts, UTC).date():
            continue
        if end.date() not in out or ts > out[end.date()][0]:
            out[end.date()] = (ts, float(close))
    if not out:
        raise MarketError("Yahoo returned no hourly prices before the Indian close")
    return sorted((d, c) for d, (_, c) in out.items())


def at_indian_close(
    fetch: Callable[[str], bytes], series: str, start: date, end: date
) -> list[tuple[date, float]]:
    """Each day's price at the Indian close (15:30 IST), for the days Yahoo keeps hourly
    prices. Raises MarketError."""
    start = max(start, end - timedelta(days=INTRADAY_DAYS))
    url = yahoo_url(series, start, end, interval="60m")
    try:
        rows = parse_yahoo_at(fetch(url))
    except MarketError:
        raise
    except Exception as exc:
        raise MarketError(f"{series} hourly: {exc}") from exc
    return [(d, c) for d, c in rows if start <= d <= end]
