"""Command-line entry point: `sna <command>`."""

import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import typer
from sqlalchemy.exc import OperationalError

from stock_news_analyzer import __version__
from stock_news_analyzer.agents import filings as fl
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import check_database, get_engine, get_session, upgrade_database
from stock_news_analyzer.sources import securities

app = typer.Typer(help="Stock news analyzer for Indian stocks and bullion.", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance.", no_args_is_help=True)
securities_app = typer.Typer(help="Master list of NSE/BSE securities.", no_args_is_help=True)
watchlist_app = typer.Typer(help="Stocks and bullion you track.", no_args_is_help=True)
news_app = typer.Typer(help="News articles from RSS feeds and Google News.", no_args_is_help=True)
filings_app = typer.Typer(
    help="Exchange filings (BSE and NSE announcements).", no_args_is_help=True
)
app.add_typer(db_app, name="db")
app.add_typer(filings_app, name="filings")
app.add_typer(news_app, name="news")
app.add_typer(securities_app, name="securities")
app.add_typer(watchlist_app, name="watchlist")


@app.callback()
def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # pypdf warns about every small defect in exchange PDFs; real failures are still reported.
    logging.getLogger("pypdf").setLevel(logging.ERROR)


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
    alias: list[str] = typer.Option(None, "--alias", help="Other name used in news, e.g. L&T."),
) -> None:
    """Add a stock or bullion to the watchlist (or update it if already there)."""
    qty = Decimal(str(quantity)) if quantity is not None else None
    with get_session() as session:
        if name.strip().lower() in wl.COMMODITIES:
            item = wl.add_commodity(session, name, owned=owned, quantity=qty)
            typer.echo(f"tracking {item.display_name}{' (owned)' if owned else ''}")
            return
        company = _resolve_or_exit(session, name)
        wl.add_equity(session, company, owned=owned, quantity=qty, notes=notes, aliases=alias)
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
            mcap = f"Rs {p.market_cap_cr:,.0f} cr" if p.market_cap_cr is not None else ""
            typer.echo(f"  {p.nse_symbol or '-':<12} {mcap:>18}  {p.name}")


# --- filings -----------------------------------------------------------------


def _collector(session, pdf: str) -> fl.FilingsCollector:
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    return fl.FilingsCollector(session, ExchangeClient(), get_settings().data_dir, pdf_policy=pdf)


def _companies_or_exit(session, symbol: str | None):
    companies = fl.watchlist_companies(session, symbol)
    if not companies:
        typer.echo(f"{symbol} is not on the watchlist" if symbol else "watchlist is empty")
        raise typer.Exit(1)
    return companies


def _report(result: fl.CollectResult) -> None:
    typer.echo(
        f"{result.new} new filings, {result.already_had} already stored, "
        f"{result.attachments} attachments downloaded"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@filings_app.command("fetch")
def filings_fetch(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: whole watchlist)."),
    days: int = typer.Option(7, help="How far back to look the first time a company is fetched."),
    source: str = typer.Option("both", help="bse, nse or both."),
    pdf: str = typer.Option("all", help="Attachments to download: all, important or none."),
) -> None:
    """Fetch new announcements since the last run."""
    sources = fl.SOURCES if source == "both" else (source,)
    with get_session() as session:
        companies = _companies_or_exit(session, symbol)
        result = _collector(session, pdf).collect(companies, default_days=days, sources=sources)
    _report(result)


@filings_app.command("backfill")
def filings_backfill(
    since: str = typer.Option(..., help="Start date, YYYY-MM-DD (e.g. 2023-10-01)."),
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: whole watchlist)."),
    source: str = typer.Option("both", help="bse, nse or both."),
    pdf: str = typer.Option(
        "important", help="all, important (results, concalls, orders, ratings) or none."
    ),
) -> None:
    """Fetch the full history from a start date. Safe to re-run; stored filings are skipped."""
    start = datetime.strptime(since, "%Y-%m-%d").date()
    sources = fl.SOURCES if source == "both" else (source,)
    with get_session() as session:
        companies = _companies_or_exit(session, symbol)
        result = _collector(session, pdf).collect(companies, start=start, sources=sources)
    _report(result)


@filings_app.command("attachments")
def filings_attachments(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    pdf: str = typer.Option("all", help="all or important."),
    limit: int = typer.Option(200, help="Maximum files to download this run."),
    retry_failed: bool = typer.Option(False, help="Also re-download files whose PDF failed."),
) -> None:
    """Download attachments that were skipped or failed earlier."""
    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        count = _collector(session, pdf).fetch_missing_attachments(
            isin=isin, limit=limit, retry_failed=retry_failed
        )
    typer.echo(f"{count} attachments downloaded")


@filings_app.command("reclassify")
def filings_reclassify() -> None:
    """Recompute filing types and clean titles from the stored raw records (after rule changes)."""
    with get_session() as session:
        changed = fl.reclassify(session)
    typer.echo(f"{changed} filings updated")


