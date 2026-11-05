from datetime import datetime
from decimal import Decimal

import pytest
from test_prices import _load_series, _trading_days, watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import portfolio as pf
from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import study
from stock_news_analyzer.models import Company, IndexMember, RedFlag, WatchlistItem
from stock_news_analyzer.sources.announcements import IST

KVB = "INE036D01028"
LT = "INE018A01030"


def test_lean_from_the_score_and_red_flags():
    high = RedFlag(severity="high")
    assert pf.lean_of(0.02, []) == "positive"
    assert pf.lean_of(0.02, [high]) == "neutral"  # an open high-severity flag holds it back
    assert pf.lean_of(-0.02, []) == "negative"
    assert pf.lean_of(0.005, []) == "neutral"


@pytest.mark.db
def test_holdings_weigh_recent_events_by_the_evidence(watchlist, monkeypatch):  # noqa: F811
    days = _trading_days(40)
    _load_series(watchlist, days, big_day=30)  # KVB beats the Nifty by 5% on day 30
    pr.compute_moves(watchlist)
    s = watchlist
    s.query(WatchlistItem).filter_by(isin=KVB).update({"owned": True, "quantity": Decimal(10)})
    s.commit()
    today = days[-1]

    def case(kind, isin, day, move):
        c = study.Case(
            "Order wins",
            kind,
            isin,
            "X",
            datetime.combine(day, datetime.min.time()).replace(hour=10, tzinfo=IST),
            f"{kind} on {day}",
        )
        c.day0, c.excess = day, {pf.HORIZON: move}
        return c

    large = "Order win: large (5%+ of a year's revenue)"
    small = "Order win: small (under 1% of a year's revenue)"
    # Evidence: 10 large order wins elsewhere that rose 3% (median), 4 small ones that fell 2%.
    others = [case(large, LT, days[0], 0.03) for _ in range(10)]
    others += [case(small, LT, days[0], -0.02) for _ in range(4)]
    mine = [case(large, KVB, days[30], None), case(small, KVB, days[35], None)]
    monkeypatch.setattr(study, "all_cases", lambda session: others + mine)

    [h] = pf.holdings(s, today=today)
    assert h.symbol == "KARURVYSYA" and h.quantity == 10 and h.value == pytest.approx(10 * h.close)
    big, little = h.reasons  # strongest contribution first
    assert big.case.kind == large and big.median == pytest.approx(0.03) and big.cases == 10
    age = (today - days[30]).days
    assert big.weight == pytest.approx(0.5 ** (age / pf.HALF_LIFE))  # full evidence, decayed
    assert little.weight == pytest.approx(0.4 * 0.5 ** ((today - days[35]).days / pf.HALF_LIFE))
    assert big.since == pytest.approx(0.05, abs=0.02)  # the 5% jump came after it
    assert h.score == pytest.approx(big.contribution + little.contribution)
    assert h.lean == "positive"

    s.add(
        RedFlag(isin=KVB, kind="pledge", severity="high", title="Pledge", flagged_on=today, ref="t")
    )
    s.commit()
    [h] = pf.holdings(s, today=today)
    assert h.lean == "neutral" and len(h.flags) == 1


@pytest.mark.db
def test_sector_weights_against_the_nifty(watchlist):  # noqa: F811
    s = watchlist
    lt, kvb = s.get(Company, LT), s.get(Company, KVB)
    lt.industry, lt.market_cap_cr = "Construction", Decimal(300)
    kvb.industry, kvb.market_cap_cr = "Financial Services", Decimal(100)
    s.add(IndexMember(index_name="Nifty 50", isin=LT, symbol="LT", industry="Construction"))
    s.add(IndexMember(index_name="Nifty 50", isin=KVB, symbol="KVB", industry="Financial Services"))
    s.commit()
    held = [
        pf.Holding(KVB, "KVB", "", 10, 100.0, 1000.0, "Financial Services", "neutral", 0.0),
        pf.Holding(LT, "LT", "", 1, 3000.0, 3000.0, "Construction", "neutral", 0.0),
    ]
    rows = {r["industry"]: r for r in pf.sector_weights(s, held)}
    assert rows["Construction"]["mine"] == pytest.approx(0.75)
    assert rows["Construction"]["nifty"] == pytest.approx(0.75)
    assert rows["Financial Services"]["mine"] == pytest.approx(0.25)
    # Without values, each holding counts equally.
    for h in held:
        h.value = None
    rows = {r["industry"]: r for r in pf.sector_weights(s, held)}
    assert rows["Construction"]["mine"] == pytest.approx(0.5)
