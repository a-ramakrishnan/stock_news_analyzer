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
TEST_WATCHLIST = Path(__file__).parent / "fixtures" / "watchlist.yaml"


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


def test_resolve_prefers_the_name_written_in_full(master):
    from stock_news_analyzer.models import Company

    master.add_all(
        [
            Company(isin="INE0ZINKA001", name="Zinka Logistics Solutions Limited"),
            Company(isin="INE0ZINKA002", name="Zinka Logistics Solutions India Limited"),
        ]
    )
    master.flush()
    assert wl.resolve(master, "Zinka Logistics Solutions").isin == "INE0ZINKA001"
    with pytest.raises(wl.Ambiguous):
        wl.resolve(master, "Zinka Logistics")  # neither is named exactly that


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


def test_load_watchlist_file(master):
    result = wl.load_file(master, TEST_WATCHLIST)
    assert not result.problems
    tracked = {c.nse_symbol: (i.owned, c.bse_code) for i, c in wl.list_items(master)}
    assert tracked == {
        "LT": (True, "500510"),
        "KARURVYSYA": (True, "590003"),
        "MSUMI": (True, "543498"),
    }


def test_repo_watchlist_file_is_well_formed(master):
    """Your own config/watchlist.yaml: every entry has a name, and loading it never crashes.

    The test master list holds only a few companies, so names outside it are reported, not
    loaded; on your Mac the full NSE/BSE list resolves them.
    """
    import yaml

    data = yaml.safe_load(REPO_WATCHLIST.read_text())
    assert all(str(entry.get("name") or "").strip() for entry in data["stocks"])
    result = wl.load_file(master, REPO_WATCHLIST)
    assert all(isinstance(p, wl.ResolveError) for p in result.problems)
    assert {"LT", "KARURVYSYA", "MSUMI"} <= {c.nse_symbol for _, c in wl.list_items(master)}


def test_example_watchlist_loads(master):
    """config/watchlist.example.yaml, for new copies: loading it never crashes, and L&T (in the
    test master list) is added; the others are reported, not loaded."""
    result = wl.load_file(master, REPO_WATCHLIST.with_name("watchlist.example.yaml"))
    assert {c.nse_symbol for _, c in wl.list_items(master)} >= {"LT"}
    assert all(isinstance(p, wl.ResolveError) for p in result.problems)


def test_compose_starts_everything_after_the_migrations():
    """`docker compose up -d` (the start script) runs the dashboard and the scheduler, each
    after the database has been brought up to date."""
    import yaml

    compose = yaml.safe_load((REPO_WATCHLIST.parents[1] / "docker-compose.yml").read_text())
    services = compose["services"]
    assert compose["name"] == "stock_news_analyzer"  # keeps the existing data volume
    assert services["migrate"]["command"] == ["sna", "db", "upgrade"]
    for name in ("ui", "scheduler"):
        assert "profiles" not in services[name]
        assert services[name]["depends_on"]["migrate"]["condition"] == (
            "service_completed_successfully"
        )
    assert services["ui"]["ports"] == ["127.0.0.1:8501:8501"]
    # The prebuilt image is named, and built here unless SNA_PULL_POLICY says to pull it.
    for name in ("migrate", "ui", "scheduler", "app"):
        assert services[name]["image"].startswith("ghcr.io/a-ramakrishnan/stock_news_analyzer:")
        assert (
            services[name]["build"] == "."
            and "SNA_PULL_POLICY:-build" in (services[name]["pull_policy"])
        )


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
