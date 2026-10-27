"""Daily closes of global bullion prices and USD/INR, for the Bullion Analyst.

Two free sources, tried in order: stooq's CSV download and Yahoo Finance's chart API. Neither
needs a key. Indian prices come from NSE's own bhavcopy (the gold and silver ETFs), already
stored by the Price & Label agent.
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
    "?period1={start}&period2={end}&interval=1d"
)


class MarketError(Exception):
    pass


def stooq_url(series: str, start: date, end: date) -> str:
    return STOOQ_URL.format(symbol=SERIES[series][0], start=start, end=end)


def yahoo_url(series: str, start: date, end: date) -> str:
    def ts(d: date) -> int:
        return int(datetime.combine(d, time.min, tzinfo=UTC).timestamp())

    return YAHOO_URL.format(
        symbol=SERIES[series][1].replace("=", "%3D"), start=ts(start), end=ts(end + timedelta(1))
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


def parse_yahoo(content: bytes) -> list[tuple[date, float]]:
    """Yahoo's chart JSON: timestamps (UTC) with the exchange's offset, and closes (None on
    days without trading)."""
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
    """(rows, source): from stooq, else Yahoo. Raises MarketError naming both failures."""
    errors = []
    for source, url, parse in (
        ("stooq", stooq_url(series, start, end), parse_stooq),
        ("yahoo", yahoo_url(series, start, end), parse_yahoo),
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
