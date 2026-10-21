from datetime import date
from decimal import Decimal

from conftest import FIXTURES

from stock_news_analyzer.sources.securities import (
    parse_bse_scrips,
    parse_nifty500,
    parse_nse_equity_list,
)


def test_nse_equity_list_handles_bom_and_spaced_headers():
    rows = parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8"))
    by_symbol = {r.symbol: r for r in rows}
    assert len(rows) == 9
    lt = by_symbol["LT"]
    assert lt.name == "Larsen & Toubro Limited"
    assert lt.isin == "INE018A01030"
    assert lt.series == "EQ"
    assert lt.listed_on == date(2004, 6, 23)


def test_nse_equity_list_tolerates_bad_dates():
    text = "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\nX,X Ltd,EQ,soon,INE1\n"
    assert parse_nse_equity_list(text)[0].listed_on is None


def test_nifty500_maps_isin_to_industry():
    industries = parse_nifty500((FIXTURES / "ind_nifty500list.csv").read_text())
    assert industries["INE018A01030"] == "Construction"
    assert industries["INE036D01028"] == "Financial Services"


def test_bse_scrips_reads_codes_and_skips_rows_without_isin():
    # The fixture's L&T row is copied from BSE's live response (Oct 2026): INDUSTRY is null.
    rows = parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text())
    by_isin = {r.isin: r for r in rows}
    assert "NOISIN" not in {r.symbol for r in rows}
    lt = by_isin["INE018A01030"]
    assert (lt.code, lt.symbol, lt.name) == ("500510", "LT", "Larsen & Toubro Limited")
    assert lt.industry is None
    assert lt.market_cap_cr == Decimal("499683.78")
    assert by_isin["INE999X01011"].market_cap_cr is None  # blank Mktcap


def test_bse_scrips_accepts_wrapped_response():
    text = '{"Table": [{"SCRIP_CD": 500510, "ISIN_NUMBER": "INE018A01030", "Scrip_Name": "L&T"}]}'
    rows = parse_bse_scrips(text)
    assert rows[0].code == "500510"
    assert rows[0].name == "L&T"
