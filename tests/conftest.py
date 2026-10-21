import pytest
from sqlalchemy.exc import OperationalError

from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import get_engine


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Settings are cached; clear the cache so each test sees its own environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine():
    """A database engine, or skip the test when Postgres is not running."""
    eng = get_engine()
    try:
        with eng.connect():
            pass
    except OperationalError:
        pytest.skip("Postgres is not reachable; start it with `make up`")
    yield eng
    eng.dispose()
