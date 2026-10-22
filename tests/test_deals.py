from datetime import date

import pytest
from conftest import FIXTURES
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import deals as dl
from stock_news_analyzer.models import Deal
from stock_news_analyzer.sources.deals import DealsFormatError, parse_deals

MSUMI = "INE0FS801015"


def test_parse_api_json():
    deals = parse_deals((FIXTURES / "nse_bulk_deals.json").read_bytes(), "bulk")
    assert len(deals) == 3
    first = deals[0]
    assert (first.trade_date, first.symbol, first.side, first.quantity) == (
        date(2026, 10, 21),
        "MSUMI",
        "BUY",
        5_200_000,
    )
    assert first.security_name == "Motherson Sumi Wiring India Ltd"  # not the client's name
    assert first.client == "EXAMPLE GROWTH FUND" and str(first.price) == "41.25"
    assert deals[1].client == "SAMPLE PROMOTER HOLDINGS"  # spacing tidied
    assert first.remarks is None  # "-" means none


def test_parse_csv_download():
    (deal,) = parse_deals((FIXTURES / "nse_block_deals.csv").read_text(), "block")
    assert (deal.kind, deal.symbol, deal.quantity, str(deal.price)) == (
        "block",
        "LT",
        1_500_000,
        "3640.00",
    )
    assert deal.security_name == "Larsen & Toubro Ltd." and deal.client == "EXAMPLE PENSION FUND"


def test_unrecognised_format_is_reported():
    assert parse_deals(b'{"data": []}', "bulk") == []
    with pytest.raises(DealsFormatError, match="no column for"):
        parse_deals(b'{"data": [{"foo": 1, "bar": 2}]}', "bulk")


class FakeNSE:
    def __init__(self, fail_block=False):
        self.calls = []
        self.fail_block = fail_block

    def nse_deals(self, kind, start, end):
        from stock_news_analyzer.sources.exchange_http import ExchangeError

        self.calls.append((kind, start, end))
        if kind == "block" and self.fail_block:
            raise ExchangeError("NSE returned HTTP 403")
        if kind == "bulk":
            return (FIXTURES / "nse_bulk_deals.json").read_bytes()
        return (FIXTURES / "nse_block_deals.csv").read_bytes()


@pytest.mark.db
def test_collect_stores_each_deal_once_by_month(loaded):  # noqa: F811
    client = FakeNSE()
    result = dl.collect(loaded, client, date(2026, 9, 1), date(2026, 10, 21))
    # Two monthly windows x two kinds; the same fixture comes back each time.
    assert [(k, s) for k, s, _ in client.calls] == [
        ("bulk", date(2026, 9, 1)),
        ("block", date(2026, 9, 1)),
        ("bulk", date(2026, 10, 1)),
        ("block", date(2026, 10, 1)),
    ]
    assert (result.new, result.seen, result.errors) == (4, 8, [])
    stored = {(d.symbol, d.side): d for d in loaded.query(Deal)}
    assert stored[("MSUMI", "BUY")].isin == MSUMI
    assert stored[("NOTLISTEDHERE", "BUY")].isin is None  # kept, but linked to no company
    assert dl.resume_date(loaded) == date(2026, 10, 18)  # three days of overlap


@pytest.mark.db
def test_failed_kind_is_reported_and_others_kept(loaded):  # noqa: F811
    result = dl.collect(loaded, FakeNSE(fail_block=True), date(2026, 10, 1), date(2026, 10, 21))
    assert result.new == 3 and "HTTP 403" in result.errors[0]


@pytest.mark.db
def test_a_deal_without_a_price_is_still_stored_once(loaded):  # noqa: F811
    (deal,) = parse_deals(
        b'{"data": [{"BD_DT_DATE": "21-OCT-2026", "BD_SYMBOL": "LT", "BD_CLIENT_NAME": "X",'
        b' "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 10}]}',
        "bulk",
    )
    assert deal.price is None
    assert dl.store(loaded, [deal]) == 1 and dl.store(loaded, [deal]) == 0


@pytest.mark.db
def test_share_of_volume_and_dashboard(loaded):  # noqa: F811
    from stock_news_analyzer.models import PriceDaily
    from stock_news_analyzer.ui import queries

    dl.collect(loaded, FakeNSE(), date(2026, 10, 1), date(2026, 10, 21))
    volume = loaded.query(PriceDaily).filter_by(isin=MSUMI, trade_date=date(2026, 10, 21)).one()
    rows = dl.watchlist_deals(loaded, MSUMI, date(2026, 10, 1), date(2026, 10, 21))
    assert [d.side for d, _ in rows] == ["BUY", "SELL"]  # larger first within the day
    assert rows[0][1] == pytest.approx(5_200_000 / volume.volume)
    frame = queries.deals(loaded, MSUMI)
    assert list(frame["quantity"]) == [5_200_000, 5_000_000]


@pytest.mark.db
def test_cli_load_and_list(loaded, test_database_url, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app
    from stock_news_analyzer.config import get_settings

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    runner = CliRunner()
    result = runner.invoke(
        app, ["deals", "load", str(FIXTURES / "nse_block_deals.csv"), "--kind", "block"]
    )
    assert result.exit_code == 0 and "1 block deals read, 1 new" in result.stdout
    result = runner.invoke(app, ["deals", "list", "LT", "--days", "36500"])
    assert "block BUY     1,500,000" in result.stdout and "EXAMPLE PENSION FUND" in result.stdout
