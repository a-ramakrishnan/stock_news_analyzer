"""NSE end-of-day files: the full bhavcopy (prices, volume, delivery) and index closes.

Formats checked against NSE's live files (Oct 2026). On a market holiday the index file is
missing (404) while the full bhavcopy URL still answers with the previous day's file, so the
trading date is always read from inside the file, never from its name.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from stock_news_analyzer.sources.exchange_http import NSE_ARCHIVES

FULL_BHAVCOPY_URL = NSE_ARCHIVES + "/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
INDEX_CLOSE_URL = NSE_ARCHIVES + "/content/indices/ind_close_all_{d:%d%m%Y}.csv"


@dataclass
class PriceRow:
    symbol: str
    series: str
    trade_date: date
    prev_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    last: Decimal | None
    close: Decimal | None
    avg_price: Decimal | None
    volume: int | None
    turnover_lacs: Decimal | None
    trades: int | None
    delivery_qty: int | None
    delivery_pct: Decimal | None


@dataclass
class IndexRow:
    index_name: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    pe: Decimal | None
    pb: Decimal | None
    div_yield: Decimal | None


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(text.removeprefix("﻿")))
    header = [h.strip().upper() for h in next(reader)]
    return [{k: v.strip() for k, v in zip(header, row, strict=False)} for row in reader if any(row)]


def _dec(value: str | None) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _int(value: str | None) -> int | None:
    d = _dec(value)
    return int(d) if d is not None else None


def parse_full_bhavcopy(text: str) -> list[PriceRow]:
    out = []
    for r in _rows(text):
        try:
            trade_date = datetime.strptime(r["DATE1"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        out.append(
            PriceRow(
                symbol=r["SYMBOL"],
                series=r.get("SERIES", ""),
                trade_date=trade_date,
                prev_close=_dec(r.get("PREV_CLOSE")),
                open=_dec(r.get("OPEN_PRICE")),
                high=_dec(r.get("HIGH_PRICE")),
                low=_dec(r.get("LOW_PRICE")),
                last=_dec(r.get("LAST_PRICE")),
                close=_dec(r.get("CLOSE_PRICE")),
                avg_price=_dec(r.get("AVG_PRICE")),
                volume=_int(r.get("TTL_TRD_QNTY")),
                turnover_lacs=_dec(r.get("TURNOVER_LACS")),
                trades=_int(r.get("NO_OF_TRADES")),
                delivery_qty=_int(r.get("DELIV_QTY")),
                delivery_pct=_dec(r.get("DELIV_PER")),
            )
        )
    return out


def parse_index_close(text: str) -> list[IndexRow]:
    out = []
    for r in _rows(text):
        try:
            trade_date = datetime.strptime(r["INDEX DATE"], "%d-%m-%Y").date()
        except (KeyError, ValueError):
            continue
        out.append(
            IndexRow(
                index_name=r["INDEX NAME"],
                trade_date=trade_date,
                open=_dec(r.get("OPEN INDEX VALUE")),
                high=_dec(r.get("HIGH INDEX VALUE")),
                low=_dec(r.get("LOW INDEX VALUE")),
                close=_dec(r.get("CLOSING INDEX VALUE")),
                pe=_dec(r.get("P/E")),
                pb=_dec(r.get("P/B")),
                div_yield=_dec(r.get("DIV YIELD")),
            )
        )
    return out
