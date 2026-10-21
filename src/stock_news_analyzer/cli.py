"""Command-line entry point: `sna <command>`."""

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import typer
from sqlalchemy.exc import OperationalError

from stock_news_analyzer import __version__
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import check_database, get_engine, get_session, upgrade_database
from stock_news_analyzer.sources import securities

app = typer.Typer(help="Stock news analyzer for Indian stocks and bullion.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
securities_app = typer.Typer(help="Master list of NSE/BSE securities.", no_args_is_help=True)
watchlist_app = typer.Typer(help="Stocks and bullion you track.", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(securities_app, name="securities")
app.add_typer(watchlist_app, name="watchlist")


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


# --- db ----------------------------------------------------------------------


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Create or update the database tables to the latest version."""
    upgrade_database()
    typer.echo("database is up to date")


# --- securities --------------------------------------------------------------


def _read_or_download(file: Path | None, url: str, save_as: str, referer: str | None = None) -> str:
    """Use a file you downloaded yourself, or download it and keep a dated raw copy."""
    if file is not None:
        return file.read_text(encoding="utf-8-sig")
    text = securities.download(url, referer=referer)
    raw_dir = get_settings().data_dir / "reference" / date.today().isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / save_as).write_text(text, encoding="utf-8")
    return text


@securities_app.command("refresh")
def securities_refresh(
    nse_file: Path = typer.Option(None, help="Use a downloaded copy of NSE's EQUITY_L.csv."),
    nifty500_file: Path = typer.Option(None, help="Use a downloaded ind_nifty500list.csv."),
    bse_file: Path = typer.Option(None, help="Use a saved copy of BSE's scrip list (JSON)."),
    skip_bse: bool = typer.Option(False, help="Don't fetch BSE codes this time."),
) -> None:
    """Download NSE and BSE security lists and update the master list."""
    try:
        nse = securities.parse_nse_equity_list(
            _read_or_download(nse_file, securities.NSE_EQUITY_LIST_URL, "EQUITY_L.csv")
        )
    except httpx.HTTPError as exc:
        typer.echo(f"NSE equity list download failed: {exc}")
        typer.echo(f"Download it in a browser from {securities.NSE_EQUITY_LIST_URL}")
        typer.echo("then run: sna securities refresh --nse-file ~/Downloads/EQUITY_L.csv")
        raise typer.Exit(1) from exc

    try:
        nifty500 = securities.parse_nifty500(
            _read_or_download(nifty500_file, securities.NIFTY500_URL, "ind_nifty500list.csv")
        )
    except httpx.HTTPError as exc:
        typer.echo(f"warning: Nifty 500 list download failed ({exc}); industries left blank")
        nifty500 = {}

    bse: list[securities.BseSecurity] = []
    if not skip_bse:
        try:
            bse = securities.parse_bse_scrips(
                _read_or_download(
                    bse_file,
                    securities.BSE_SCRIPS_URL,
                    "bse_scrips.json",
                    referer="https://www.bseindia.com/",
                )
            )
        except (httpx.HTTPError, ValueError) as exc:
            typer.echo(f"warning: BSE scrip list failed ({exc}); BSE codes left blank")

    with get_session() as session:
        result = wl.load_master(session, nse, nifty500, bse)
    typer.echo(
        f"loaded {result.nse} NSE, {result.bse} BSE, {result.nifty500} Nifty 500 rows; "
        f"{result.total} companies in the master list"
    )


# --- watchlist ---------------------------------------------------------------


def _print_candidates(exc: wl.ResolveError) -> None:
    if isinstance(exc, wl.NotFound):
        typer.echo(f"No listed company matches '{exc.query}'.")
        typer.echo("Is the master list loaded? Run: sna securities refresh")
        return
    typer.echo(f"'{exc.query}' could match more than one company:")
    for m in exc.candidates:
        c = m.company
        typer.echo(f"  {c.nse_symbol or '-':<12} {c.bse_code or '-':<8} {m.score:>5.0f}  {c.name}")
    typer.echo("Run again with the NSE symbol, e.g. sna watchlist add <SYMBOL>")


def _resolve_or_exit(session, query: str):
    try:
        return wl.resolve(session, query)
    except wl.ResolveError as exc:
        _print_candidates(exc)
        raise typer.Exit(1) from exc


@watchlist_app.command("add")
def watchlist_add(
    name: str = typer.Argument(
        ..., help="Company name, NSE symbol, BSE code, ISIN, or gold/silver."
    ),
    owned: bool = typer.Option(False, "--owned", help="You hold this stock."),
    quantity: float = typer.Option(None, help="Number of shares (or grams of bullion)."),
    notes: str = typer.Option(None, help="Free-text notes."),
) -> None:
    """Add a stock or bullion to the watchlist (or update it if already there)."""
    qty = Decimal(str(quantity)) if quantity is not None else None
    with get_session() as session:
        if name.strip().lower() in wl.COMMODITIES:
            item = wl.add_commodity(session, name, owned=owned, quantity=qty)
            typer.echo(f"tracking {item.display_name}{' (owned)' if owned else ''}")
            return
        company = _resolve_or_exit(session, name)
        wl.add_equity(session, company, owned=owned, quantity=qty, notes=notes)
        typer.echo(
            f"tracking {company.name}  NSE {company.nse_symbol or '-'}  "
            f"BSE {company.bse_code or '-'}  ISIN {company.isin}"
            f"{'  (owned)' if owned else ''}"
        )


@watchlist_app.command("load")
def watchlist_load(
    path: Path = typer.Argument(Path("config/watchlist.yaml"), help="Watchlist YAML file."),
) -> None:
    """Add everything in a watchlist file. Safe to run again after editing the file."""
    with get_session() as session:
        result = wl.load_file(session, path)
        for item in result.added:
            typer.echo(f"tracking {item.display_name}{'  (owned)' if item.owned else ''}")
    for problem in result.problems:
        _print_candidates(problem)
    if result.problems:
        typer.echo("Add `symbol: <NSE SYMBOL>` to those entries in the file and run again.")
        raise typer.Exit(1)


@watchlist_app.command("list")
def watchlist_list() -> None:
    """Show the watchlist."""
    with get_session() as session:
        rows = wl.list_items(session)
    if not rows:
        typer.echo("watchlist is empty; add with: sna watchlist load")
        return
    typer.echo(f"{'NSE':<12} {'BSE':<8} {'ISIN':<13} {'OWNED':<6} {'QTY':>8}  NAME / INDUSTRY")
    for item, c in rows:
        qty = f"{item.quantity:g}" if item.quantity is not None else "-"
        if c is None:
            typer.echo(
                f"{item.commodity:<12} {'-':<8} {'-':<13} {item.owned!s:<6} {qty:>8}  bullion"
            )
            continue
        industry = c.bse_industry or c.industry or "industry unknown"
        typer.echo(
            f"{c.nse_symbol or '-':<12} {c.bse_code or '-':<8} {c.isin:<13} "
            f"{item.owned!s:<6} {qty:>8}  {c.name} / {industry}"
        )


@watchlist_app.command("remove")
def watchlist_remove(
    key: str = typer.Argument(..., help="NSE symbol, ISIN, or gold/silver."),
) -> None:
    """Stop tracking a stock or bullion."""
    with get_session() as session:
        if wl.remove(session, key):
            typer.echo(f"removed {key}")
        else:
            typer.echo(f"{key} is not on the watchlist")
            raise typer.Exit(1)


@watchlist_app.command("peers")
def watchlist_peers(
    name: str = typer.Argument(..., help="Company name or NSE symbol."),
    approve: list[str] = typer.Option(None, "--approve", help="NSE symbol of a peer to save."),
) -> None:
    """Suggest peers from the same industry; save the ones you approve with --approve."""
    with get_session() as session:
        company = _resolve_or_exit(session, name)
        if approve:
            wl.approve_peers(session, company, [_resolve_or_exit(session, a) for a in approve])
        saved = wl.approved_peers(session, company)
        typer.echo(f"{company.name}: industry {company.bse_industry or company.industry or '-'}")
        if saved:
            typer.echo("approved peers: " + ", ".join(p.nse_symbol or p.name for p in saved))
        suggestions = [p for p in wl.suggest_peers(session, company) if p not in saved]
        if not suggestions:
            typer.echo("no further suggestions (industry unknown or no other companies in it)")
            return
        typer.echo("suggested peers (approve with --approve SYMBOL):")
        for p in suggestions:
            typer.echo(f"  {p.nse_symbol or '-':<12} {p.name}")
