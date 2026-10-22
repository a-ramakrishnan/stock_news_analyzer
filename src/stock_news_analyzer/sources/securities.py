"""Master lists of listed securities from NSE and BSE.

- NSE equity list: every NSE-listed equity with symbol, name, series and ISIN.
- Nifty 500 constituents: adds a broad industry for the 500 largest companies.
- BSE scrip list: BSE scrip code (needed to fetch BSE filings) and market cap in Rs crore.
  It has an INDUSTRY field, but BSE leaves it empty; it is read in case that changes.
"""

import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

log = logging.getLogger(__name__)

NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
# Companies on NSE Emerge, the SME platform (not in EQUITY_L.csv); same columns.
NSE_SME_LIST_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
BSE_SCRIPS_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)

# NSE and BSE reject requests that don't look like a browser.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


@dataclass
class NseSecurity:
    symbol: str
    name: str
    series: str
    isin: str
    listed_on: date | None


@dataclass
class BseSecurity:
    code: str
    symbol: str | None
    name: str
    isin: str
    industry: str | None
    market_cap_cr: Decimal | None


def _rows(text: str) -> list[dict[str, str]]:
    """CSV rows with header names upper-cased and stripped (NSE headers have stray spaces).

    Underscores count as spaces, so "NAME_OF_COMPANY" and "NAME OF COMPANY" read the same.
    """
    reader = csv.reader(io.StringIO(text.removeprefix("\ufeff")))
    header = [h.strip().upper().replace("_", " ") for h in next(reader)]
    return [{k: v.strip() for k, v in zip(header, row, strict=False)} for row in reader if any(row)]


def parse_nse_equity_list(text: str) -> list[NseSecurity]:
    out = []
    for row in _rows(text):
        listed = row.get("DATE OF LISTING", "")
        try:
            listed_on = datetime.strptime(listed, "%d-%b-%Y").date() if listed else None
        except ValueError:
            listed_on = None
        out.append(
            NseSecurity(
                symbol=row["SYMBOL"],
                name=row["NAME OF COMPANY"],
                series=row.get("SERIES", ""),
                isin=row["ISIN NUMBER"],
                listed_on=listed_on,
            )
        )
    return out


def parse_nifty500(text: str) -> dict[str, str]:
    """ISIN -> NSE industry for Nifty 500 members."""
    return {row["ISIN CODE"]: row["INDUSTRY"] for row in _rows(text) if row.get("ISIN CODE")}


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "")) if value not in (None, "") else None
    except InvalidOperation:
        return None


def parse_bse_scrips(text: str) -> list[BseSecurity]:
    data = json.loads(text)
    if isinstance(data, dict):  # some responses wrap the list, e.g. {"Table": [...]}
        data = next((v for v in data.values() if isinstance(v, list)), [])
    out = []
    for item in data:
        row = {k.upper(): (v.strip() if isinstance(v, str) else v) for k, v in item.items()}
        isin = row.get("ISIN_NUMBER")
        code = row.get("SCRIP_CD")
        if not isin or not code:
            continue
        out.append(
            BseSecurity(
                code=str(code),
                symbol=row.get("SCRIP_ID") or None,
                name=row.get("ISSUER_NAME") or row.get("SCRIP_NAME") or "",
                isin=isin,
                industry=row.get("INDUSTRY") or None,
                market_cap_cr=_decimal(row.get("MKTCAP")),
            )
        )
    return out


def download(url: str, referer: str | None = None) -> str:
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    log.info("downloading %s", url)
    resp = httpx.get(url, headers=headers, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.text
