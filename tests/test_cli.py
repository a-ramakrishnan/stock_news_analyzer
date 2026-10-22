from pathlib import Path

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


@pytest.mark.db
def test_refresh_load_and_list_from_downloaded_files(session, test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    fixtures = Path(__file__).parent / "fixtures"
    result = runner.invoke(
        app,
        [
            "securities",
            "refresh",
            "--nse-file",
            str(fixtures / "EQUITY_L.csv"),
            "--nifty500-file",
            str(fixtures / "ind_nifty500list.csv"),
            "--bse-file",
            str(fixtures / "bse_scrips.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "loaded 9 NSE, 9 BSE, 8 Nifty 500 rows" in result.stdout

    result = runner.invoke(app, ["watchlist", "load", str(fixtures / "watchlist.yaml")])
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(app, ["watchlist", "list"])
    assert result.exit_code == 0
    assert "543498" in result.stdout and "Motherson Sumi Wiring India Limited" in result.stdout

    result = runner.invoke(app, ["watchlist", "add", "Bank"])
    assert result.exit_code == 1
    assert "could match more than one company" in result.stdout


@pytest.mark.db
def test_load_lists_candidates_for_ambiguous_entries(
    session, test_database_url, monkeypatch, tmp_path
):
    from stock_news_analyzer.agents import watchlist as wl
    from stock_news_analyzer.sources.securities import parse_nse_equity_list

    fixtures = Path(__file__).parent / "fixtures"
    wl.load_master(session, parse_nse_equity_list((fixtures / "EQUITY_L.csv").read_text()))
    session.commit()
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    f = tmp_path / "w.yaml"
    f.write_text("stocks:\n  - name: Bank\n  - name: LT\n")
    result = runner.invoke(app, ["watchlist", "load", str(f)])
    # Exit code 1 with the candidates listed; it used to crash after the session closed.
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.exception
    assert "tracking Larsen & Toubro Limited" in result.stdout
    assert "'Bank' could match more than one company" in result.stdout
    assert "KARURVYSYA" in result.stdout and "Add `symbol: <NSE SYMBOL>`" in result.stdout
