"""NSE bulk and block deals.

Bulk deal: one client trading more than 0.5% of a company's shares in a day. Block deal: a
trade of at least Rs 10 crore in the separate block window. NSE publishes both daily, as JSON
(the historical API) and as CSV downloads; the column names differ between the two and over
time, so columns are found by the words in their names.
"""

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

KINDS = ("bulk", "block")

# For each field, words that appear in its column name (after lower-casing and dropping
# everything but letters and digits), tried in order. "BD_CLIENT_NAME" -> "bdclientname".
COLUMNS = {
    "date": ("date",),
    "symbol": ("symbol",),
    "name": ("scripname", "securityname", "secname", "name"),
    "client": ("client",),
    "side": ("buysell", "buy", "side"),
    "quantity": ("qty", "quantity"),
    "price": ("watp", "price"),
    "remarks": ("remark",),
}
DATE_FORMATS = ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y")


@dataclass
class Deal:
    kind: str  # 'bulk' or 'block'
    trade_date: date
    symbol: str
    security_name: str | None
    client: str
    side: str  # 'BUY' or 'SELL'
    quantity: int
    price: Decimal | None
    remarks: str | None


class DealsFormatError(ValueError):
    """The response has no recognisable deal columns."""


def _norm(key: str) -> str:
    return "".join(c for c in key.lower() if c.isalnum())


def _columns(keys) -> dict[str, str]:
    normalised = {_norm(k): k for k in keys}
    found = {}
    for field_name, words in COLUMNS.items():
        for word in words:
            match = next(
                (
                    orig
                    for norm, orig in normalised.items()
                    if word in norm
                    and orig not in found.values()
                    and not (field_name == "name" and "client" in norm)  # "client name"
                ),
                None,
            )
            if match:
                found[field_name] = match
                break
    return found


def _date(text: str) -> date | None:
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.title() if "%b" in fmt else text, fmt).date()
        except ValueError:
            continue
    return None


def _number(text) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _text(value) -> str:
    """A cell as text; JSON nulls are empty, not the word 'None'."""
    return "" if value is None else str(value).strip()


def records(content: bytes | str) -> list[dict]:
    """Rows of a JSON response ({"data": [...]} or a list) or of a CSV file."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        data = json.loads(stripped)
        rows = data if isinstance(data, list) else data.get("data", [])
        return [r for r in rows if isinstance(r, dict)]
    reader = csv.DictReader(io.StringIO(text.removeprefix("﻿")))
    return [r for r in reader if any((v or "").strip() for v in r.values())]


def parse_deals(content: bytes | str, kind: str) -> list[Deal]:
    rows = records(content)
    if not rows:
        return []
    cols = _columns(rows[0].keys())
    missing = {"date", "symbol", "client", "side", "quantity"} - cols.keys()
    if missing:
        raise DealsFormatError(
            f"{kind} deals: no column for {', '.join(sorted(missing))} in {list(rows[0])}"
        )
    deals = []
    for row in rows:
        day = _date(str(row.get(cols["date"], "")))
        quantity = _number(row.get(cols["quantity"]))
        side = str(row.get(cols["side"], "")).strip().upper()
        symbol = str(row.get(cols["symbol"], "")).strip().upper()
        if not day or not symbol or quantity is None or side not in ("BUY", "SELL"):
            continue
        name = _text(row.get(cols["name"])) if "name" in cols else None
        remarks = _text(row.get(cols["remarks"])) if "remarks" in cols else None
        deals.append(
            Deal(
                kind=kind,
                trade_date=day,
                symbol=symbol,
                security_name=name or None,
                client=" ".join(str(row.get(cols["client"], "")).split()),
                side=side,
                quantity=int(quantity),
                price=_number(row.get(cols["price"])) if "price" in cols else None,
                remarks=None if remarks in (None, "", "-") else remarks,
            )
        )
    return deals
