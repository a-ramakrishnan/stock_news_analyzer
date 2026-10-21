from pathlib import Path

from stock_news_analyzer.config import Settings


def test_defaults_point_at_local_docker_database():
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://sna:sna@localhost:5433/sna"
    assert settings.timezone == "Asia/Kolkata"
    assert settings.data_dir == Path("data")


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@example:5432/other")
    monkeypatch.setenv("DATA_DIR", "/tmp/sna-data")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://u:p@example:5432/other"
    assert settings.data_dir == Path("/tmp/sna-data")
