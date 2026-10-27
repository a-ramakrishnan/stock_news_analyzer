"""Corporate announcements from BSE and NSE, parsed into one common shape.

Field names come from the exchanges' live responses (Oct 2026); see tests/fixtures/.
"""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_news_analyzer.sources.exchange_http import BSE_ATTACHMENT_URLS
from stock_news_analyzer.text import clean

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
        subject = clean(row.get("NEWSSUB"))
        out.append(
            Announcement(
                source="bse",
                source_id=row["NEWSID"],
                exchange_code=str(row.get("SCRIP_CD")),
                isin=None,
                title=clean(row.get("HEADLINE")) or subject,
                subject=subject,
                category=clean(row.get("SUBCATNAME") or row.get("CATEGORYNAME")) or None,
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
                title=clean(row.get("attchmntText") or row.get("desc")),
                subject=clean(row.get("desc")),
                category=clean(row.get("desc")) or None,
                published_at=published,
                attachment_urls=[url] if url and url != "-" else [],
                raw=row,
            )
        )
    return out


# Checked in order: the first rule whose words appear decides the type.
_RULES = [
    ("concall_transcript", ("transcript",)),
    ("concall_audio", ("audio recording", "audio/video", "audio of", "recording")),
    ("newspaper_publication", ("newspaper",)),
    ("investor_presentation", ("investor presentation", "presentation")),
    ("results", ("financial result", "results for the quarter", "outcome of board meeting")),
    ("concall_schedule", ("analyst", "investor meet", "earnings call", "conference call")),
    (
        "order_win",
        (
            "bagging",
            "receiving of order",
            "order win",
            "wins order",
            "orders",
            # One order at a time, as smaller companies (and NSE SME filings) word it.
            "work order",
            "letter of award",
            "letter of intent",
            "award of contract",
            "award of work",
            "contract award",
            "receipt of order",
            "receipt of purchase order",
            "order received",
            "received an order",
            "secured an order",
            "secures order",
            "new order",
            "lowest bidder",
            "l1 bidder",
            "bags ",
        ),
    ),
    ("credit_rating", ("credit rating",)),
    ("board_meeting", ("board meeting",)),
    ("shareholding", ("shareholding",)),
    ("insider_trading", ("insider trading", "sast", "acquisition of shares")),
]

# Documents the Concall Analyst (agent 11) reads.
CONCALL_MATERIAL = {"concall_transcript", "concall_audio", "investor_presentation", "results"}

# The Event Extractor (agent 7) reads filings of these types whose title names an event.
# Results, order wins and call material have their own agents.
EVENT_DOC_TYPES = {"other", "board_meeting", "credit_rating", "insider_trading"}
EVENT_WORDS = (
    # capacity and capex
    "capacity",
    "expansion",
    "commission",
    "commercial production",
    "commercial operation",
    "capex",
    "capital expenditure",
    "plant",
    "facility",
    "greenfield",
    "brownfield",
    # guidance and updates
    "guidance",
    "outlook",
    "business update",
    "operational update",
    # management
    "appointment",
    "resignation",
    "cessation",
    "change in director",
    "change in management",
    "senior management",
    "key managerial",
    "managing director",
    "chief executive",
    "chief financial",
    "auditor",
    # ratings ("rating" alone would match "operating")
    "credit rating",
    "ratings",
    "rating action",
    "rating agenc",
    # legal and regulatory
    "litigation",
    "dispute",
    "penalty",
    "show cause",
    "demand",
    "tax",
    "search",
    "sebi",
    "nclt",
    "arbitra",
    "court",
    "tribunal",
    "regulatory action",
    # deals and funding
    "acqui",
    "merger",
    "amalgamation",
    "demerger",
    "scheme of arrangement",
    "joint venture",
    "subsidiary",
    "stake ",  # not "stakeholder"
    "divest",
    "disinvest",
    "slump sale",
    "sale of",
    "fund rais",
    "raising of funds",
    "qip",
    "qualified institution",
    "preferential",
    "rights issue",
    "warrant",
    "debenture",
    "ncd",
    "buyback",
    "buy-back",
    # promoters
    "pledge",
    "encumbrance",
    "promoter",
    "sast",
    "takeover",
    "offer for sale",
    # disruptions
    "fire",
    "accident",
    "strike",
    "lockout",
    "shutdown",
    "suspension of operation",
    "cyber",
    "flood",
    "force majeure",
    "disruption",
    "incident",
    # agreements and approvals
    "agreement",
    " mou",  # not "amount"
    "memorandum of understanding",
    "partnership",
    "collaboration",
    "launch",
    "approval",
    "licen",
    "usfda",
    "inspection",
)
# Routine filings that use the same words: skipped before any are read.
ROUTINE_WORDS = (
    "trading window",
    "share certificate",
    "74(5)",
    "regulation 74",
    "compliance certificate",
    "esop",
    "esos",
    "employee stock",
    "newspaper",
    "investor complaint",
    "secretarial compliance",
    "annual report",
    "record date",
    "book closure",
    "iepf",
    "unclaimed",
    "related party transaction",
    "statement of deviation",
    "monitoring agency",
    "large corporate",
    "initial disclosure",
    "annual disclosure",
    "voting result",
    "scrutini",
    "business responsibility",
    "loss of share",
    "esg",
)


def event_candidate(doc_type: str, title: str | None, subject: str | None) -> bool:
    """Whether a filing may announce an event the Event Extractor records."""
    if doc_type not in EVENT_DOC_TYPES:
        return False
    text = f"{title or ''} {subject or ''}".lower()
    if any(w in text for w in ROUTINE_WORDS):
        return False
    return doc_type == "credit_rating" or any(w in text for w in EVENT_WORDS)


def classify(subject: str, title: str, category: str | None, raw: dict | None = None) -> str:
    if raw and raw.get("AUDIO_VIDEO_FILE"):
        return "concall_audio"
    text = " ".join(filter(None, (subject, title, category))).lower()
    for doc_type, words in _RULES:
        if any(w in text for w in words):
            return doc_type
    return "other"
