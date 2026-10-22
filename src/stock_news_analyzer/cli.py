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
prices_app = typer.Typer(
    help="NSE daily prices, index closes and unusual moves.", no_args_is_help=True
)
labels_app = typer.Typer(
    help="What each stock did after each filing and article.", no_args_is_help=True
)
app.add_typer(prices_app, name="prices")
app.add_typer(labels_app, name="labels")
orchestrator_app = typer.Typer(help="Run the jobs on a schedule.", no_args_is_help=True)
app.add_typer(orchestrator_app, name="orchestrator")
app.add_typer(securities_app, name="securities")
app.add_typer(watchlist_app, name="watchlist")
triage_app = typer.Typer(
    help="News triage (LLM): relevance, topic, sentiment, importance.", no_args_is_help=True
)
llm_app = typer.Typer(help="LLM usage and spending.", no_args_is_help=True)
explain_app = typer.Typer(
    help="Move Explainer (LLM): the likely cause of each unusual day.", no_args_is_help=True
)
app.add_typer(explain_app, name="explain")
app.add_typer(triage_app, name="triage")
app.add_typer(llm_app, name="llm")


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
    nse_sme_file: Path = typer.Option(None, help="Use a downloaded SME_EQUITY_L.csv (NSE Emerge)."),
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
        nse += securities.parse_nse_equity_list(
            _read_or_download(nse_sme_file, securities.NSE_SME_LIST_URL, "SME_EQUITY_L.csv")
        )
    except httpx.HTTPError as exc:
        typer.echo(f"warning: NSE SME list download failed ({exc}); SME companies left out")
        typer.echo(f"Download it in a browser from {securities.NSE_SME_LIST_URL}")
        typer.echo("and add: --nse-sme-file ~/Downloads/SME_EQUITY_L.csv")

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
    sector_index: str = typer.Option(None, help="NSE sector index benchmark, e.g. 'Nifty Bank'."),
) -> None:
    """Add a stock or bullion to the watchlist (or update it if already there)."""
    qty = Decimal(str(quantity)) if quantity is not None else None
    with get_session() as session:
        if name.strip().lower() in wl.COMMODITIES:
            item = wl.add_commodity(session, name, owned=owned, quantity=qty)
            typer.echo(f"tracking {item.display_name}{' (owned)' if owned else ''}")
            return
        company = _resolve_or_exit(session, name)
        wl.add_equity(
            session,
            company,
            owned=owned,
            quantity=qty,
            notes=notes,
            aliases=alias,
            sector_index=sector_index,
        )
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
        for problem in result.problems:  # inside the session: candidates are read from it
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
        result = _collector(session, pdf).collect(
            companies, default_days=days, sources=sources, progress=typer.echo
        )
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
        result = _collector(session, pdf).collect(
            companies, start=start, sources=sources, progress=typer.echo
        )
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
            feed_keys=feed or None, google=google, progress=typer.echo
        )
    typer.echo(
        f"{result.seen} articles read from {len(result.feeds)} feeds; "
        f"{result.matched} mention a watchlist company; {result.new} new"
    )
    for report in result.errors:
        typer.echo(f"error: {report.key}: {report.error}")


@news_app.command("backfill")
def news_backfill(
    since: str = typer.Option(..., help="Start date, YYYY-MM-DD (e.g. 2023-10-01)."),
    until: str = typer.Option(None, help="End date, YYYY-MM-DD (default: today)."),
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: whole watchlist)."),
) -> None:
    """Older articles from Google News, a month at a time. Safe to re-run; stored ones are kept."""
    from stock_news_analyzer.agents.news import NewsCollector
    from stock_news_analyzer.sources.news import NewsClient

    start = datetime.strptime(since, "%Y-%m-%d").date()
    end = datetime.strptime(until, "%Y-%m-%d").date() if until else date.today()
    with get_session() as session:
        if not fl.watchlist_companies(session, symbol):
            typer.echo(f"{symbol} is not on the watchlist" if symbol else "watchlist is empty")
            raise typer.Exit(1)
        result = NewsCollector(session, NewsClient(), _news_config(FEEDS_FILE)).backfill(
            start, end, symbol=symbol, progress=typer.echo
        )
    typer.echo(
        f"{len(result.feeds)} searches; {result.matched} articles mention a watchlist company; "
        f"{result.new} new"
    )
    for report in result.errors:
        typer.echo(f"error: {report.key}: {report.error}")
    if result.errors:
        typer.echo("re-run the same command to retry; stored articles are skipped")


