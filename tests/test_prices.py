import gzip
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import FIXTURES

from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import (
    Document,
    DocumentCompany,
    EventLabel,
    IndexDaily,
    PriceDaily,
    StockMove,
)
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.prices import parse_full_bhavcopy, parse_index_close
from stock_news_analyzer.sources.securities import parse_bse_scrips, parse_nse_equity_list

REPO = Path(__file__).parent.parent

# The LT and Nifty 50 rows in the fixtures are NSE's real values for 16, 19 and 21 Oct 2026
# (20 Oct was a holiday). The other stocks' and the sector indices' rows are made up.


def test_parse_full_bhavcopy():
    rows = parse_full_bhavcopy((FIXTURES / "sec_bhavdata_full_16102026.csv").read_text())
    lt = next(r for r in rows if r.symbol == "LT")
    assert lt.series == "EQ" and lt.trade_date == date(2026, 10, 16)
    assert (lt.prev_close, lt.close) == (Decimal("3632.00"), Decimal("3627.10"))
    assert lt.volume == 1875108 and lt.delivery_pct == Decimal("61.21")
    bond = next(r for r in rows if r.series == "GB")
    assert bond.delivery_qty is None and bond.delivery_pct is None  # '-' in the file


def test_parse_index_close():
    rows = parse_index_close((FIXTURES / "ind_close_all_19102026.csv").read_text())
    nifty = next(r for r in rows if r.index_name == "Nifty 50")
    assert nifty.trade_date == date(2026, 10, 19)
    assert nifty.close == Decimal("22888.95") and nifty.pe == Decimal("19.33")


def test_weekdays_skip_weekends():
    assert list(pr.weekdays(date(2026, 10, 16), date(2026, 10, 19))) == [
        date(2026, 10, 16),
        date(2026, 10, 19),
    ]


@pytest.mark.parametrize(
    "published, expected",
    [
        (datetime(2026, 10, 19, 9, 45), date(2026, 10, 19)),  # during market hours
        (datetime(2026, 10, 19, 15, 29), date(2026, 10, 19)),
        (datetime(2026, 10, 19, 15, 30), date(2026, 10, 21)),  # after close; 20th a holiday
        (datetime(2026, 10, 17, 11, 0), date(2026, 10, 19)),  # Saturday
        (datetime(2026, 9, 1, 11, 0), None),  # before the stored price history
        (datetime(2026, 10, 22, 11, 0), None),  # no trading day stored yet
    ],
)
def test_first_trading_day(published, expected):
    calendar = [date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 21)]
    assert pr.first_trading_day(published.replace(tzinfo=IST), calendar) == expected


# --- collecting from NSE files -----------------------------------------------


class FakeNSE:
    """Serves the fixture files by URL; 20 Oct behaves like NSE on a holiday."""

    def __init__(self):
        self.urls = []

    def nse_file(self, url):
        self.urls.append(url)
        name = url.rsplit("/", 1)[1]
        if name == "sec_bhavdata_full_20102026.csv":
            name = "sec_bhavdata_full_19102026.csv"  # previous day's file under today's name
        path = FIXTURES / name
        return path.read_bytes() if path.exists() else None


@pytest.fixture
def watchlist(session):
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        bse=parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    wl.load_file(session, FIXTURES / "watchlist.yaml")
    return session


