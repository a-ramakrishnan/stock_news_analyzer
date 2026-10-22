from datetime import date
from pathlib import Path

import pytest
from test_corporate_actions import FakeNSE as FakeActions
from test_filings import FakeClient as FakeFilings
from test_news import FakeClient as FakeFeeds
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.models import WatchlistItem
from stock_news_analyzer.ui import actions

REPO = Path(__file__).parent.parent
LT = "INE018A01030"
CUB = "INE491A01021"


class FakeExchange(FakeFilings, FakeActions):
    def __init__(self):
        super().__init__()
        self.action_symbols = []

    def nse_corporate_actions(self, symbol, start, end):
        self.action_symbols.append(symbol)
        return super().nse_corporate_actions(symbol, start, end)


@pytest.mark.db
def test_search_marks_tracked_companies(loaded):  # noqa: F811
    hits = {h["symbol"]: h for h in actions.search(loaded, "City Union")}
    assert hits["CUB"]["isin"] == CUB and not hits["CUB"]["tracked"]
    assert actions.search(loaded, "LT")[0]["tracked"]
    assert actions.search(loaded, "  ") == []


@pytest.mark.db
def test_add_edit_and_remove_from_the_dashboard(loaded):  # noqa: F811
    assert "Nifty Bank" in actions.index_names(loaded)
    actions.add_stock(
        loaded, CUB, owned=False, aliases="CUB, City Union", sector_index="Nifty Bank"
    )
    rows = {r["symbol"]: r for r in actions.tracked_stocks(loaded)}
    assert rows["CUB"] == {
        "isin": CUB,
        "symbol": "CUB",
        "name": "City Union Bank Limited",
        "owned": False,
        "sector_index": "Nifty Bank",
        "aliases": "CUB, City Union",
        "remove": False,
    }
    assert list(rows)[:3] != ["CUB"]  # owned stocks are listed first

    rows["CUB"].update(owned=True, aliases="CUB", sector_index="")
    rows["KARURVYSYA"]["remove"] = True
    assert actions.save_changes(loaded, list(rows.values())) == (1, 1)
    cub = loaded.query(WatchlistItem).filter_by(isin=CUB).one()
    assert cub.owned and cub.aliases == ["CUB"] and cub.sector_index is None
    assert {r["symbol"] for r in actions.tracked_stocks(loaded)} == {"LT", "MSUMI", "CUB"}
    assert actions.save_changes(loaded, actions.tracked_stocks(loaded)) == (0, 0)  # no changes

    with pytest.raises(ValueError, match="unknown ISIN"):
        actions.add_stock(loaded, "INE000000000", owned=True)


@pytest.mark.db
def test_load_history_for_one_stock(loaded, tmp_path):  # noqa: F811
    exchange, lines = FakeExchange(), []
    errors = actions.load_history(
        loaded,
        LT,
        tmp_path,
        since=date(2026, 9, 1),
        progress=lines.append,
        exchange=exchange,
        news_client=FakeFeeds(),
        feeds_file=REPO / "config/news_feeds.yaml",
    )
    assert errors == []
    assert exchange.action_symbols == ["LT"]  # only this stock's corporate actions
    assert {c[1] for c in exchange.calls} == {"500510", "LT"}  # BSE code and NSE symbol
    assert lines[0].startswith("Filings") and lines[-1].startswith("Done:")
    assert actions.load_history(loaded, CUB, tmp_path) == [f"{CUB} is not on the watchlist"]


@pytest.mark.db
def test_manage_page_adds_a_stock(loaded, test_database_url, monkeypatch, tmp_path):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from stock_news_analyzer.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    at = AppTest.from_string(
        "from stock_news_analyzer.ui import app\napp.manage_page()", default_timeout=30
    )
    at.run()
    at.text_input[0].input("City Union").run()
    assert "CUB · City Union Bank Limited" in at.radio[0].options[0]
    at.radio[1].set_value("Watchlist")
    at.selectbox[0].set_value("Nifty Bank")
    next(b for b in at.button if b.label == "Add").click().run()
    assert not at.exception, at.exception
    assert "Added City Union Bank Limited in Watchlist." in at.success[0].value
    loaded.expire_all()
    cub = loaded.query(WatchlistItem).filter_by(isin=CUB).one()
    assert not cub.owned and cub.sector_index == "Nifty Bank"
    assert any(b.label == "Load history now" for b in at.button)