@filings_app.command("list")
def filings_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist companies)."),
    doc_type: str = typer.Option(
        None, "--type", help="e.g. order_win, results, concall_transcript"
    ),
    limit: int = typer.Option(20, help="How many to show."),
) -> None:
    """Show the latest stored filings."""
    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        rows = fl.recent_documents(session, isin=isin, doc_type=doc_type, limit=limit)
        if not rows:
            typer.echo("no filings stored yet; run: sna filings fetch")
            return
        for doc, company in rows:
            when = doc.published_at.astimezone(fl.IST).strftime("%Y-%m-%d %H:%M")
            text = {
                "ok": "text",
                "partial": "partial",
                "empty": "no text",
                "failed": "pdf failed",
            }.get(doc.text_status, "-")
            typer.echo(
                f"{doc.id:>6}  {when}  {doc.source.upper()}  {company.nse_symbol or '-':<11} "
                f"{doc.doc_type:<21} {text:<10} {doc.title[:70]}"
            )


@filings_app.command("show")
def filings_show(
    doc_id: int = typer.Argument(..., help="Filing id from `sna filings list`."),
    chars: int = typer.Option(1500, help="How much of the extracted text to print."),
) -> None:
    """Show one filing: details, file location and the start of its text."""
    from stock_news_analyzer.models import Document

    with get_session() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            typer.echo(f"no filing with id {doc_id}")
            raise typer.Exit(1)
        typer.echo(f"{doc.title}\n{doc.subject}")
        typer.echo(f"source     {doc.source.upper()} {doc.source_id}")
        typer.echo(f"type       {doc.doc_type}")
        typer.echo(f"published  {doc.published_at.astimezone(fl.IST):%Y-%m-%d %H:%M:%S} IST")
        typer.echo(f"first seen {doc.first_seen_at.astimezone(fl.IST):%Y-%m-%d %H:%M:%S} IST")
        typer.echo(f"file       {doc.attachment_path or doc.attachment_url or '-'}")
        typer.echo(f"text       {doc.text_status}\n")
        if doc.text:
            typer.echo(doc.text[:chars])


# --- news --------------------------------------------------------------------

FEEDS_FILE = Path("config/news_feeds.yaml")


def _news_config(path: Path):
    from stock_news_analyzer.sources.news import load_feed_config

    return load_feed_config(path)


@news_app.command("check-feeds")
def news_check_feeds(
    feeds_file: Path = typer.Option(FEEDS_FILE, help="Feed list (YAML)."),
) -> None:
    """Fetch every configured feed once and report which work."""
    from stock_news_analyzer.agents.news import check_feeds
    from stock_news_analyzer.sources.news import NewsClient

    failed = 0
    for key, url, items, error in check_feeds(NewsClient(), _news_config(feeds_file)):
        if error:
            failed += 1
            typer.echo(f"FAIL  {key:<24} {error}  {url}")
        else:
            typer.echo(f"ok    {key:<24} {items:>3} items")
    if failed:
        typer.echo(f"{failed} feed(s) failed; fix or remove them in {feeds_file}")
        raise typer.Exit(1)


@news_app.command("fetch")
def news_fetch(
    feed: list[str] = typer.Option(None, "--feed", help="Only these feed keys."),
    google: bool = typer.Option(True, help="Also search Google News per company."),
    feeds_file: Path = typer.Option(FEEDS_FILE, help="Feed list (YAML)."),
) -> None:
    """Read the feeds and store articles that mention a watchlist company."""
    from stock_news_analyzer.agents.news import NewsCollector
    from stock_news_analyzer.sources.news import NewsClient

    with get_session() as session:
        if not fl.watchlist_companies(session):
            typer.echo("watchlist is empty")
            raise typer.Exit(1)
        result = NewsCollector(session, NewsClient(), _news_config(feeds_file)).collect(
            feed_keys=feed or None, google=google
        )
    typer.echo(
        f"{result.seen} articles read from {len(result.feeds)} feeds; "
        f"{result.matched} mention a watchlist company; {result.new} new"
    )
    for report in result.errors:
        typer.echo(f"error: {report.key}: {report.error}")


@news_app.command("list")
def news_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist companies)."),
    limit: int = typer.Option(20, help="How many to show."),
) -> None:
    """Show the latest stored news articles."""
    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        rows = fl.recent_documents(session, isin=isin, doc_type="news", limit=limit)
        if not rows:
            typer.echo("no news stored yet; run: sna news fetch")
            return
        for doc, company in rows:
            when = doc.published_at.astimezone(fl.IST).strftime("%Y-%m-%d %H:%M")
            publisher = (doc.publisher or "-")[:18]
            typer.echo(
                f"{doc.id:>6}  {when}  {company.nse_symbol or '-':<11} {publisher:<18} "
                f"{doc.title[:80]}"
            )
