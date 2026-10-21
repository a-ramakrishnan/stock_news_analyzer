"""Command-line entry point: `sna <command>`."""

import logging

import typer
from sqlalchemy.exc import OperationalError

from stock_news_analyzer import __version__
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import check_database, get_engine

app = typer.Typer(help="Stock news analyzer for Indian stocks and bullion.", no_args_is_help=True)


@app.callback()
def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def health() -> None:
    """Check that settings load, the data folder is writable and the database is reachable."""
    settings = get_settings()
    ok = True

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"data dir     ok  {settings.data_dir.resolve()}")
    typer.echo(f"timezone     ok  {settings.timezone}")

    try:
        db = check_database(get_engine())
        typer.echo(f"postgres     ok  {db.server_version}")
        if db.pgvector_version:
            typer.echo(f"pgvector     ok  {db.pgvector_version}")
        else:
            typer.echo("pgvector     MISSING  run: CREATE EXTENSION vector;")
            ok = False
    except OperationalError as exc:
        typer.echo(f"postgres     FAILED  {exc.orig}")
        typer.echo("             is the database running? try: make up")
        ok = False

    raise typer.Exit(code=0 if ok else 1)