@news_app.command("relink")
def news_relink() -> None:
    """Re-match stored articles to companies after changing aliases or exclusions."""
    from stock_news_analyzer.agents.news import relink

    with get_session() as session:
        added, removed = relink(session)
    typer.echo(f"{added} links added, {removed} links removed")


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


# --- prices and labels -------------------------------------------------------


def _price_collector(session):
    from stock_news_analyzer.agents.prices import PriceCollector
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    return PriceCollector(session, ExchangeClient(), get_settings().data_dir)


def _refresh_actions(session, client, start=None) -> list[str]:
    """Bonus issues, splits and dividends for the watchlist, used to adjust returns."""
    from stock_news_analyzer.agents.prices import refresh_corporate_actions

    today = datetime.now(fl.IST).date()
    since = min(start or today, today.replace(year=today.year - 3))
    typer.echo("fetching corporate actions (bonus, split, dividend)...")
    return refresh_corporate_actions(session, client, since, today)


def _price_progress(done: int, total: int, day, status: str, eta: float | None) -> None:
    left = f"  ~{eta / 60:.0f} min left" if eta is not None and eta >= 60 else ""
    typer.echo(f"[{done:>{len(str(total))}}/{total}] {day}  {status}{left}")


def _price_report(result, warnings: list[str]) -> None:
    typer.echo(
        f"{result.days} trading days loaded ({result.rows:,} price rows), "
        f"{result.holidays} holidays or not yet published, "
        f"{result.already_stored} already stored"
    )
    for w in warnings:
        typer.echo(f"warning: {w}")
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@prices_app.command("fetch")
def prices_fetch(
    days: int = typer.Option(7, help="How far back to start the first time."),
) -> None:
    """Load trading days since the last one stored, then update daily moves."""
    from stock_news_analyzer.agents.prices import compute_moves

    with get_session() as session:
        collector = _price_collector(session)
        result = collector.collect(collector.resume_date(days), progress=_price_progress)
        warnings = _refresh_actions(session, collector.client)
        typer.echo("updating daily moves...")
        warnings += compute_moves(session)
    _price_report(result, warnings)


@prices_app.command("backfill")
def prices_backfill(
    since: str = typer.Option(..., help="Start date, YYYY-MM-DD (e.g. 2023-10-01)."),
    until: str = typer.Option(None, help="End date, YYYY-MM-DD (default: today)."),
    force: bool = typer.Option(False, help="Download days already stored again."),
) -> None:
    """Load history (about 2 requests per trading day). Safe to stop and re-run."""
    from stock_news_analyzer.agents.prices import compute_moves

    start = datetime.strptime(since, "%Y-%m-%d").date()
    end = datetime.strptime(until, "%Y-%m-%d").date() if until else None
    with get_session() as session:
        collector = _price_collector(session)
        result = collector.collect(start, end, skip_stored=not force, progress=_price_progress)
        warnings = _refresh_actions(session, collector.client, start)
        typer.echo("updating daily moves...")
        warnings += compute_moves(session)
    _price_report(result, warnings)


