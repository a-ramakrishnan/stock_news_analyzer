from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import get_engine, upgrade_database
from stock_news_analyzer.models import Base

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Settings are cached; clear the cache so each test sees its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine():
    """An engine for the configured database, or skip the test when Postgres is not running."""
    eng = get_engine()
    try:
        with eng.connect():
            pass
    except OperationalError:
        pytest.skip("Postgres is not reachable; start it with `make up`")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def test_database_url():
    """A separate `sna_test` database on the same server, rebuilt from migrations once per run.

    Tests that write data use this, so `make test` never touches your real watchlist.
    """
    url = make_url(get_settings().database_url)
    test_url = url.set(database=f"{url.database}_test")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": test_url.database}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    except OperationalError:
        pytest.skip("Postgres is not reachable; start it with `make up`")
    finally:
        admin.dispose()

    eng = create_engine(test_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    eng.dispose()

    rendered = test_url.render_as_string(hide_password=False)
    upgrade_database(rendered)
    return rendered


@pytest.fixture
def session(test_database_url):
    """A session on the test database; every table is emptied after each test."""
    eng = create_engine(test_database_url)
    with Session(eng) as s:
        yield s
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    eng.dispose()
