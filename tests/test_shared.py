import importlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import Company

pytestmark = pytest.mark.db

shared = importlib.import_module("stock_news_analyzer.migrations.versions.0030_shared_views")


def _reader(test_database_url: str):
    url = make_url(test_database_url).set(username="research_reader", password="research_reader")
    return create_engine(url)


def test_every_shared_view_is_readable_by_the_reader_only(session, test_database_url):
    company = Company(isin="INE018A01030", name="Larsen & Toubro Limited", nse_symbol="LT")
    session.add(company)
    session.commit()
    wl.add_equity(session, company, owned=True)

    reader = _reader(test_database_url)
    with reader.connect() as conn:
        assert conn.execute(text("SELECT version FROM shared.contract")).scalar() == "1.0"
        for name in shared.VIEWS:
            conn.execute(text(f"SELECT * FROM shared.{name} LIMIT 1")).all()  # no error
        row = conn.execute(
            text("SELECT nse_symbol, owned, on_watchlist FROM shared.companies")
        ).one()
        assert tuple(row) == ("LT", True, True)
    with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("SELECT * FROM public.companies"))  # the tables themselves: no
    # A view over one table could be written through; the reader isn't allowed to.
    with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text("DELETE FROM shared.peers"))
    reader.dispose()
