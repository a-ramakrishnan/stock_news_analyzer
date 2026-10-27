"""HTTP access to BSE and NSE websites.

Both exchanges sit behind bot protection (Akamai) that rejects ordinary HTTP clients on their
announcement APIs. `curl_cffi` presents the same TLS fingerprint as Chrome, which gets through.
Each session first loads an exchange web page to pick up cookies, as a browser would.
"""

import logging
import time
from datetime import date

from curl_cffi import requests as creq

log = logging.getLogger(__name__)

BSE_WARMUP_URL = "https://www.bseindia.com/corporates/ann.html"
BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACHMENT_URLS = (
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}",  # older filings
)
BSE_HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}

NSE_WARMUP_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
NSE_ARCHIVES = "https://nsearchives.nseindia.com"
NSE_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_CORPORATE_ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions"
# The list behind NSE's "Financial Results" page: one row per results filing, with links to
# the PDF and to the XBRL file (the same figures, tagged).
NSE_FINANCIAL_RESULTS_URL = "https://www.nseindia.com/api/corporates-financial-results"
NSE_INTEGRATED_URL = "https://www.nseindia.com/api/integrated-filing-results"
# The API behind NSE's "Bulk & block deals" report; it answers only after that page is opened.
NSE_DEALS_URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
NSE_DEALS_PAGE = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"


# NSE series of SME (Emerge) companies. NSE serves their announcements, corporate actions and
# results under index=sme; asked under index=equities it answers with nothing.
SME_SERIES = {"SM", "ST", "SZ"}


class ExchangeError(Exception):
    pass


