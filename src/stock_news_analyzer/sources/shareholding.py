"""Shareholding-pattern XBRL files: who owns a company at a quarter's end.

Every listed company files its shareholding pattern each quarter (LODR Regulation 31), and
NSE lists the filings with a link to each XBRL file (`ExchangeClient.nse_shareholdings`). In
the file each figure is tagged with what it is (NumberOfShares,
ShareholdingAsAPercentageOfTotalNumberOfShares...) and its context names the holder category
as a dimension member: ShareholdingOfPromoterAndPromoterGroupMember, MutualFundsOrUTIMember,
InstitutionsForeignMember, ShareholdingPatternMember (the total) and so on. Percentages are
written as fractions (0.1939 for 19.39%).
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

PROMOTER = "ShareholdingOfPromoterAndPromoterGroup"
PUBLIC = "PublicShareholding"
TOTAL = "ShareholdingPattern"
# The categories kept in their own columns, by member name (without prefix and "Member").
COLUMNS = {
    "fii_pct": "InstitutionsForeign",
    "dii_pct": "InstitutionsDomestic",
    "mf_pct": "MutualFundsOrUTI",
    "insurance_pct": "InsuranceCompanies",
    "retail_pct": "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh",
}
ENCUMBERED = re.compile(r"(?i)pledg|encumber")


@dataclass
class Pattern:
    quarter_end: date | None = None
    categories: dict[str, dict] = field(default_factory=dict)  # name: shares, pct, holders
    pledged_pct: Decimal | None = None  # of the promoters' shares
    locked_pct: Decimal | None = None  # of the promoters' shares

    def pct(self, name: str) -> Decimal | None:
        found = self.categories.get(name, {}).get("pct")
        return Decimal(found) if found is not None else None

    def shares(self, name: str) -> int | None:
        return self.categories.get(name, {}).get("shares")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _member(text: str) -> str:
    """'in-bse-shp:MutualFundsOrUTIMember' -> 'MutualFundsOrUTI'."""
    name = text.strip().rsplit(":", 1)[-1]
    return name[: -len("Member")] if name.endswith("Member") else name


def _number(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return None


def parse(content: bytes) -> Pattern:
    """The categories of a shareholding-pattern file, from the contexts that name exactly one
    category (contexts that also name a shareholder, for the lists of large holders, are
    left out)."""
    root = ET.fromstring(content)
    category: dict[str, str] = {}  # context id -> category
    for ctx in root.iter():
        if _local(ctx.tag) != "context" or not ctx.get("id"):
            continue
        explicit = [m.text for m in ctx.iter() if _local(m.tag) == "explicitMember" and m.text]
        typed = any(_local(m.tag) == "typedMember" for m in ctx.iter())
        if len(explicit) == 1 and not typed:
            category[ctx.get("id")] = _member(explicit[0])
    out = Pattern()
    encumbered: list[Decimal] = []
    encumbered_shares: list[Decimal] = []
    for el in root.iter():
        text = (el.text or "").strip()
        tag = _local(el.tag)
        if tag == "DateOfReport" and text:
            out.quarter_end = date.fromisoformat(text[:10])
        name = category.get(el.get("contextRef") or "")
        if name is None or not text:
            continue
        value = _number(text)
        if value is None:
            continue
        cat = out.categories.setdefault(name, {})
        if tag == "NumberOfShares":
            cat["shares"] = int(value)
        elif tag == "ShareholdingAsAPercentageOfTotalNumberOfShares":
            cat["pct"] = str((value * 100).quantize(Decimal("0.0001")))
        elif tag == "NumberOfShareholders":
            cat["holders"] = int(value)
        elif name == PROMOTER and tag == "LockedInSharesAsAPercentageOfTotalNumberOfShares":
            out.locked_pct = (value * 100).quantize(Decimal("0.0001"))
        elif name == PROMOTER and ENCUMBERED.search(tag):
            (encumbered if "Percentage" in tag else encumbered_shares).append(value)
    # The form splits encumbrance into pledges, non-disposal undertakings and others, with a
    # total: the largest figure is the total.
    if encumbered:
        out.pledged_pct = (max(encumbered) * 100).quantize(Decimal("0.0001"))
    elif encumbered_shares and out.shares(PROMOTER):
        out.pledged_pct = (max(encumbered_shares) * 100 / out.shares(PROMOTER)).quantize(
            Decimal("0.0001")
        )
    return out
