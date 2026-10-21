from decimal import Decimal
from pathlib import Path

import pytest
from conftest import FIXTURES

from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import Company
from stock_news_analyzer.sources.securities import (
    parse_bse_scrips,
    parse_nifty500,
    parse_nse_equity_list,
)

pytestmark = pytest.mark.db

REPO_WATCHLIST = Path(__file__).parent.parent / "config" / "watchlist.yaml"


@pytest.fixture
def master(session):
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        parse_nifty500((FIXTURES / "ind_nifty500list.csv").read_text()),
        parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    return session


def test_master_merges_nse_and_bse_by_isin(master):
    lt = master.get(Company, "INE018A01030")
    assert lt.name == "Larsen & Toubro Limited"  # NSE name kept
    assert (lt.nse_symbol, lt.bse_code) == ("LT", "500510")
    assert (lt.industry, lt.bse_industry) == ("Construction", None)
    assert lt.market_cap_cr == Decimal("499683.78")
    assert lt.in_nifty500
    bse_only = master.get(Company, "INE999X01011")
    assert bse_only.nse_symbol is None and bse_only.bse_code == "999901"


def test_master_reload_is_idempotent(master):
    before = master.query(Company).count()
    wl.load_master(master, parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text()))
    assert master.query(Company).count() == before


@pytest.mark.parametrize(
    "query, symbol",
    [
        ("Larsen & Toubro", "LT"),
        ("Karur Vysya Bank", "KARURVYSYA"),
        ("Motherson Sumi Wiring", "MSUMI"),
        ("lt", "LT"),  # NSE symbol
        ("590003", "KARURVYSYA"),  # BSE code
        ("INE0FS801015", "MSUMI"),  # ISIN
    ],
)
def test_resolve_finds_the_right_company(master, query, symbol):
    assert wl.resolve(master, query).nse_symbol == symbol


def test_resolve_reports_candidates_when_ambiguous(master):
    with pytest.raises(wl.Ambiguous) as exc:
        wl.resolve(master, "Bank")
    assert len(exc.value.candidates) > 1


def test_resolve_reports_not_found(master):
    with pytest.raises(wl.NotFound):
        wl.resolve(master, "Zzyzx Quantum Holdings")


def test_add_equity_updates_existing_item(master):
    lt = wl.resolve(master, "LT")
    wl.add_equity(master, lt, owned=False)
    wl.add_equity(master, lt, owned=True, quantity=Decimal("25"))
    rows = wl.list_items(master)
    assert len(rows) == 1
    item, company = rows[0]
    assert item.owned and item.quantity == Decimal("25") and company.isin == lt.isin


def test_load_repo_watchlist_file(master):
    result = wl.load_file(master, REPO_WATCHLIST)
    assert not result.problems
    tracked = {c.nse_symbol: (i.owned, c.bse_code) for i, c in wl.list_items(master)}
    assert tracked == {
        "LT": (True, "500510"),
        "KARURVYSYA": (True, "590003"),
        "MSUMI": (True, "543498"),
    }


def test_load_file_reports_unresolved_names(master, tmp_path):
    f = tmp_path / "w.yaml"
    f.write_text("stocks:\n  - name: Bank\n  - name: LT\n    owned: true\nbullion: [gold]\n")
    result = wl.load_file(master, f)
    assert [p.query for p in result.problems] == ["Bank"]
    assert {i.display_name for i in result.added} == {"Larsen & Toubro Limited", "Gold"}


def test_remove_unknown_symbol_leaves_bullion_alone(master):
    wl.add_commodity(master, "gold", owned=True)
    assert wl.remove(master, "NOTASTOCK") is False
    assert [i.commodity for i, _ in wl.list_items(master)] == ["GOLD"]
    assert wl.remove(master, "gold") is True
    assert wl.list_items(master) == []


def test_peers_share_nse_industry_largest_first_and_can_be_approved(master):
    kvb = wl.resolve(master, "KARURVYSYA")
    suggested = [p.nse_symbol for p in wl.suggest_peers(master, kvb)]
    # Same Nifty 500 industry ("Financial Services"), by market cap. KTKBANK is not in the
    # Nifty 500 sample, so it has no industry and is not suggested.
    assert suggested == ["FEDERALBNK", "LTF", "CUB"]

    wl.approve_peers(master, kvb, [wl.resolve(master, "CUB")])
    wl.approve_peers(master, kvb, [wl.resolve(master, "CUB")])  # no duplicate
    assert [p.nse_symbol for p in wl.approved_peers(master, kvb)] == ["CUB"]