@pytest.mark.db
def test_collect_loads_trading_days_and_skips_the_holiday(watchlist, tmp_path):
    client = FakeNSE()
    result = pr.PriceCollector(watchlist, client, tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21)
    )
    assert (result.days, result.holidays, result.errors) == (3, 1, [])
    assert not any("17102026" in u or "18102026" in u for u in client.urls)  # weekend

    lt = watchlist.query(PriceDaily).filter_by(symbol="LT").order_by(PriceDaily.trade_date).all()
    assert [p.trade_date.day for p in lt] == [16, 19, 21]
    assert lt[0].isin == "INE018A01030"
    bond = watchlist.query(PriceDaily).filter_by(series="GB").one()
    assert bond.isin is None  # not the company's ordinary shares
    assert watchlist.query(IndexDaily).filter_by(index_name="Nifty 50").count() == 3
    raw = tmp_path / "prices" / "2026" / "sec_bhavdata_full_20261016.csv.gz"
    assert gzip.decompress(raw.read_bytes()).startswith(b"SYMBOL, SERIES")

    again = pr.PriceCollector(watchlist, client, tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21)
    )
    assert again.days == 3 and watchlist.query(PriceDaily).filter_by(symbol="LT").count() == 3


@pytest.mark.db
def test_moves_use_real_lt_and_nifty_values(watchlist, tmp_path):
    pr.PriceCollector(watchlist, FakeNSE(), tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21)
    )
    assert pr.compute_moves(watchlist) == []
    move = watchlist.get(StockMove, ("INE018A01030", date(2026, 10, 19)))
    assert move.stock_return == pytest.approx(3661.90 / 3627.10 - 1)  # +0.96%
    assert move.nifty_return == pytest.approx(22888.95 / 23146.15 - 1)  # -1.11%
    assert move.excess_return == pytest.approx(0.020706, abs=1e-6)
    assert move.sector_index == "Nifty Infrastructure"
    assert move.sector_return == pytest.approx(8740 / 8830 - 1)
    assert move.zscore is None and not move.unusual  # too little history to judge
    first = watchlist.get(StockMove, ("INE018A01030", date(2026, 10, 16)))
    assert first.nifty_return is None  # no earlier Nifty close stored


@pytest.mark.db
def test_unknown_sector_index_is_reported(watchlist, tmp_path):
    wl.add_equity(watchlist, wl.resolve(watchlist, "LT"), owned=True, sector_index="Nifty Nope")
    pr.PriceCollector(watchlist, FakeNSE(), tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21)
    )
    assert pr.compute_moves(watchlist) == ["LT: sector index 'Nifty Nope' not in NSE's file"]


# --- unusual moves and labels on a generated series ---------------------------


