import pytest
from typer.testing import CliRunner

from stock_news_analyzer import __version__
from stock_news_analyzer.cli import app

runner = CliRunner()


def test_version_prints_package_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_health_fails_cleanly_when_database_is_down(monkeypatch, tmp_path):
    # Port 1 is never a Postgres server, so the connection is refused straight away.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://sna:sna@localhost:1/sna")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 1
    assert "postgres     FAILED" in result.stdout
    assert (tmp_path / "data").is_dir()


@pytest.mark.db
def test_health_passes_against_running_database(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0, result.stdout
    assert "pgvector     ok" in result.stdout
