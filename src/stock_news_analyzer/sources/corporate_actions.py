"""NSE corporate actions: bonus issues, splits and dividends.

NSE's full bhavcopy does not adjust the previous close on ex-dates (checked Oct 2026: on the
MSUMI 1:2 bonus ex-date the stored previous close was the old 64.47). These records supply
the adjustment.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction

BONUS = re.compile(r"bonus\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
FACE_VALUE_CHANGE = re.compile(
    r"from\s*r[se]\.?\s*([\d.]+).*?to\s*r[se]\.?\s*([\d.]+)", re.IGNORECASE | re.DOTALL
)
DIVIDEND_AMOUNT = re.compile(r"r[se]\.?\s*([\d.]+)\s*(?:/-)?\s*per\s*share", re.IGNORECASE)


@dataclass
class CorporateAction:
    symbol: str
    series: str
    ex_date: date
    subject: str
    isin: str | None
    kind: str  # 'bonus', 'split', 'consolidation', 'dividend', 'rights', 'other'
    # Multiply the previous close by this to make it comparable with the ex-date price
    # (bonus 1:2 -> 2/3, split Rs 10 -> Rs 2 -> 1/5). 1 for dividends and other actions.
    price_factor: float = 1.0
    dividend: Decimal | None = None  # Rs per share, subtracted from the previous close
    raw: dict = field(default_factory=dict)


def classify_action(subject: str) -> tuple[str, float, Decimal | None]:
    """(kind, price factor, dividend per share) from NSE's subject text."""
    s = subject.lower()
    if m := BONUS.search(subject):
        new, held = int(m.group(1)), int(m.group(2))
        return "bonus", float(Fraction(held, held + new)), None
    if ("split" in s or "consolidation" in s or "sub-division" in s) and (
        m := FACE_VALUE_CHANGE.search(subject)
    ):
        old, new = Decimal(m.group(1)), Decimal(m.group(2))
        if old and new and old != new:
            return ("split" if new < old else "consolidation"), float(new / old), None
    if "dividend" in s:
        amounts = [Decimal(a) for a in DIVIDEND_AMOUNT.findall(subject)]
        return "dividend", 1.0, (sum(amounts) if amounts else None)
    if "rights" in s:
        return "rights", 1.0, None  # needs the rights price; not adjusted (rare and small)
    return "other", 1.0, None


def parse_corporate_actions(data) -> list[CorporateAction]:
    rows = data if isinstance(data, list) else (data or {}).get("data", [])
    out = []
    for row in rows:
        try:
            ex_date = datetime.strptime(row["exDate"], "%d-%b-%Y").date()
        except (KeyError, TypeError, ValueError):
            continue
        subject = (row.get("subject") or "").strip()
        kind, factor, dividend = classify_action(subject)
        out.append(
            CorporateAction(
                symbol=row.get("symbol", ""),
                series=row.get("series") or "",
                ex_date=ex_date,
                subject=subject,
                isin=row.get("isin") or None,
                kind=kind,
                price_factor=factor,
                dividend=dividend,
                raw=row,
            )
        )
    return out