def _trading_days(n):
    days, d = [], date(2026, 6, 1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _load_series(session, days, big_day):
    """Nifty rises 0.1% a day; KVB beats it by +/-0.5% alternately, and by 5% on `big_day`."""
    nifty, stock = 20000.0, 200.0
    for i, d in enumerate(days):
        if i:
            nifty_r = 0.001
            excess = 0.05 if i == big_day else (0.005 if i % 2 else -0.005)
            prev_stock, stock = stock, stock * (1 + nifty_r + excess)
            nifty *= 1 + nifty_r
        else:
            prev_stock = stock
        session.add(IndexDaily(index_name="Nifty 50", trade_date=d, close=Decimal(f"{nifty:.2f}")))
        session.add(
            PriceDaily(
                symbol="KARURVYSYA",
                series="EQ",
                trade_date=d,
                isin="INE036D01028",
                prev_close=Decimal(f"{prev_stock:.4f}"),
                close=Decimal(f"{stock:.4f}"),
            )
        )
    session.commit()


@pytest.mark.db
def test_unusual_day_is_flagged(watchlist):
    days = _trading_days(40)
    _load_series(watchlist, days, big_day=30)
    pr.compute_moves(watchlist)
    unusual = watchlist.query(StockMove).filter_by(isin="INE036D01028", unusual=True).all()
    assert [m.trade_date for m in unusual] == [days[30]]
    assert unusual[0].zscore == pytest.approx(10, rel=0.05)  # 5% vs a usual 0.5%
    assert unusual[0].sector_return is None  # Nifty Bank not in this generated data


@pytest.mark.db
def test_labels_measure_returns_after_the_news(watchlist):
    days = _trading_days(40)
    _load_series(watchlist, days, big_day=30)
    kvb = "INE036D01028"
    published = {
        "before_close": datetime.combine(days[30], datetime.min.time()).replace(
            hour=11, tzinfo=IST
        ),
        "after_close": datetime.combine(days[29], datetime.min.time()).replace(hour=17, tzinfo=IST),
        "too_recent": datetime.combine(days[35], datetime.min.time()).replace(hour=10, tzinfo=IST),
    }
    ids = {}
    for key, when in published.items():
        doc = Document(
            source="test", source_id=key, doc_type="results", title=key, published_at=when, raw={}
        )
        watchlist.add(doc)
        watchlist.flush()
        watchlist.add(DocumentCompany(document_id=doc.id, isin=kvb))
        ids[key] = doc.id
    watchlist.commit()

    written, complete = pr.update_labels(watchlist)
    assert (written, complete) == (3, 0)  # 20-day windows haven't finished for any of them

    before = watchlist.get(EventLabel, (ids["before_close"], kvb))
    assert before.day0 == days[30]
    assert before.excess_1d == pytest.approx(0.05, abs=1e-3)  # the 5% jump day itself
    assert before.excess_5d is not None and before.excess_20d is None
    after = watchlist.get(EventLabel, (ids["after_close"], kvb))
    assert after.day0 == days[30]  # published after 15:30, so the next day counts
    recent = watchlist.get(EventLabel, (ids["too_recent"], kvb))
    assert recent.excess_1d is not None and recent.excess_5d is not None  # days 35..39
    assert recent.excess_20d is None and not recent.complete


@pytest.mark.db
def test_complete_labels_are_not_recomputed(watchlist):
    days = _trading_days(40)
    _load_series(watchlist, days, big_day=30)
    doc = Document(
        source="test",
        source_id="early",
        doc_type="news",
        title="early",
        published_at=datetime.combine(days[2], datetime.min.time()).replace(hour=10, tzinfo=IST),
        raw={},
    )
    watchlist.add(doc)
    watchlist.flush()
    watchlist.add(DocumentCompany(document_id=doc.id, isin="INE036D01028"))
    watchlist.commit()
    assert pr.update_labels(watchlist) == (1, 1)
    assert pr.update_labels(watchlist) == (0, 0)


@pytest.mark.db
def test_cli_moves_and_labels(watchlist, tmp_path, test_database_url, monkeypatch):
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app

    monkeypatch.setenv("DATABASE_URL", test_database_url)  # before settings are first read
    pr.PriceCollector(watchlist, FakeNSE(), tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21)
    )
    pr.compute_moves(watchlist)
    runner = CliRunner()
    result = runner.invoke(app, ["prices", "moves", "LT", "--days", "5"])
    assert result.exit_code == 0, result.stdout
    line = next(row for row in result.stdout.splitlines() if "2026-10-19" in row)
    assert line.split()[1:6] == ["+0.96%", "-1.11%", "-1.02%", "+2.07%", "+1.98%"]
    result = runner.invoke(app, ["prices", "indices", "bank"])
    assert "Nifty Bank" in result.stdout
    result = runner.invoke(app, ["labels", "update"])
    assert result.exit_code == 0 and "labels computed" in result.stdout


@pytest.mark.db
def test_progress_and_skipping_stored_days(watchlist, tmp_path):
    lines = []
    collector = pr.PriceCollector(watchlist, FakeNSE(), tmp_path)
    collector.collect(
        date(2026, 10, 16),
        date(2026, 10, 19),
        progress=lambda done, total, day, status, eta: lines.append((done, total, day, status)),
    )
    assert lines[0][:3] == (1, 2, date(2026, 10, 16)) and lines[0][3].startswith("loaded ")

    client = FakeNSE()
    result = pr.PriceCollector(watchlist, client, tmp_path).collect(
        date(2026, 10, 16), date(2026, 10, 21), skip_stored=True
    )
    assert (result.already_stored, result.days, result.holidays) == (2, 1, 1)
    assert not any("16102026" in u or "19102026" in u for u in client.urls)
