from datetime import date

import pytest
from test_orchestrator import loaded  # noqa: F401  (fixture)

from stock_news_analyzer.agents import setup
from stock_news_analyzer.models import WatchlistItem

LT = "INE018A01030"


@pytest.mark.db
def test_a_new_copy_needs_setup_until_finished(session):
    assert setup.needs_setup(session)
    setup.finish(session)
    assert not setup.needs_setup(session)


@pytest.mark.db
def test_a_copy_with_stocks_never_sees_setup(loaded):  # noqa: F811
    assert not setup.needs_setup(loaded)


@pytest.mark.db
def test_a_started_setup_stays_on_after_stocks_are_added(loaded):  # noqa: F811
    # Run again from Settings, or started on a new copy and the first stock added: the
    # setup stays on until finished, also after a browser reload.
    setup.start(loaded)
    assert setup.needs_setup(loaded)
    setup.finish(loaded)
    assert not setup.needs_setup(loaded)


@pytest.mark.db
def test_examples_and_company_list(loaded):  # noqa: F811
    assert not setup.has_companies(loaded)  # a handful, not a downloaded list
    loaded.query(WatchlistItem).filter(WatchlistItem.kind == "equity").delete()
    loaded.commit()
    # Only L&T of the examples is among the fixture's companies.
    assert setup.add_examples(loaded) == ["Larsen & Toubro Limited"]
    item = loaded.query(WatchlistItem).filter_by(isin=LT).one()
    assert not item.owned and item.aliases == ["L&T"]


def test_history_start():
    today = date(2026, 10, 28)
    assert setup.history_start("1 year", today) == date(2025, 10, 28)
    assert setup.history_start("Since October 2023", today) == date(2023, 10, 1)
    assert setup.history_start("2 years", date(2025, 1, 1)) == date(2023, 10, 1)  # not before


@pytest.mark.db
def test_load_prices_reports_progress(session, monkeypatch):
    from stock_news_analyzer.agents import prices

    def collect(self, start, end=None, skip_stored=False, progress=None):
        assert skip_stored and start == date(2026, 1, 1)
        for done in (1, 20, 21, 40):
            progress(done, 40, date(2026, 1, done % 28 + 1), "ok", 600)
        return prices.PriceResult()

    monkeypatch.setattr(prices.PriceCollector, "collect", collect)
    lines = []
    assert setup.load_prices(session, None, date(2026, 1, 1), lines.append, client=object()) == []
    assert (
        len(lines) == 3 and lines[0].startswith("Prices: day 1 of 40") and "10 min left" in lines[0]
    )