@prices_app.command("moves")
def prices_moves(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
    days: int = typer.Option(30, help="How many recent trading days."),
    unusual: bool = typer.Option(False, "--unusual", help="Only unusual days."),
) -> None:
    """Daily return vs Nifty 50 and sector index; '!!' marks unusual days."""
    from sqlalchemy import select

    from stock_news_analyzer.models import StockMove

    def pct(x):
        return f"{x * 100:+6.2f}%" if x is not None else "     - "

    with get_session() as session:
        companies = _companies_or_exit(session, symbol)
        for company in companies:
            query = select(StockMove).where(StockMove.isin == company.isin)
            if unusual:
                query = query.where(StockMove.unusual)
            moves = session.scalars(query.order_by(StockMove.trade_date.desc()).limit(days)).all()
            typer.echo(f"\n{company.nse_symbol}  {company.name}")
            if not moves:
                typer.echo("  no moves yet; run: sna prices fetch")
                continue
            sector = moves[0].sector_index or "sector"
            typer.echo(
                f"  {'date':<10}  {'stock':>8} {'Nifty50':>8} {sector[:12]:>12} "
                f"{'vs Nifty':>9} {'vs sector':>9} {'z':>6}"
            )
            for m in moves:
                z = f"{m.zscore:+5.1f}" if m.zscore is not None else "    -"
                typer.echo(
                    f"  {m.trade_date}  {pct(m.stock_return):>8} {pct(m.nifty_return):>8} "
                    f"{pct(m.sector_return):>12} {pct(m.excess_return):>9} "
                    f"{pct(m.sector_excess_return):>9} {z:>6}{'  !!' if m.unusual else ''}"
                )


@prices_app.command("actions")
def prices_actions(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
) -> None:
    """Corporate actions used to adjust returns (refreshed by `prices fetch`)."""
    from sqlalchemy import select

    from stock_news_analyzer.models import CorporateAction

    with get_session() as session:
        symbols = [c.nse_symbol for c in _companies_or_exit(session, symbol)]
        actions = session.scalars(
            select(CorporateAction)
            .where(CorporateAction.symbol.in_(symbols))
            .order_by(CorporateAction.symbol, CorporateAction.ex_date)
        ).all()
        if not actions:
            typer.echo("no corporate actions stored yet; run: sna prices fetch")
        for a in actions:
            adj = f"x{a.price_factor:.4f}" if a.price_factor != 1 else ""
            div = f"-Rs {a.dividend:g}" if a.dividend else ""
            typer.echo(f"{a.symbol:<11} {a.ex_date}  {a.kind:<13} {adj or div:<12} {a.subject}")


@prices_app.command("indices")
def prices_indices(
    search: str = typer.Argument(None, help="Filter by name, e.g. bank."),
) -> None:
    """List NSE index names as stored (for `sector_index` in config/watchlist.yaml)."""
    from sqlalchemy import func, select

    from stock_news_analyzer.models import IndexDaily

    with get_session() as session:
        query = select(IndexDaily.index_name, func.max(IndexDaily.trade_date)).group_by(
            IndexDaily.index_name
        )
        if search:
            query = query.where(IndexDaily.index_name.ilike(f"%{search}%"))
        rows = session.execute(query.order_by(IndexDaily.index_name)).all()
    if not rows:
        typer.echo("no index data yet; run: sna prices fetch")
    for name, latest in rows:
        typer.echo(f"{name:<45} latest {latest}")


@labels_app.command("update")
def labels_update() -> None:
    """Compute what each stock did 1, 5 and 20 trading days after each filing and article."""
    from stock_news_analyzer.agents.prices import update_labels

    with get_session() as session:
        written, complete = update_labels(session)
    typer.echo(f"{written} labels computed ({complete} complete; others wait for more days)")


@labels_app.command("list")
def labels_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
    doc_type: str = typer.Option(None, "--type", help="e.g. order_win, results, news."),
    limit: int = typer.Option(20, help="How many to show."),
) -> None:
    """Filings and articles with the stock's return vs Nifty 50 afterwards."""
    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Document, EventLabel

    def pct(x):
        return f"{x * 100:+6.2f}%" if x is not None else "     - "

    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        query = (
            select(EventLabel, Document, Company)
            .join(Document, Document.id == EventLabel.document_id)
            .join(Company, Company.isin == EventLabel.isin)
            .order_by(Document.published_at.desc())
            .limit(limit)
        )
        if isin:
            query = query.where(EventLabel.isin == isin)
        if doc_type:
            query = query.where(Document.doc_type == doc_type)
        rows = session.execute(query).all()
        if not rows:
            typer.echo("no labels yet; run: sna labels update")
            return
        typer.echo(
            f"{'id':>6}  {'day0':<10}  {'symbol':<11} {'type':<14} "
            f"{'1d':>8} {'5d':>8} {'20d':>8}  (vs Nifty 50)  title"
        )
        for label, doc, company in rows:
            typer.echo(
                f"{doc.id:>6}  {label.day0 or '-'!s:<10}  {company.nse_symbol or '-':<11} "
                f"{doc.doc_type[:14]:<14} {pct(label.excess_1d):>8} {pct(label.excess_5d):>8} "
                f"{pct(label.excess_20d):>8}  {doc.title[:60]}"
            )