class ExchangeClient:
    """Fetches announcement listings and attachments. Waits `delay` seconds between requests."""

    def __init__(self, delay: float = 1.0, timeout: float = 60):
        self.delay = delay
        self.timeout = timeout
        self._sessions: dict[str, creq.Session] = {}
        self._last_request = 0.0
        self._deals_page_opened_in = None  # the NSE session that has opened the deals page

    def _session(self, exchange: str) -> creq.Session:
        if exchange not in self._sessions:
            s = creq.Session(impersonate="chrome")
            self._get(s, BSE_WARMUP_URL if exchange == "bse" else NSE_WARMUP_URL)
            self._sessions[exchange] = s
        return self._sessions[exchange]

    def _get(self, session: creq.Session, url: str, **kwargs):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        log.debug("GET %s %s", url, kwargs.get("params", ""))
        return session.get(url, timeout=self.timeout, **kwargs)

    def _get_json(self, exchange: str, url: str, params: dict, headers: dict | None = None):
        for attempt in (1, 2):
            resp = self._get(self._session(exchange), url, params=params, headers=headers)
            if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                return resp.json()
            if attempt == 1 and resp.status_code in (401, 403):
                log.info(
                    "%s returned %s; refreshing cookies and retrying", exchange, resp.status_code
                )
                self._sessions.pop(exchange, None)
                continue
            raise ExchangeError(
                f"{exchange.upper()} returned HTTP {resp.status_code} "
                f"({resp.headers.get('content-type')}) for {url}"
            )
        raise AssertionError("unreachable")

    def bse_announcements(self, scrip_code: str, start: date, end: date, page: int = 1) -> dict:
        params = {
            "pageno": page,
            "strCat": -1,
            "strPrevDate": start.strftime("%Y%m%d"),
            "strScrip": scrip_code,
            "strSearch": "P",
            "strToDate": end.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": -1,
        }
        return self._get_json("bse", BSE_ANNOUNCEMENTS_URL, params, headers=BSE_HEADERS)

    def nse_announcements(
        self, symbol: str, start: date, end: date, index: str = "equities"
    ) -> list:
        """A symbol's announcements. NSE keeps SME (Emerge) companies' filings apart: pass
        index='sme' for them, or the answer is empty."""
        params = {
            "index": index,
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        return self._get_json("nse", NSE_ANNOUNCEMENTS_URL, params)

    def nse_financial_results(
        self, symbol: str, period: str = "Quarterly", index: str = "equities"
    ) -> list:
        """A symbol's results filings as NSE lists them. period: Quarterly, Half-Yearly,
        Annual or Others; index='sme' for SME companies."""
        params = {"index": index, "period": period, "symbol": symbol}
        data = self._get_json("nse", NSE_FINANCIAL_RESULTS_URL, params)
        return data if isinstance(data, list) else data.get("data", [])

    def nse_integrated_results(self, symbol: str, index: str = "equities") -> list:
        """A symbol's results filed as SEBI's Integrated Filing (Financial), from February
        2025: one row per filing with its quarter-end date (qe_Date) and XBRL link."""
        params = {"index": index, "symbol": symbol, "type": "Integrated Filing- Financials"}
        data = self._get_json("nse", NSE_INTEGRATED_URL, params)
        return data if isinstance(data, list) else data.get("data", [])

    def nse_json(self, url: str, params: dict):
        """Any NSE API answer, for probes."""
        return self._get_json("nse", url, params)

    def nse_corporate_actions(
        self, symbol: str, start: date, end: date, index: str = "equities"
    ) -> list:
        params = {
            "index": index,
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        data = self._get_json("nse", NSE_CORPORATE_ACTIONS_URL, params)
        return data if isinstance(data, list) else data.get("data", [])

    def nse_deals(self, kind: str, start: date, end: date) -> bytes:
        """NSE's bulk or block deals for a date range, as the report page's CSV download.

        The JSON form of the same request stops at 70 rows (checked Oct 2026: 70 of 134 bulk
        deals on 21 Oct); the CSV has every row (2,167 for 1-21 Oct in one request).
        """
        params = {
            "optionType": f"{kind}_deals",
            "from": start.strftime("%d-%m-%Y"),
            "to": end.strftime("%d-%m-%Y"),
            "csv": "true",
        }
        for attempt in (1, 2):
            session = self._session("nse")
            if self._deals_page_opened_in is not session:  # new or refreshed cookies
                self._get(session, NSE_DEALS_PAGE)
                self._deals_page_opened_in = session
            resp = self._get(
                session, NSE_DEALS_URL, params=params, headers={"Referer": NSE_DEALS_PAGE}
            )
            ctype = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "html" not in ctype:
                return resp.content
            if attempt == 1 and resp.status_code in (401, 403):
                self._sessions.pop("nse", None)
                continue
            raise ExchangeError(
                f"NSE returned HTTP {resp.status_code} ({ctype}) for {NSE_DEALS_URL}"
            )
        raise AssertionError("unreachable")

    def nse_file(self, url: str) -> bytes | None:
        """An NSE archive file, or None if NSE has none for that day (HTTP 404: a holiday)."""
        for attempt in (1, 2):
            resp = self._get(self._session("nse"), url)
            if resp.status_code == 404:
                return None
            if resp.status_code == 200 and "html" not in resp.headers.get("content-type", ""):
                return resp.content
            if attempt == 1 and resp.status_code in (401, 403):
                self._sessions.pop("nse", None)
                continue
            raise ExchangeError(f"NSE returned HTTP {resp.status_code} for {url}")
        raise AssertionError("unreachable")

    def download(
        self, exchange: str, urls: list[str], attempts: int = 3
    ) -> tuple[str, bytes, bool]:
        """Download the first URL that returns a file. Returns (url, content, complete).

        A file that arrives cut short is retried up to `attempts` times; a timeout or network
        error once. Raises ExchangeError when no URL gives a file. If two attempts return
        the same incomplete file, the exchange itself holds a broken copy (seen on NSE in Oct
        2026); it is returned with complete=False rather than retried further.
        """
        session = self._session(exchange)
        last = "no response"
        for url in urls:
            previous = None
            failures = 0
            for _ in range(attempts):
                try:
                    resp = self._get(
                        session, url, headers=BSE_HEADERS if exchange == "bse" else None
                    )
                except creq.exceptions.RequestException as exc:
                    # A timeout or dropped connection (large PDFs on a slow line): try once
                    # more, then give up on this URL rather than stop the whole run.
                    failures += 1
                    last = f"network error: {str(exc)[:200]}"
                    log.warning("%s: %s", url, last)
                    if failures >= 2:
                        break
                    continue
                if resp.status_code != 200 or "html" in resp.headers.get("content-type", ""):
                    last = f"HTTP {resp.status_code}"
                    break  # not here; try the next URL
                if is_complete(resp.content, resp.headers):
                    return url, resp.content, True
                if previous == resp.content:
                    log.warning("%s: the exchange serves an incomplete file; keeping it", url)
                    return url, resp.content, False
                previous = resp.content
                last = f"incomplete download ({len(resp.content)} bytes)"
                log.warning("%s: %s, retrying", url, last)
        raise ExchangeError(f"attachment not downloaded ({last}): {urls[0]}")


def is_complete(content: bytes, headers) -> bool:
    """False if the body is shorter than Content-Length, or is a PDF missing its end marker.

    (A server that itself holds a truncated file sends a matching Content-Length; only the
    missing end marker gives that away.)
    """
    length = headers.get("content-length")
    if length and str(length).isdigit() and len(content) < int(length):
        return False
    if content.startswith(b"%PDF-") and b"%%EOF" not in content[-8192:]:
        return False
    return True
