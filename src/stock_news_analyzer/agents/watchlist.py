"""Watchlist Manager (agent 1).

Keeps the master list of listed securities current, turns the names you type into exact
instruments (ISIN, NSE symbol, BSE code), stores what you track and own, and suggests peers.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.models import Company, CompanyPeer, WatchlistItem
from stock_news_analyzer.sources.securities import BseSecurity, NseSecurity

COMMODITIES = {"gold": "GOLD", "silver": "SILVER"}

# A match is picked automatically only when it is this good and clearly ahead of the next one.
AUTO_PICK_SCORE = 90
AUTO_PICK_GAP = 5
MIN_SCORE = 60


class ResolveError(Exception):
    def __init__(self, query: str, candidates: list["Match"]):
        self.query = query
        self.candidates = candidates
        super().__init__(query)


class NotFound(ResolveError):
    pass


class Ambiguous(ResolveError):
    pass


@dataclass
class Match:
    company: Company
    score: float


@dataclass
class MasterLoadResult:
    nse: int
    bse: int
    nifty500: int
    total: int


# --- master list -------------------------------------------------------------


def load_master(
    session: Session,
    nse: list[NseSecurity],
    nifty500: dict[str, str] | None = None,
    bse: list[BseSecurity] | None = None,
) -> MasterLoadResult:
    """Upsert the master list: NSE rows first, then BSE rows add BSE codes and BSE-only names."""
    nifty500 = nifty500 or {}
    bse = bse or []

    for s in nse:
        values = {
            "isin": s.isin,
            "name": s.name,
            "nse_symbol": s.symbol,
            "nse_series": s.series or None,
            "listed_on": s.listed_on,
            "industry": nifty500.get(s.isin),
            "in_nifty500": s.isin in nifty500,
        }
        session.execute(
            insert(Company)
            .values(**values)
            .on_conflict_do_update(index_elements=["isin"], set_=values)
        )

    for b in bse:
        values = {
            "isin": b.isin,
            "name": b.name,
            "bse_code": b.code,
            "bse_symbol": b.symbol,
            "bse_industry": b.industry,
            "market_cap_cr": b.market_cap_cr,
        }
        # On conflict keep the NSE name; only fill in the BSE fields.
        update = {k: v for k, v in values.items() if k not in ("isin", "name")}
        session.execute(
            insert(Company)
            .values(**values)
            .on_conflict_do_update(index_elements=["isin"], set_=update)
        )

    session.commit()
    total = session.query(Company).count()
    return MasterLoadResult(nse=len(nse), bse=len(bse), nifty500=len(nifty500), total=total)


# --- resolving names ---------------------------------------------------------


def _normalise(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    words = [w for w in name.split() if w not in ("limited", "ltd")]
    return " ".join(words)


def find_matches(session: Session, query: str, limit: int = 5) -> list[Match]:
    """Best matches for a name, NSE symbol, BSE code or ISIN, best first."""
    q = query.strip()
    exact = session.scalars(
        select(Company).where(
            or_(
                Company.nse_symbol == q.upper(),
                Company.bse_code == q,
                Company.isin == q.upper(),
            )
        )
    ).all()
    if exact:
        return [Match(c, 100.0) for c in exact]

    wanted = _normalise(q)
    scored = []
    for company in session.scalars(select(Company)):
        candidate = _normalise(company.name)
        score = fuzz.token_set_ratio(wanted, candidate)
        if score >= MIN_SCORE:
            # Tie-break equal scores by how close the whole name is.
            scored.append((score, fuzz.ratio(wanted, candidate), company))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [Match(c, float(s)) for s, _, c in scored[:limit]]


def resolve(session: Session, query: str) -> Company:
    """Return the one company a name refers to, or raise NotFound / Ambiguous with candidates."""
    matches = find_matches(session, query)
    if not matches:
        raise NotFound(query, [])
    top = matches[0]
    if len(matches) == 1 and top.score >= AUTO_PICK_SCORE:
        return top.company
    if top.score >= AUTO_PICK_SCORE and top.score - matches[1].score >= AUTO_PICK_GAP:
        return top.company
    raise Ambiguous(query, matches)


# --- watchlist ---------------------------------------------------------------


def add_equity(
    session: Session,
    company: Company,
    owned: bool = False,
    quantity: Decimal | None = None,
    notes: str | None = None,
    aliases: list[str] | None = None,
) -> WatchlistItem:
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.isin == company.isin))
    if item is None:
        item = WatchlistItem(kind="equity", isin=company.isin, display_name=company.name)
        session.add(item)
    item.owned = owned
    item.quantity = quantity
    if notes is not None:
        item.notes = notes
    if aliases is not None:
        item.aliases = [a.strip() for a in aliases if a.strip()]
    session.commit()
    return item


def add_commodity(
    session: Session, name: str, owned: bool = False, quantity: Decimal | None = None
) -> WatchlistItem:
    code = COMMODITIES[name.strip().lower()]
    item = session.scalar(select(WatchlistItem).where(WatchlistItem.commodity == code))
    if item is None:
        item = WatchlistItem(kind="commodity", commodity=code, display_name=code.title())
        session.add(item)
    item.owned = owned
    item.quantity = quantity
    session.commit()
    return item


def remove(session: Session, key: str) -> bool:
    """Remove by NSE symbol, ISIN or commodity name. Returns False if nothing matched."""
    k = key.strip().upper()
    company = session.scalar(select(Company).where(or_(Company.nse_symbol == k, Company.isin == k)))
    conditions = [WatchlistItem.commodity == COMMODITIES.get(key.strip().lower(), k)]
    if company is not None:
        conditions.append(WatchlistItem.isin == company.isin)
    item = session.scalar(select(WatchlistItem).where(or_(*conditions)))
    if item is None:
        return False
    session.delete(item)
    session.commit()
    return True


def list_items(session: Session) -> list[tuple[WatchlistItem, Company | None]]:
    rows = session.execute(
        select(WatchlistItem, Company)
        .outerjoin(Company, WatchlistItem.isin == Company.isin)
        .order_by(WatchlistItem.kind.desc(), WatchlistItem.display_name)
    ).all()
    return [(item, company) for item, company in rows]


# --- peers -------------------------------------------------------------------


def suggest_peers(session: Session, company: Company, limit: int = 10) -> list[Company]:
    """Companies in the same industry, largest market cap first.

    Uses BSE's industry if it is ever filled in, otherwise NSE's broader Nifty 500 industry.
    """
    if company.bse_industry:
        same = Company.bse_industry == company.bse_industry
    elif company.industry:
        same = Company.industry == company.industry
    else:
        return []
    return list(
        session.scalars(
            select(Company)
            .where(same, Company.isin != company.isin)
            .order_by(Company.market_cap_cr.desc().nulls_last(), Company.name)
            .limit(limit)
        )
    )


def approve_peers(session: Session, company: Company, peers: list[Company]) -> None:
    for peer in peers:
        session.execute(
            insert(CompanyPeer)
            .values(isin=company.isin, peer_isin=peer.isin, source="industry")
            .on_conflict_do_nothing()
        )
    session.commit()


def approved_peers(session: Session, company: Company) -> list[Company]:
    return list(
        session.scalars(
            select(Company)
            .join(CompanyPeer, CompanyPeer.peer_isin == Company.isin)
            .where(CompanyPeer.isin == company.isin)
            .order_by(Company.name)
        )
    )


# --- watchlist file ----------------------------------------------------------


@dataclass
class FileLoadResult:
    added: list[WatchlistItem]
    problems: list[ResolveError]


def load_file(session: Session, path: Path) -> FileLoadResult:
    """Load a watchlist YAML file (see config/watchlist.yaml). Safe to run repeatedly."""
    data = yaml.safe_load(path.read_text()) or {}
    added, problems = [], []

    for entry in data.get("stocks") or []:
        query = str(entry.get("symbol") or entry["name"])
        quantity = entry.get("quantity")
        try:
            company = resolve(session, query)
        except ResolveError as exc:
            problems.append(exc)
            continue
        added.append(
            add_equity(
                session,
                company,
                owned=bool(entry.get("owned", False)),
                quantity=Decimal(str(quantity)) if quantity is not None else None,
                notes=entry.get("notes"),
                aliases=[str(a) for a in entry.get("aliases") or []],
            )
        )

    for entry in data.get("bullion") or []:
        if isinstance(entry, str):
            entry = {"name": entry}
        quantity = entry.get("quantity")
        added.append(
            add_commodity(
                session,
                entry["name"],
                owned=bool(entry.get("owned", False)),
                quantity=Decimal(str(quantity)) if quantity is not None else None,
            )
        )

    return FileLoadResult(added=added, problems=problems)
