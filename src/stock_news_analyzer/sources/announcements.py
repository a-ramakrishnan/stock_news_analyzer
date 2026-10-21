"""Corporate announcements from BSE and NSE, parsed into one common shape.

Field names come from the exchanges' live responses (Oct 2026); see tests/fixtures/.
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_news_analyzer.sources.exchange_http import BSE_ATTACHMENT_URLS

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class Announcement:
    source: str  # 'bse' or 'nse'
    source_id: str  # BSE NEWSID / NSE seq_id
    exchange_code: str  # BSE scrip code / NSE symbol
    isin: str | None  # NSE gives it; for BSE it comes from the scrip code
    title: str
    subject: str
    category: str | None
    published_at: datetime  # when the exchange made it public, IST
    attachment_urls: list[str] = field(default_factory=list)  # alternatives, best first
    attachment_bytes: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def doc_type(self) -> str:
        return classify(self.subject, self.title, self.category, self.raw)


def _ist(value: str | None, *formats: str) -> datetime | None:
    if not value:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_bse(data: dict) -> list[Announcement]:
    out = []
    for row in data.get("Table") or []:
        published = _ist(
            row.get("DissemDT") or row.get("NEWS_DT") or row.get("DT_TM"),
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        )
        if not row.get("NEWSID") or published is None:
            continue
        name = (row.get("ATTACHMENTNAME") or "").strip()
        subject = (row.get("NEWSSUB") or "").strip()
        out.append(
            Announcement(
                source="bse",
                source_id=row["NEWSID"],
                exchange_code=str(row.get("SCRIP_CD")),
                isin=None,
                title=(row.get("HEADLINE") or subject).strip(),
                subject=subject,
                category=(row.get("SUBCATNAME") or row.get("CATEGORYNAME") or "").strip() or None,
                published_at=published,
                attachment_urls=[u.format(name=name) for u in BSE_ATTACHMENT_URLS] if name else [],
                attachment_bytes=row.get("Fld_Attachsize"),
                raw=row,
            )
        )
    return out


def bse_total_rows(data: dict) -> int:
    counts = data.get("Table1") or [{}]
    return int(counts[0].get("ROWCNT") or 0)


def parse_nse(data: list) -> list[Announcement]:
    out = []
    for row in data or []:
        published = _ist(row.get("exchdisstime") or row.get("an_dt"), "%d-%b-%Y %H:%M:%S") or _ist(
            row.get("sort_date"), "%Y-%m-%d %H:%M:%S"
        )
        if not row.get("seq_id") or published is None:
            continue
        url = (row.get("attchmntFile") or "").strip()
        out.append(
            Announcement(
                source="nse",
                source_id=str(row["seq_id"]),
                exchange_code=row.get("symbol") or "",
                isin=row.get("sm_isin") or None,
                title=(row.get("attchmntText") or row.get("desc") or "").strip(),
                subject=(row.get("desc") or "").strip(),
                category=(row.get("desc") or "").strip() or None,
                published_at=published,
                attachment_urls=[url] if url and url != "-" else [],
                raw=row,
            )
        )
    return out


# Checked in order: the first rule whose words appear decides the type.
_RULES = [
    ("concall_transcript", ("transcript",)),
    ("concall_audio", ("audio recording", "audio/video", "audio of", "recording of")),
    ("investor_presentation", ("investor presentation", "presentation")),
    ("results", ("financial result", "results for the quarter", "outcome of board meeting")),
    ("concall_schedule", ("analyst", "investor meet", "earnings call", "conference call")),
    ("order_win", ("bagging", "receiving of order", "order win", "wins order", "orders")),
    ("credit_rating", ("credit rating",)),
    ("board_meeting", ("board meeting",)),
    ("shareholding", ("shareholding",)),
    ("insider_trading", ("insider trading", "sast", "acquisition of shares")),
]

# Documents the Concall Analyst (agent 11) will read for stocks you own.
CONCALL_MATERIAL = {"concall_transcript", "concall_audio", "investor_presentation", "results"}


def classify(subject: str, title: str, category: str | None, raw: dict | None = None) -> str:
    if raw and raw.get("AUDIO_VIDEO_FILE"):
        return "concall_audio"
    text = " ".join(filter(None, (subject, title, category))).lower()
    for doc_type, words in _RULES:
        if any(w in text for w in words):
            return doc_type
    return "other"