# --- orchestrator, runs and digest -------------------------------------------


@app.command("run")
def run(
    job: str = typer.Argument(
        ..., help="filings, news, triage, prices, explain, securities, digest, or all."
    ),
) -> None:
    """Run a job now (as the orchestrator would) and record it in the run log."""
    from stock_news_analyzer.agents.orchestrator import JOBS, RUN_ALL, run_job

    names = list(RUN_ALL) if job == "all" else [job]
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        typer.echo(f"unknown job '{unknown[0]}'; choose from: {', '.join(JOBS)}, all")
        raise typer.Exit(2)
    failed = False
    for name in names:
        typer.echo(f"running {name}...")
        result = run_job(name)
        typer.echo(f"{name}: {result.status}  {result.summary or ''}")
        if result.error:
            typer.echo(f"  error: {result.error}")
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command("runs")
def runs(
    job: str = typer.Option(None, help="Only this job."),
    limit: int = typer.Option(20, help="How many to show."),
) -> None:
    """Recent job runs: when, how long, result."""
    from sqlalchemy import select

    from stock_news_analyzer.models import Run

    with get_session() as session:
        query = select(Run).order_by(Run.started_at.desc()).limit(limit)
        if job:
            query = query.where(Run.job == job)
        rows = session.scalars(query).all()
    if not rows:
        typer.echo("no runs yet; try: sna run all")
        return
    for r in rows:
        took = f"{(r.finished_at - r.started_at).total_seconds():.0f}s" if r.finished_at else "-"
        when = r.started_at.astimezone(fl.IST).strftime("%Y-%m-%d %H:%M")
        typer.echo(f"{when}  {r.job:<10} {r.status:<7} {took:>6}  {r.summary or ''}")
        if r.error:
            typer.echo(f"{'':>36}error: {r.error[:200]}")


@orchestrator_app.command("show")
def orchestrator_show(
    schedule: Path = typer.Option(Path("config/schedule.yaml"), help="Schedule file."),
) -> None:
    """The schedule and when each job runs next (India time)."""
    from stock_news_analyzer.agents.orchestrator import load_schedule, next_runs

    jobs = load_schedule(schedule)
    upcoming = next_runs(jobs)
    for j in jobs:
        nxt = upcoming.get(j.name)
        when = nxt.strftime("%a %d %b %H:%M") if nxt else "paused"
        typer.echo(f"{j.name:<11} {j.cron:<20} next: {when}")


@orchestrator_app.command("start")
def orchestrator_start(
    schedule: Path = typer.Option(Path("config/schedule.yaml"), help="Schedule file."),
    run_now: bool = typer.Option(False, help="Run filings and news once before waiting."),
) -> None:
    """Run jobs on schedule until stopped (Ctrl+C). Also used by the Docker scheduler."""
    from stock_news_analyzer.agents.orchestrator import (
        build_scheduler,
        load_schedule,
        next_runs,
        run_job,
    )

    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    jobs = load_schedule(schedule)
    for name, when in next_runs(jobs).items():
        typer.echo(f"{name:<11} next run {when:%a %d %b %H:%M} IST")
    if run_now:
        for name in ("filings", "news"):
            run_job(name)
    typer.echo("orchestrator running; Ctrl+C to stop")
    try:
        build_scheduler(jobs).start()
    except (KeyboardInterrupt, SystemExit):
        typer.echo("orchestrator stopped")


@app.command("digest")
def digest(
    hours: int = typer.Option(None, help="Cover the last N hours (default: since last digest)."),
    save: bool = typer.Option(False, help="Also save it under data/digests/."),
) -> None:
    """Print the digest now. Scheduled digests (`sna run digest`) are saved automatically."""
    from datetime import UTC, timedelta

    from stock_news_analyzer.agents.digest import build_digest, last_digest_time, save_digest

    until = datetime.now(UTC)
    with get_session() as session:
        since = (
            until - timedelta(hours=hours)
            if hours
            else last_digest_time(session) or until - timedelta(days=1)
        )
        result = build_digest(session, since, until)
    typer.echo(result.markdown)
    if save:
        typer.echo(f"saved to {save_digest(result, get_settings().data_dir)}")


