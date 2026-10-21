import pytest

from stock_news_analyzer.db import check_database

pytestmark = pytest.mark.db


def test_database_is_postgres_16_with_pgvector(engine):
    health = check_database(engine)
    assert health.server_version.startswith("16")
    assert health.pgvector_version is not None
