import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import FIXTURES

from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import CorporateAction, IndexDaily, PriceDaily, StockMove
from stock_news_analyzer.sources.corporate_actions import classify_action, parse_corporate_actions
from stock_news_analyzer.sources.securities import parse_bse_scrips, parse_nse_equity_list

REPO = Path(__file__).parent.parent
ACTIONS = json.loads((FIXTURES / "nse_corporate_actions.json").read_text())  # NSE live, Oct 2026


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Bonus 1:2", ("bonus", 2 / 3, None)),
        ("Bonus 1:5", ("bonus", 5 / 6, None)),
        (
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
            ("split", 0.2, None),
        ),
        (
            "Consolidation Of Shares From Rs 1/- Per Share To Rs 10/- Per Share",
            ("consolidation", 10.0, None),
        ),
        ("Annual General Meeting/Dividend - Re 0.80 Per Share", ("dividend", 1.0, Decimal("0.80"))),
        (
            "Interim Dividend - Rs 5 Per Share / Special Dividend - Rs 10 Per Share",
            ("dividend", 1.0, Decimal("15")),
        ),
        ("Rights 1:5 @ Premium Rs 100/-", ("rights", 1.0, None)),
        ("Annual General Meeting", ("other", 1.0, None)),
    ],
)
def test_classify_action(subject, expected):
    kind, factor, dividend = classify_action(subject)
    assert (kind, dividend) == (expected[0], expected[2])
    assert factor == pytest.approx(expected[1])


def test_parse_live_records():
    actions = parse_corporate_actions(ACTIONS)
    bonus = next(a for a in actions if a.kind == "bonus" and a.symbol == "MSUMI")
    assert bonus.ex_date == date(2025, 7, 18) and bonus.price_factor == pytest.approx(2 / 3)
    kvb = next(a for a in actions if a.symbol == "KARURVYSYA")
    assert kvb.isin == "INE036D01010"  # NSE's record carries an older ISIN: match on symbol
    assert parse_corporate_actions({"data": ACTIONS[:1]})[0].dividend == Decimal("0.80")


class FakeNSE:
    def nse_corporate_actions(self, symbol, start, end):
        return [a for a in ACTIONS if a["symbol"] == symbol]


@pytest.fixture
def watchlist(session):
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        bse=parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    wl.load_file(session, FIXTURES / "watchlist.yaml")
    return session


def _prices(session, symbol, isin, rows):
    for d, prev, close in rows:
        session.add(
            PriceDaily(
                symbol=symbol,
                series="EQ",
                trade_date=d,
                isin=isin,
                prev_close=Decimal(prev),
                close=Decimal(close),
            )
        )
    session.commit()


@pytest.mark.db
def test_bonus_ex_date_is_not_a_crash(watchlist):
    # MSUMI's stored rows around its 1:2 bonus (ex-date 18 Jul 2025), from NSE's bhavcopy.
    _prices(
        watchlist,
        "MSUMI",
        "INE0FS801015",
        [
            (date(2025, 7, 17), "64.50", "64.47"),
            (date(2025, 7, 18), "64.47", "43.52"),
            (date(2025, 7, 21), "43.52", "43.81"),
        ],
    )
    assert pr.stock_returns(watchlist, "INE0FS801015", "MSUMI")[date(2025, 7, 18)] == (
        pytest.approx(-0.325, abs=1e-3)  # unadjusted: the fake crash
    )
    assert (
        pr.refresh_corporate_actions(watchlist, FakeNSE(), date(2023, 10, 1), date(2026, 10, 21))
        == []
    )
    assert watchlist.query(CorporateAction).filter_by(symbol="MSUMI").count() == 5
    returns = pr.stock_returns(watchlist, "INE0FS801015", "MSUMI")
    assert returns[date(2025, 7, 18)] == pytest.approx(43.52 / (64.47 * 2 / 3) - 1)  # +1.26%
    assert returns[date(2025, 7, 21)] == pytest.approx(43.81 / 43.52 - 1)  # untouched


@pytest.mark.db
def test_dividend_is_added_back(watchlist):
    pr.refresh_corporate_actions(watchlist, FakeNSE(), date(2023, 10, 1), date(2026, 10, 21))
    _prices(watchlist, "LT", "INE018A01030", [(date(2025, 6, 3), "3600.00", "3570.00")])
    # L&T went ex-dividend Rs 34 on 3 Jun 2025: a 0.83% drop that is not a loss.
    assert pr.stock_returns(watchlist, "INE018A01030", "LT")[date(2025, 6, 3)] == (
        pytest.approx(3570 / (3600 - 34) - 1)
    )


@pytest.mark.db
def test_threshold_setting_controls_unusual_days(watchlist, monkeypatch):
    days = [
        date(2026, 6, d)
        for d in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19, 22, 23, 24, 25, 26, 29, 30)
    ] + [date(2026, 7, 1)]
    stock, nifty = 100.0, 1000.0
    for i, d in enumerate(days):
        prev = stock
        if i:
            stock *= 1 + (0.03 if i == len(days) - 1 else (0.01 if i % 2 else -0.01))
        watchlist.add(IndexDaily(index_name="Nifty 50", trade_date=d, close=Decimal(nifty)))
        watchlist.add(
            PriceDaily(
                symbol="KARURVYSYA",
                series="EQ",
                trade_date=d,
                isin="INE036D01028",
                prev_close=Decimal(f"{prev:.4f}"),
                close=Decimal(f"{stock:.4f}"),
            )
        )
    watchlist.commit()

    pr.compute_moves(watchlist, threshold=2.0)
    last = watchlist.get(StockMove, ("INE036D01028", days[-1]))
    assert last.zscore == pytest.approx(3.0, rel=0.05) and last.unusual
    pr.compute_moves(watchlist, threshold=3.5)
    watchlist.refresh(last)
    assert not last.unusual