@app.command("ui")
def ui(
    port: int = typer.Option(8501, help="Port for the dashboard."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open it in the browser."),
) -> None:
    """Start the dashboard at http://localhost:8501 (read-only; Ctrl+C to stop)."""
    import subprocess
    import sys

    script = Path(__file__).parent / "ui" / "app.py"
    typer.echo(f"dashboard on http://localhost:{port}  (Ctrl+C to stop)")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(script),
        "--server.port",
        str(port),
        "--server.headless",
        str(not open_browser).lower(),
    ]
    try:
        raise typer.Exit(subprocess.call(cmd))
    except KeyboardInterrupt:
        typer.echo("dashboard stopped")


# --- news triage and LLM usage (Phase 2) -------------------------------------


@triage_app.command("run")
def triage_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(None, help="Only articles published from YYYY-MM-DD."),
    limit: int = typer.Option(None, help="At most this many articles (default: all pending)."),
) -> None:
    """Triage news not triaged yet (Haiku by default; LLM_MODEL_TRIAGE in .env)."""
    from stock_news_analyzer.agents.triage import triage_news
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=fl.IST) if since else None
    with get_session() as session:
        try:
            result = triage_news(
                session,
                LLM(session),
                symbol=symbol,
                since=start,
                limit=limit,
                progress=typer.echo,
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.triaged} articles triaged ({result.same_story} linked to an earlier report "
        f"of the same event), {result.duplicates} near-identical headlines, "
        f"{result.calls} LLM calls, ${result.cost_usd:.4f} (this month ${spent:.2f} of "
        f"${get_settings().llm_monthly_budget_usd:.2f})"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@triage_app.command("list")
def triage_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
    days: int = typer.Option(7, help="How many days back."),
    min_importance: int = typer.Option(3, help="Only articles at least this important (1-5)."),
    all_: bool = typer.Option(False, "--all", help="Include off-topic and repeated articles."),
) -> None:
    """Triaged news, most important first."""
    from datetime import UTC, timedelta

    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Document, NewsTriage

    since = datetime.now(UTC) - timedelta(days=days)
    query = (
        select(NewsTriage, Document, Company.nse_symbol)
        .join(Document, Document.id == NewsTriage.document_id)
        .join(Company, Company.isin == NewsTriage.isin)
        .where(Document.published_at >= since, NewsTriage.importance >= min_importance)
        .order_by(NewsTriage.importance.desc(), Document.published_at.desc())
    )
    if symbol:
        query = query.where(Company.nse_symbol == symbol.upper())
    if not all_:
        query = query.where(NewsTriage.relevant, NewsTriage.duplicate_of.is_(None))
    with get_session() as session:
        rows = session.execute(query).all()
        if not rows:
            typer.echo("nothing triaged in that window; run: sna triage run")
            return
        for t, doc, sym in rows:
            when = doc.published_at.astimezone(fl.IST).strftime("%d %b %H:%M")
            tag = (
                "  [off-topic]"
                if not t.relevant
                else f"  [repeat of {t.duplicate_of}]"
                if t.duplicate_of
                else ""
            )
            typer.echo(
                f"{'*' * t.importance:<5} {when}  {sym or '-':<11} {t.topic:<16} "
                f"{t.sentiment:<8} #{doc.id} {doc.title[:90]}{tag}"
            )
            if not t.duplicate_of:
                typer.echo(f"      {t.summary}")


@triage_app.command("reset")
def triage_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget triage results so the next `sna triage run` judges those articles again."""
    from stock_news_analyzer.agents.triage import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} triage results?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol)
    typer.echo(f"{count} triage results removed; run `sna triage run` to triage them again")


@llm_app.command("usage")
def llm_usage() -> None:
    """This month's LLM calls and cost, by task and model, against the budget."""
    from sqlalchemy import func, select

    from stock_news_analyzer.llm import month_spend
    from stock_news_analyzer.models import LlmCall

    now = datetime.now(fl.IST)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        rows = session.execute(
            select(
                LlmCall.task,
                LlmCall.model,
                func.count(),
                func.sum(LlmCall.input_tokens),
                func.sum(LlmCall.output_tokens),
                func.sum(LlmCall.cost_usd),
                func.count().filter(~LlmCall.ok),
            )
            .where(LlmCall.at >= start)
            .group_by(LlmCall.task, LlmCall.model)
            .order_by(LlmCall.task)
        ).all()
        spent = month_spend(session)
    budget = get_settings().llm_monthly_budget_usd
    typer.echo(f"{now:%B %Y}: ${spent:.2f} of ${budget:.2f} budget")
    for task, model, calls, tin, tout, usd, failed in rows:
        typer.echo(
            f"  {task:<10} {model:<20} {calls:>5} calls ({failed} failed)  "
            f"{tin or 0:>9,} in  {tout or 0:>8,} out  ${usd or 0:.4f}"
        )


@explain_app.command("run")
def explain_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(None, help="Only unusual days from YYYY-MM-DD."),
    until: str = typer.Option(
        None, help="Only unusual days up to YYYY-MM-DD (default: yesterday)."
    ),
    limit: int = typer.Option(None, help="At most this many days (newest first)."),
) -> None:
    """Explain unusual days not explained yet (Sonnet by default; LLM_MODEL_ANALYSIS)."""
    from datetime import timedelta

    from stock_news_analyzer.agents.explain import explain_moves, pending
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = datetime.strptime(since, "%Y-%m-%d").date() if since else None
    end = (
        datetime.strptime(until, "%Y-%m-%d").date()
        if until
        else datetime.now(fl.IST).date() - timedelta(days=1)
    )
    with get_session() as session:
        waiting = len(pending(session, start, end, symbol))
        n = min(waiting, limit) if limit else waiting
        typer.echo(f"{n} unusual days to explain (roughly ${0.02 * n:.2f} with Sonnet)")
        try:
            result = explain_moves(
                session,
                LLM(session),
                since=start,
                until=end,
                symbol=symbol,
                limit=limit,
                progress=typer.echo,
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.explained} explained, {result.calls} LLM calls, ${result.cost_usd:.4f} "
        f"(this month ${spent:.2f} of ${get_settings().llm_monthly_budget_usd:.2f})"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@explain_app.command("list")
def explain_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
    days: int = typer.Option(90, help="How many days back."),
) -> None:
    """Explained unusual days, newest first, with the documents they rest on."""
    from datetime import timedelta

    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Document, MoveExplanation, StockMove

    since = datetime.now(fl.IST).date() - timedelta(days=days)
    query = (
        select(MoveExplanation, StockMove, Company.nse_symbol)
        .join(
            StockMove,
            (StockMove.isin == MoveExplanation.isin)
            & (StockMove.trade_date == MoveExplanation.trade_date),
        )
        .join(Company, Company.isin == MoveExplanation.isin)
        .where(MoveExplanation.trade_date >= since)
        .order_by(MoveExplanation.trade_date.desc())
    )
    if symbol:
        query = query.where(Company.nse_symbol == symbol.upper())
    with get_session() as session:
        rows = session.execute(query).all()
        if not rows:
            typer.echo("nothing explained in that window; run: sna explain run")
            return
        for e, m, sym in rows:
            typer.echo(
                f"{e.trade_date:%d %b %Y}  {sym or '-':<11} {m.stock_return:+.2%} "
                f"({m.excess_return:+.2%} vs Nifty)  {e.cause}, {e.confidence} confidence"
            )
            typer.echo(f"      {e.explanation}")
            for doc_id in e.evidence:
                doc = session.get(Document, doc_id)
                if doc:
                    typer.echo(f"      - #{doc.id} {doc.title[:100]}")


@explain_app.command("reset")
def explain_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget explanations so the next `sna explain run` explains those days again."""
    from stock_news_analyzer.agents.explain import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} move explanations?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol)
    typer.echo(f"{count} explanations removed; run `sna explain run` to explain them again")
