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
concalls_app = typer.Typer(
    help="Concall Analyst (LLM): earnings calls of watchlist stocks, and the promise ledger.",
    no_args_is_help=True,
)
app.add_typer(concalls_app, name="concalls")
promises_app = typer.Typer(
    help="Promise Ledger (LLM): were management's promises kept? Credibility per company.",
    no_args_is_help=True,
)
app.add_typer(promises_app, name="promises")
orders_app = typer.Typer(
    help="Order Book Tracker (LLM): order wins, order books, book-to-bill, peers.",
    no_args_is_help=True,
)
app.add_typer(orders_app, name="orders")
results_app = typer.Typer(
    help="Results Reader (LLM): revenue, profit and margins from quarterly results filings.",
    no_args_is_help=True,
)
app.add_typer(results_app, name="results")
events_app = typer.Typer(
    help="Event Extractor and QA Checker (LLM): capex, ratings, management changes, "
    "fundraises... from filings, each checked.",
    no_args_is_help=True,
)
app.add_typer(events_app, name="events")
flags_app = typer.Typer(
    help="Red-flag Monitor: auditor and CFO exits, downgrades, pledges, penalties, late results.",
    no_args_is_help=True,
)
app.add_typer(flags_app, name="flags")
bullion_app = typer.Typer(
    help="Bullion Analyst: Indian gold and silver moves split into global price, rupee and "
    "the rest, with a note on unusual days.",
    no_args_is_help=True,
)
app.add_typer(bullion_app, name="bullion")
themes_app = typer.Typer(
    help="Theme & Peer Analyst: themes across companies (data centres, defence, credit...) "
    "and read-across between watchlist companies.",
    no_args_is_help=True,
)
app.add_typer(themes_app, name="themes")
questions_app = typer.Typer(
    help="Analyst Q&A: questions asked so far and saved reports (ask with `sna ask`).",
    no_args_is_help=True,
)
app.add_typer(questions_app, name="questions")
deals_app = typer.Typer(help="NSE bulk and block deals.", no_args_is_help=True)
app.add_typer(deals_app, name="deals")
app.add_typer(triage_app, name="triage")
app.add_typer(llm_app, name="llm")


def entry() -> None:
    """The `sna` command: the app, with a one-line message when Postgres is not running
    instead of a long traceback."""
    try:
        app()
    except OperationalError as exc:
        if "connection" not in str(exc).lower():
            raise
        url = get_settings().database_url.rsplit("@", 1)[-1]
        typer.echo(
            f"Postgres is not reachable at {url}. Open Docker Desktop, run `make up`, "
            "then `make health` to check.",
            err=True,
        )
        raise SystemExit(1) from None


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
        ...,
        help="filings, news, triage, deals, prices, xbrl, results, explain, concalls, promises, "
        "orders, securities, digest, or all.",
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
    redo_unexplained: bool = typer.Option(
        False, help="First forget days answered 'unexplained' in the range, to try them again."
    ),
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
        if redo_unexplained:
            from stock_news_analyzer.agents.explain import reset

            redo = reset(session, symbol, only_unexplained=True, since=start, until=end)
            typer.echo(f"{redo} 'unexplained' days will be tried again")
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


# --- earnings calls ------------------------------------------------------------


@concalls_app.command("run")
def concalls_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(
        None, help="Transcripts filed from YYYY-MM-DD (default: the last 400 days)."
    ),
    limit: int = typer.Option(None, help="At most this many LLM calls."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask before spending more than $2."),
) -> None:
    """Analyse earnings call transcripts not read yet (Sonnet by default; LLM_MODEL_ANALYSIS).

    Oldest first, so each call is compared with the one before it.
    """
    from datetime import timedelta

    from stock_news_analyzer.agents import concalls as cc
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = (
        datetime.strptime(since, "%Y-%m-%d").date()
        if since
        else datetime.now(fl.IST).date() - timedelta(days=400)
    )
    model = get_settings().llm_model_analysis
    with get_session() as session:
        waiting = cc.pending(session, start, symbol)
        calls, estimate = cc.estimate(session, waiting, model)
        typer.echo(
            f"{len(waiting)} transcript filings to look at since {start:%d %b %Y}: about "
            f"{calls} call{'' if calls == 1 else 's'} once BSE/NSE copies are merged; "
            f"roughly ${estimate:.2f} with {model}"
        )
        if estimate > 2 and not yes and not typer.confirm("Go ahead?"):
            raise typer.Exit(1)
        try:
            result = cc.analyse_calls(
                session, LLM(session), since=start, symbol=symbol, limit=limit, progress=typer.echo
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.analysed} calls analysed, {result.duplicates} copies of the same call, "
        f"{result.no_text} without text, {result.skipped} not earnings calls; "
        f"{result.calls} LLM calls, ${result.cost_usd:.4f} "
        f"(this month ${spent:.2f} of ${get_settings().llm_monthly_budget_usd:.2f})"
    )
    if result.waiting:
        typer.echo(
            f"{result.waiting} transcripts have no PDF yet: run "
            "`sna filings attachments --pdf important`, then this again"
        )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@concalls_app.command("list")
def concalls_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: every stock)."),
    all_rows: bool = typer.Option(
        False, "--all", help="Also transcripts not analysed (copies, no text, skipped)."
    ),
) -> None:
    """Earnings calls looked at, newest first."""
    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Concall

    query = (
        select(Concall, Company.nse_symbol)
        .join(Company, Company.isin == Concall.isin)
        .order_by(Concall.published_at.desc())
    )
    if symbol:
        query = query.where(Company.nse_symbol == symbol.upper())
    if not all_rows:
        query = query.where(Concall.status == "analysed")
    with get_session() as session:
        rows = session.execute(query).all()
    if not rows:
        typer.echo("no earnings calls analysed yet; run: sna concalls run")
        return
    for c, sym in rows:
        when = f"{c.published_at.astimezone(fl.IST):%d %b %Y}"
        if c.status == "analysed":
            typer.echo(f"{when}  {sym or '-':<11} {c.quarter:<8} {c.tone:<9} #{c.id}")
            typer.echo(f"      {c.summary}")
        else:
            typer.echo(f"{when}  {sym or '-':<11} {c.status}: {c.note}")


@concalls_app.command("show")
def concalls_show(
    symbol: str = typer.Argument(..., help="NSE symbol."),
    quarter: str = typer.Option(None, help="e.g. 'Q2 FY27' (default: the latest call)."),
) -> None:
    """One call in full: summary, points to watch, changes, guidance, analyst concerns."""
    from sqlalchemy import select

    from stock_news_analyzer.agents.concalls import quarter_name
    from stock_news_analyzer.models import Company, Concall, ConcallPoint, Promise

    query = (
        select(Concall)
        .join(Company, Company.isin == Concall.isin)
        .where(Company.nse_symbol == symbol.upper(), Concall.status == "analysed")
        .order_by(Concall.published_at.desc())
    )
    if quarter:
        query = query.where(Concall.quarter == (quarter_name(quarter) or quarter))
    with get_session() as session:
        c = session.scalars(query.limit(1)).first()
        if c is None:
            typer.echo(f"no analysed call for {symbol}" + (f" {quarter}" if quarter else ""))
            raise typer.Exit(1)
        a = c.analysis or {}
        typer.echo(f"{symbol.upper()} {c.quarter} earnings call, tone: {c.tone}")
        typer.echo(f"filed {c.published_at.astimezone(fl.IST):%d %b %Y %H:%M}, concall #{c.id}")
        typer.echo(f"\n{c.summary}\n\nTo watch:")
        for point in a.get("action_points", []):
            typer.echo(f"  - {point}")
        if a.get("changes"):
            typer.echo("\nSince the previous call:")
            for ch in a["changes"]:
                typer.echo(f"  - {ch['kind']}: {ch['text']}")
        typer.echo("\nPoints:")
        points = session.scalars(
            select(ConcallPoint).where(ConcallPoint.concall_id == c.id).order_by(ConcallPoint.id)
        ).all()
        for p in points:
            mark = "" if p.quote_found else "  (quote not found in the transcript)"
            typer.echo(f"  - [{p.category}, {p.sentiment}] {p.text}{mark}")
        if a.get("analyst_concerns"):
            typer.echo("\nAnalysts pressed on:")
            for q in a["analyst_concerns"]:
                typer.echo(f"  - {q['topic']} ({q['answer']} answer): {q['question']}")
        promises = session.scalars(select(Promise).where(Promise.concall_id == c.id)).all()
        if promises:
            typer.echo("\nPromises made:")
            for p in promises:
                typer.echo(f"  - #{p.id} {p.statement} (due {p.due}; {p.status})")


@concalls_app.command("promises")
def concalls_promises(
    symbol: str = typer.Argument(None, help="NSE symbol (default: every stock)."),
    open_only: bool = typer.Option(False, "--open", help="Only promises not settled yet."),
) -> None:
    """The promise ledger: what management committed to, by when, and what became of it."""
    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Concall, Promise

    query = (
        select(Promise, Company.nse_symbol, Concall.quarter)
        .join(Company, Company.isin == Promise.isin)
        .join(Concall, Concall.id == Promise.concall_id)
        .order_by(Company.nse_symbol, Promise.due_date.nulls_last(), Promise.id)
    )
    if symbol:
        query = query.where(Company.nse_symbol == symbol.upper())
    if open_only:
        query = query.where(Promise.status.in_(("open", "on_track", "revised")))
    with get_session() as session:
        rows = session.execute(query).all()
    if not rows:
        typer.echo("no promises recorded yet; run: sna concalls run")
        return
    today = datetime.now(fl.IST).date()
    for p, sym, made_in in rows:
        overdue = (
            "  OVERDUE"
            if p.due_date and p.due_date < today and p.status in ("open", "on_track")
            else ""
        )
        due = f"{p.due_date:%d %b %Y}" if p.due_date else "no date"
        typer.echo(
            f"{sym or '-':<11} #{p.id:<5} {p.status:<9} due {due:<11}  {p.statement}{overdue}"
        )
        typer.echo(f"{'':<17}target: {p.target}; due as said: {p.due}; said in {made_in}")
        if p.status_note:
            typer.echo(f"{'':<17}{p.status_note}")


@concalls_app.command("reset")
def concalls_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    unread_only: bool = typer.Option(
        False, "--unread-only", help="Only transcripts that had no text or were skipped."
    ),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget calls (with their points and promises) so `sna concalls run` reads them again."""
    from stock_news_analyzer.agents.concalls import reset

    what = f"{symbol}'s" if symbol else "all"
    what += " unread" if unread_only else ""
    if not yes and not typer.confirm(f"Forget {what} earnings call results?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol, only_unread=unread_only)
    typer.echo(f"{count} transcripts forgotten; run `sna concalls run` to read them again")


# --- promise ledger -------------------------------------------------------------


@promises_app.command("check")
def promises_check(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    limit: int = typer.Option(None, help="At most this many companies (LLM calls)."),
) -> None:
    """Check promises past their due date against later results, filings and calls."""
    from stock_news_analyzer.agents.promises import check_promises, due
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    with get_session() as session:
        waiting = due(session, symbol)
        count = sum(len(p) for _, p in waiting)
        typer.echo(
            f"{count} promises past their due date at {len(waiting)} companies "
            f"(already-checked ones are skipped until new documents arrive; about $0.05 a "
            "company)"
        )
        try:
            result = check_promises(
                session, LLM(session), symbol=symbol, limit=limit, progress=typer.echo
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    if result.held:
        typer.echo(
            f"{result.held} judged missed before their results are due out: they stay open and "
            "are marked missed when the window closes with nothing newer"
        )
    typer.echo(
        f"{result.checked} promises checked, {result.settled} settled; {result.calls} LLM calls, "
        f"${result.cost_usd:.4f} (this month ${spent:.2f} of "
        f"${get_settings().llm_monthly_budget_usd:.2f})"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@promises_app.command("list")
def promises_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: every stock)."),
    open_only: bool = typer.Option(False, "--open", help="Only promises not settled yet."),
) -> None:
    """The promise ledger (same as `sna concalls promises`)."""
    concalls_promises(symbol, open_only)


@promises_app.command("scores")
def promises_scores() -> None:
    """Management credibility: the share of each company's promises kept."""
    from stock_news_analyzer.agents.promises import MIN_SCORED, credibility

    with get_session() as session:
        rows = credibility(session)
    if not rows:
        typer.echo("no promises recorded yet; run: sna concalls run")
        return
    for c in rows:
        score = f"{c['score']:.0%}" if c["score"] is not None else "–"
        typer.echo(
            f"{c['symbol'] or '-':<11} {score:>5} of {c['scored']:<3} "
            f"kept {c['kept']}, kept late {c['kept_late']}, partly {c['partly']}, "
            f"missed {c['missed']}, dropped {c['dropped']}, overdue {c['overdue']}; "
            f"{c['to_come']} still to come"
        )
    typer.echo(
        f"Score: kept 1, kept late or partly 0.5, missed, dropped or long overdue 0; shown from "
        f"{MIN_SCORED} settled promises. Run `sna promises check` to settle more."
    )


@promises_app.command("reset")
def promises_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget promise checks; settled promises go back to what the calls last said."""
    from stock_news_analyzer.agents.promises import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} promise checks?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol)
    typer.echo(f"{count} promises reopened; run `sna promises check` to check them again")


# --- orders and order books -----------------------------------------------------


def _cr(x) -> str:
    return "–" if x is None else f"{x:,.0f}"


def _x(x, fmt="{:.2f}x") -> str:
    return "–" if x is None else fmt.format(x)


@orders_app.command("run")
def orders_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(None, help="Filings from YYYY-MM-DD (default: all not read yet)."),
    limit: int = typer.Option(None, help="At most this many LLM calls."),
) -> None:
    """Read new order-win filings (Haiku), then order books by quarter (Sonnet)."""
    from stock_news_analyzer.agents import orders
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = datetime.strptime(since, "%Y-%m-%d").date() if since else None
    with get_session() as session:
        waiting = len(orders.pending_filings(session, start, symbol))
        typer.echo(
            f"{waiting} order-win filings not read yet (Haiku, a fraction of a cent each); "
            "then order books for order-driven companies (Sonnet, about $0.03 a quarter)"
        )
        try:
            result = orders.run(
                session,
                LLM(session),
                since=start,
                symbol=symbol,
                limit=limit,
                progress=typer.echo,
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.orders} orders from {result.filings} filings ({result.duplicates} copies of "
        f"the same announcement, {result.not_orders} not order wins); {result.snapshots} "
        f"quarterly order books; {result.calls} LLM calls, ${result.cost_usd:.4f} (this month "
        f"${spent:.2f} of ${get_settings().llm_monthly_budget_usd:.2f})"
    )
    if result.waiting:
        typer.echo(
            f"{result.waiting} order filings have no PDF yet: run "
            "`sna filings attachments --pdf important`, then this again"
        )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@orders_app.command("list")
def orders_list(
    symbol: str = typer.Argument(..., help="NSE symbol."),
    days: int = typer.Option(365, help="How many days back."),
) -> None:
    """A company's orders, newest first."""
    from datetime import timedelta

    from sqlalchemy import select

    from stock_news_analyzer.models import Company, Order

    since = datetime.now(fl.IST) - timedelta(days=days)
    with get_session() as session:
        rows = session.scalars(
            select(Order)
            .join(Company, Company.isin == Order.isin)
            .where(Company.nse_symbol == symbol.upper(), Order.announced_at >= since)
            .order_by(Order.announced_at.desc())
        ).all()
        if not rows:
            typer.echo(f"no orders for {symbol} in that window; run: sna orders run")
            return
        for o in rows:
            value = f"Rs {o.value_cr:,.0f} cr" if o.value_cr is not None else "value not disclosed"
            if o.value_low_cr is not None and o.value_high_cr is not None:
                value += f" ({o.value_low_cr:,.0f}-{o.value_high_cr:,.0f})"
            # A value from a size class ("large") is not written as a number in the filing.
            checkable = o.value_cr is not None and not o.size_class
            check = "" if o.value_found or not checkable else "  (value not found as written)"
            typer.echo(
                f"{o.announced_at.astimezone(fl.IST):%d %b %Y}  {o.kind:<9} {value:<28} "
                f"{o.client_type:<10} {o.client or 'client not named'}{check}"
            )
            typer.echo(f"{'':<12}{o.description}")


@orders_app.command("book")
def orders_book(symbol: str = typer.Argument(..., help="NSE symbol.")) -> None:
    """Quarter by quarter: orders announced, inflow, order book, revenue, book-to-bill."""
    from stock_news_analyzer.agents import orders

    with get_session() as session:
        company = _companies_or_exit(session, symbol)[0]
        rows = orders.quarterly(session, company.isin)
        s = orders.summary(session, company.isin)
    if not rows:
        typer.echo(f"nothing for {symbol} yet; run: sna orders run --symbol {symbol}")
        return
    typer.echo(
        f"{'quarter':<9} {'announced':>10} {'(n)':>5} {'inflow':>9} {'revenue':>9} "
        f"{'book':>10} {'book/bill':>9} {'unexplained':>11}   (Rs crore)"
    )
    for r in rows:
        revenue = _cr(r["revenue_cr"]) + ("*" if r["revenue_from"] == "results" else " ")
        typer.echo(
            f"{r['quarter']:<9} {_cr(r['announced_cr']):>10} {r['announced']:>5} "
            f"{_cr(r['inflow_cr']):>9} {revenue:>10} {_cr(r['order_book_cr']):>9} "
            f"{_x(r['book_to_bill']):>9} {_cr(r['unexplained_cr']):>11}"
        )
    if any(r["revenue_from"] == "results" for r in rows):
        typer.echo("* revenue from the results filing (the order-book document didn't give it)")
    if s["revenue_from"] and s["revenue_from"].startswith("results"):
        typer.echo(
            f"Revenue below: the 12 months to {s['order_book_quarter']} from {s['revenue_from']}; "
            f"orders won: {s['inflow_from'] or '–'}"
        )
    typer.echo(
        f"Last 4 quarters: inflow {_cr(s['inflow_cr'])}, revenue {_cr(s['revenue_cr'])}, "
        f"book-to-bill {_x(s['book_to_bill'])}; order book {_cr(s['order_book_cr'])} "
        f"({s['order_book_quarter'] or '-'}) = {_x(s['years_of_revenue'], '{:.1f}')} years of "
        f"revenue; execution {_x(s['execution'], '{:.0%}')} of the book a year earlier; "
        f"government/PSU {_x(s['government_share'], '{:.0%}')} of orders announced, top client "
        f"{s['top_client'] or '-'} {_x(s['top_client_share'], '{:.0%}')}"
    )


@orders_app.command("peers")
def orders_peers() -> None:
    """Order-driven watchlist companies side by side, ranked (1 = best)."""
    from stock_news_analyzer.agents import orders

    with get_session() as session:
        rows = orders.peers(session)
    if not rows:
        typer.echo(f"no company has {orders.MIN_ORDERS}+ orders yet; run: sna orders run")
        return
    typer.echo(
        f"{'':<11} {'book/bill':>9} {'(rank)':>6} {'years':>6} {'(rank)':>6} "
        f"{'growth':>7} {'(rank)':>6} {'order book':>11} {'govt':>5}"
    )
    for r in rows:
        typer.echo(
            f"{r['symbol'] or '-':<11} {_x(r['book_to_bill']):>9} "
            f"{r.get('book_to_bill_rank', '-'):>6} {_x(r['years_of_revenue'], '{:.1f}'):>6} "
            f"{r.get('years_of_revenue_rank', '-'):>6} "
            f"{_x(r['announced_growth'], '{:+.0%}'):>7} {r.get('announced_growth_rank', '-'):>6} "
            f"{_cr(r['order_book_cr']):>11} {_x(r['government_share'], '{:.0%}'):>5}"
        )
    typer.echo(
        "book/bill: inflow / revenue, last 4 quarters. years: latest order book / last 4 "
        "quarters' revenue. growth: orders announced, last 4 quarters vs the 4 before."
    )


@orders_app.command("coverage")
def orders_coverage() -> None:
    """For every watchlist stock: order filings found and read, orders, order books."""
    from stock_news_analyzer.agents import orders

    with get_session() as session:
        rows = orders.coverage(session)
    typer.echo(
        f"{'':<11} {'filings':>7} {'read':>5} {'copies':>6} {'not':>4} {'no PDF':>6} "
        f"{'unread':>6} {'orders':>6} {'books':>5}  order book tracked"
    )
    for r in rows:
        typer.echo(
            f"{r['symbol']:<11} {r['filings']:>7} {r['extracted']:>5} {r['copies']:>6} "
            f"{r['not_orders']:>4} {r['no_pdf']:>6} {r['unread']:>6} {r['orders']:>6} "
            f"{r['order_books']:>5}  {'yes' if r['tracked'] else 'no'}"
        )
    typer.echo(
        f"filings: classified as order wins. not: read but not an order win. no PDF: run "
        f"`sna filings attachments --pdf important`. unread: run `sna orders run`. An order "
        f"book is tracked from {orders.MIN_ORDERS} orders. If a company's order wins are "
        "missing, run `sna filings reclassify` first: it re-reads each filing's type."
    )


@orders_app.command("reset")
def orders_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    books_only: bool = typer.Option(False, "--books-only", help="Only the order-book figures."),
    orders_only: bool = typer.Option(
        False, "--orders-only", help="Only the orders (keep the order books)."
    ),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget extracted orders and order books so `sna orders run` reads them again."""
    from stock_news_analyzer.agents.orders import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} order data?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol, snapshots_only=books_only, orders_only=orders_only)
    typer.echo(f"{count} rows removed; run `sna orders run` to read them again")


# --- results -------------------------------------------------------------------


@results_app.command("run")
def results_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(
        None, help="Results filed from YYYY-MM-DD (default: the last 800 days)."
    ),
    limit: int = typer.Option(None, help="At most this many LLM calls."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask before spending more than $1."),
) -> None:
    """Read results filings not read yet (Haiku by default; LLM_MODEL_TRIAGE)."""
    from datetime import timedelta

    from stock_news_analyzer.agents import results as rs
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = (
        datetime.strptime(since, "%Y-%m-%d").date()
        if since
        else datetime.now(fl.IST).date() - timedelta(days=rs.RESULT_DAYS)
    )
    model = get_settings().llm_model_triage
    with get_session() as session:
        waiting = rs.pending(session, start, symbol)
        calls, estimate = rs.estimate(session, waiting, model)
        typer.echo(
            f"{len(waiting)} results filings to look at since {start:%d %b %Y}: about {calls} "
            f"company-quarters to read; roughly ${estimate:.2f} with {model}"
        )
        if estimate > 1 and not yes and not typer.confirm("Go ahead?"):
            raise typer.Exit(1)
        try:
            result = rs.run(
                session, LLM(session), since=start, symbol=symbol, limit=limit, progress=typer.echo
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.periods} periods stored from {result.filings} filings ({result.duplicates} "
        f"copies of a period already read, {result.no_figures} without a results statement, "
        f"{result.no_text} without text, {result.failed} unusable answers; "
        f"{result.rescaled} figures out of scale restored or left out); "
        f"{result.calls} LLM calls, ${result.cost_usd:.4f} "
        f"(this month ${spent:.2f} of ${get_settings().llm_monthly_budget_usd:.2f})"
    )
    if result.waiting:
        typer.echo(
            f"{result.waiting} results filings have no PDF yet: run "
            "`sna filings attachments --pdf important`, then this again"
        )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


# Where NSE may list results filed as SEBI's Integrated Filing (Financial), which replaced the
# results listing from February 2025. Tried by `sna results probe` until one answers.
INTEGRATED_CANDIDATES = (
    ("https://www.nseindia.com/api/integrated-filing-results", {}),
    (
        "https://www.nseindia.com/api/integrated-filing-results",
        {"type": "Integrated Filing- Financials"},
    ),
    ("https://www.nseindia.com/api/integrated-filing-results", {"period": "Quarterly"}),
    ("https://www.nseindia.com/api/corporates-integrated-filing", {}),
)


def _probe_xbrl(client, link: str, path) -> None:
    """Download one XBRL file and show its periods and main figures."""
    from stock_news_analyzer.sources import xbrl

    try:
        _, content, _ = client.download("nse", [link])
        path.write_bytes(content)
        found, contexts = xbrl.facts(content), xbrl.contexts(content)
    except Exception as exc:
        typer.echo(f"  XBRL {link}: FAILED {type(exc).__name__}: {exc}")
        return
    typer.echo(f"  XBRL {link}: {len(content):,} bytes, {len(found)} facts, saved to {path}")
    plain = {k: v for k, v in contexts.items() if "[" not in v}
    typer.echo("  contexts without dimensions: " + "; ".join(f"{k}={v}" for k, v in plain.items()))
    wanted = ("RevenueFromOperations", "Income", "ProfitLossForPeriod", "ProfitBeforeTax")
    for tag, context, value in found:
        if tag in wanted or "OwnersOfParent" in tag or tag.startswith("BasicEarnings"):
            typer.echo(f"    {tag:<55} {context:<12} {value[:30]}")


def _probe_integrated(client, company, index: str, out_dir) -> None:
    """Try the candidate listings of integrated filings, and show the company's stored NSE
    announcements that carry XBRL."""
    import json

    from sqlalchemy import select

    from stock_news_analyzer.models import Document, DocumentCompany

    for url, extra in INTEGRATED_CANDIDATES:
        params = {"index": index, "symbol": company.nse_symbol, **extra}
        try:
            data = client.nse_json(url, params)
        except Exception as exc:
            typer.echo(f"integrated {url} {extra}: FAILED {type(exc).__name__}: {exc}")
            continue
        rows = data if isinstance(data, list) else data.get("data", data)
        name = url.rsplit("/", 1)[-1] + "".join(f"-{v}" for v in extra.values())
        (out_dir / f"{company.nse_symbol}-{name}.json").write_text(json.dumps(data, indent=1))
        count = len(rows) if isinstance(rows, list) else "?"
        typer.echo(f"integrated {url} {extra}: {count} rows")
        first = rows[0] if isinstance(rows, list) and rows else rows
        typer.echo(f"  first: {str(first)[:600]}")
        link = first.get("xbrl") if isinstance(first, dict) else None
        if extra and link and link.endswith(".xml"):
            _probe_xbrl(client, link, out_dir / f"{company.nse_symbol}-integrated.xml")
    with get_session() as session:
        docs = session.scalars(
            select(Document)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(
                DocumentCompany.isin == company.isin,
                Document.source == "nse",
                Document.raw["hasXbrl"].astext.in_(("true", "True", "1")),
            )
            .order_by(Document.published_at.desc())
            .limit(3)
        ).all()
        typer.echo(f"stored NSE announcements with XBRL: {len(docs)} shown")
        for d in docs:
            typer.echo(f"  {d.published_at:%d %b %Y} {d.doc_type}: {str(d.raw)[:600]}")


@results_app.command("probe")
def results_probe(
    symbol: str = typer.Argument(..., help="NSE symbol."),
    period: str = typer.Option(
        None, help="Quarterly, Half-Yearly, Annual or Others (default: all)."
    ),
) -> None:
    """Show NSE's results listing and one XBRL file for a stock, to check their format."""
    import json

    from stock_news_analyzer.sources import xbrl
    from stock_news_analyzer.sources.exchange_http import SME_SERIES, ExchangeClient

    with get_session() as session:
        company = _companies_or_exit(session, symbol)[0]
    index = "sme" if company.nse_series in SME_SERIES else "equities"
    out_dir = get_settings().data_dir / "probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ExchangeClient()
    link = None
    for p in [period] if period else ["Quarterly", "Half-Yearly", "Annual", "Others"]:
        try:
            rows = client.nse_financial_results(company.nse_symbol, p, index)
        except Exception as exc:  # a probe reports any failure and carries on
            typer.echo(f"{p} ({index}): FAILED {type(exc).__name__}: {exc}")
            continue
        typer.echo(f"{p} ({index}): {len(rows)} filings")
        (out_dir / f"{company.nse_symbol}-{p}.json").write_text(json.dumps(rows, indent=1))
        if rows:
            typer.echo(f"  fields: {', '.join(rows[0])}")
        for row in rows[:3]:
            typer.echo("  " + "; ".join(f"{k}={str(v)[:60]}" for k, v in row.items() if v))
        for row in rows:
            xml = next((v for v in row.values() if isinstance(v, str) and v.endswith(".xml")), None)
            if xml and not link:
                link = xml
    _probe_integrated(client, company, index, out_dir)
    if not link:
        typer.echo("no XBRL link found in the listings above")
        return
    if link.startswith("/"):
        link = "https://nsearchives.nseindia.com" + link
    try:
        _, content, _ = client.download("nse", [link])
    except Exception as exc:
        typer.echo(f"XBRL {link}: FAILED {type(exc).__name__}: {exc}")
        return
    path = out_dir / f"{company.nse_symbol}.xml"
    path.write_bytes(content)
    try:
        found, periods = xbrl.facts(content), xbrl.contexts(content)
    except Exception as exc:  # not XML after all: show what came back
        typer.echo(f"XBRL {link}: not readable as XML ({exc}); first bytes: {content[:300]!r}")
        return
    typer.echo(f"XBRL {link}: {len(content):,} bytes, {len(found)} facts, saved to {path}")
    typer.echo("contexts: " + "; ".join(f"{k}={v}" for k, v in list(periods.items())[:12]))
    wanted = ("revenue", "income", "profit", "finance", "depreciation", "earningspershare", "tax")
    shown = [f for f in found if any(w in f[0].lower() for w in wanted)]
    for tag, context, value in (shown or found)[:60]:
        typer.echo(f"  {tag:<60} {context:<14} {value[:40]}")


@results_app.command("xbrl")
def results_xbrl(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(None, help="Periods ending from YYYY-MM-DD (default: 800 days)."),
) -> None:
    """Take results from NSE's XBRL files (exact figures, no LLM) for every period listed."""
    from stock_news_analyzer.agents import xbrl_results
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    start = datetime.strptime(since, "%Y-%m-%d").date() if since else None
    with get_session() as session:
        result = xbrl_results.import_results(
            session, ExchangeClient(), symbol=symbol, since=start, progress=typer.echo
        )
    typer.echo(
        f"{result.periods} periods from XBRL ({result.corrected} replaced a figure read from "
        f"the PDF that differed by more than 1%); {result.skipped} already from XBRL; "
        f"{result.rejected} quarters rejected as half years"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")


@results_app.command("list")
def results_list(symbol: str = typer.Argument(..., help="NSE symbol.")) -> None:
    """A company's results, period by period: revenue, EBITDA, profit, growth, margins."""
    from stock_news_analyzer.agents import results as rs

    with get_session() as session:
        company = _companies_or_exit(session, symbol)[0]
        rows = rs.table(session, company.isin)
    if not rows:
        typer.echo(f"no results read for {symbol} yet; run: sna results run --symbol {symbol}")
        return
    typer.echo(
        f"{'period':<9} {'revenue':>10} {'y/y':>7} {'EBITDA':>9} {'margin':>7} {'PAT':>9} "
        f"{'y/y':>7} {'EPS':>7}  basis   (Rs crore)"
    )
    for r in rows:
        flags = ("" if r["checked"] else "  not all figures found as written") + (
            "" if r["own_filing"] else "  (from a later filing's comparative column)"
        )
        flags = "  XBRL" if r["from_xbrl"] else flags
        typer.echo(
            f"{r['period']:<9} {_cr(r['revenue_cr']):>10} {_x(r['revenue_yoy'], '{:+.0%}'):>7} "
            f"{_cr(r['ebitda_cr']):>9} {_x(r['ebitda_margin'], '{:.1%}'):>7} "
            f"{_cr(r['pat_cr']):>9} {_x(r['pat_yoy'], '{:+.0%}'):>7} "
            f"{_x(r['eps'], '{:.2f}'):>7}  {r['basis']}{flags}"
        )
    typer.echo(
        "EBITDA: profit before tax + finance costs + depreciation - other income. y/y: on the "
        "same period a year earlier."
    )


@results_app.command("coverage")
def results_coverage() -> None:
    """For every watchlist stock: results filings found and read, periods stored."""
    from stock_news_analyzer.agents import results as rs

    with get_session() as session:
        rows = rs.coverage(session)
    typer.echo(
        f"{'':<11} {'filings':>7} {'read':>5} {'copies':>6} {'none':>5} {'no text':>7} "
        f"{'failed':>6} {'no PDF':>6} {'unread':>6} {'periods':>7}  latest"
    )
    for r in rows:
        typer.echo(
            f"{r['symbol']:<11} {r['filings']:>7} {r['read']:>5} {r['copies']:>6} "
            f"{r['no_figures']:>5} {r['no_text']:>7} {r['failed']:>6} {r['no_pdf']:>6} "
            f"{r['unread']:>6} "
            f"{r['periods']:>7}  {r['latest'] or '–'}"
        )
    typer.echo(
        "copies: the same period already read from another filing. none: no results statement "
        "in it. no text: a scanned PDF. failed: the model's answer was unusable; the period's "
        "next filing is tried instead. no PDF: run `sna filings attachments --pdf important`. "
        "unread: run `sna results run` (filings older than 800 days stay unread)."
    )


@results_app.command("reset")
def results_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget results read so `sna results run` reads them again."""
    from stock_news_analyzer.agents.results import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} results?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol)
    typer.echo(f"{count} rows removed; run `sna results run` to read them again")


# --- events ----------------------------------------------------------------------


@events_app.command("run")
def events_run(
    symbol: str = typer.Option(None, help="Only this NSE symbol."),
    since: str = typer.Option(None, help="Filings from YYYY-MM-DD (default: the last 400 days)."),
    limit: int = typer.Option(None, help="At most this many extraction calls."),
    fetch: bool = typer.Option(True, help="Download PDFs not downloaded yet (up to 300 a run)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask before spending more than $1."),
) -> None:
    """Read filings not read yet for events (Haiku), then check the new events (QA Checker:
    code checks, and Sonnet for flagged or important ones)."""
    from datetime import timedelta

    from stock_news_analyzer.agents import events as ev
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = (
        datetime.strptime(since, "%Y-%m-%d").date()
        if since
        else datetime.now(fl.IST).date() - timedelta(days=ev.EVENT_DAYS)
    )
    model = get_settings().llm_model_triage
    with get_session() as session:
        waiting = ev.pending(session, start, symbol)
        calls, estimate = ev.estimate(waiting, model)
        typer.echo(
            f"{len(waiting)} filings to look at since {start:%d %b %Y}: about {calls} calls; "
            f"roughly ${estimate:.2f} with {model}, plus the second pass on some events"
        )
        if estimate > 1 and not yes and not typer.confirm("Go ahead?"):
            raise typer.Exit(1)
        collector = _collector(session, "important") if fetch else None
        try:
            result = ev.run(
                session,
                LLM(session),
                since=start,
                symbol=symbol,
                limit=limit,
                fetch=collector.fetch_attachment if collector else None,
                progress=typer.echo,
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.events} events from {result.filings} filings ({result.no_event} with no event, "
        f"{result.duplicates} copies from the other exchange, {result.failed} unusable answers; "
        f"{result.fetched} PDFs downloaded)"
    )
    typer.echo(
        f"QA: {result.passed} passed, {result.flagged} flagged, {result.rejected} failed, "
        f"{result.same_event} already recorded; {result.second_pass} second passes"
    )
    typer.echo(
        f"{result.calls} extraction calls, ${result.cost_usd:.4f} "
        f"(this month ${spent:.2f} of ${get_settings().llm_monthly_budget_usd:.2f})"
    )
    if result.waiting:
        typer.echo(f"{result.waiting} filings have no PDF yet: run this again")
    if result.flagged or result.rejected:
        typer.echo("see them with: sna events review")
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


def _event_line(e, symbol: str | None = None) -> str:
    from stock_news_analyzer.agents.events import amount

    value = f"  {amount(e)}" if e.value_cr is not None else ""
    who = f"{symbol:<11} " if symbol else ""
    return (
        f"#{e.id:<5} {who}{e.published_at.astimezone(fl.IST):%d %b %Y}  "
        f"{e.event_type:<17} {e.importance} {e.sentiment:<8} {e.headline}{value}"
    )


@events_app.command("list")
def events_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: every stock)."),
    days: int = typer.Option(90, help="How many days back."),
    event_type: str = typer.Option(None, "--type", help="Only this type, e.g. credit_rating."),
    importance: int = typer.Option(1, help="Only events at least this important (1-5)."),
    hidden: bool = typer.Option(False, "--all", help="Also failed, rejected and repeated ones."),
) -> None:
    """Events, newest first: type, importance (1-5), sentiment, headline, amount."""
    from datetime import timedelta

    from sqlalchemy import select

    from stock_news_analyzer.agents import qa
    from stock_news_analyzer.models import Company, Event

    since = datetime.now(fl.IST) - timedelta(days=days)
    with get_session() as session:
        query = (
            select(Event, Company.nse_symbol)
            .join(Company, Company.isin == Event.isin)
            .where(Event.published_at >= since, Event.importance >= importance)
            .order_by(Event.published_at.desc(), Event.id)
        )
        if symbol:
            query = query.where(Company.nse_symbol == symbol.upper())
        if event_type:
            query = query.where(Event.event_type == event_type)
        if not hidden:
            query = query.where(qa.shown())
        rows = session.execute(query).all()
        if not rows:
            typer.echo("no events in that window; run: sna events run")
            return
        for e, sym in rows:
            typer.echo(_event_line(e, None if symbol else sym))
            mark = {"flagged": "unchecked: ", "failed": "failed QA: ", "duplicate": ""}
            if e.qa_status in mark and e.review is None:
                typer.echo(f"{'':<7}{mark[e.qa_status]}{'; '.join(e.qa_notes)}")
            elif e.review:
                typer.echo(
                    f"{'':<7}you {e.review} it{': ' + e.review_note if e.review_note else ''}"
                )


@events_app.command("show")
def events_show(
    event_id: int = typer.Argument(..., help="Event number, from `sna events list`."),
) -> None:
    """One event in full: every field, its quote, the QA notes and the filing."""
    from stock_news_analyzer.models import Company, Document, Event

    with get_session() as session:
        e = session.get(Event, event_id)
        if e is None:
            typer.echo(f"no event #{event_id}")
            raise typer.Exit(1)
        company = session.get(Company, e.isin)
        doc = session.get(Document, e.document_id)
        typer.echo(_event_line(e, company.nse_symbol or company.isin))
        for name in (
            "event_date",
            "value_as_written",
            "value_kind",
            "counterparty",
            "person",
            "role",
            "action",
            "rating_from",
            "rating_to",
            "stake_pct",
            "shares",
        ):
            if getattr(e, name) is not None:
                typer.echo(f"  {name}: {getattr(e, name)}")
        typer.echo(f"  quote{'' if e.quote_found else ' (not found in the filing)'}: {e.quote}")
        typer.echo(f"  QA: {e.qa_status}{' (' + e.qa_model + ')' if e.qa_model else ''}")
        for note in e.qa_notes:
            typer.echo(f"    - {note}")
        if e.review:
            typer.echo(f"  you {e.review} it {e.reviewed_at:%d %b %Y}: {e.review_note or ''}")
        typer.echo(f"  filing #{doc.id} ({doc.source}): {doc.title}")
        if doc.attachment_url:
            typer.echo(f"  {doc.attachment_url}")


@events_app.command("review")
def events_review() -> None:
    """The review queue: events the QA Checker flagged or failed, waiting for your decision."""
    from stock_news_analyzer.agents import qa

    with get_session() as session:
        rows = qa.review_queue(session)
        if not rows:
            typer.echo("nothing to review")
            return
        for e, company in rows:
            typer.echo(_event_line(e, company.nse_symbol or company.isin))
            typer.echo(f"{'':<7}{e.qa_status}: {'; '.join(e.qa_notes)}")
    typer.echo(
        f"{len(rows)} to review. `sna events show ID` for the details, then "
        "`sna events accept ID` or `sna events reject ID` (add --note to say why)"
    )


def _decide(event_id: int, accept: bool, note: str | None) -> None:
    from stock_news_analyzer.agents import qa

    with get_session() as session:
        try:
            e = qa.decide(session, event_id, accept, note)
        except LookupError as exc:
            typer.echo(str(exc))
            raise typer.Exit(1) from exc
        typer.echo(f"#{e.id} {e.review}: {e.headline}")


@events_app.command("accept")
def events_accept(
    event_id: int = typer.Argument(..., help="Event number."),
    note: str = typer.Option(None, help="Why, for the record."),
) -> None:
    """Accept an event: it is shown although the QA Checker doubted it."""
    _decide(event_id, True, note)


@events_app.command("reject")
def events_reject(
    event_id: int = typer.Argument(..., help="Event number."),
    note: str = typer.Option(None, help="What was wrong, for the record."),
) -> None:
    """Reject an event: it is hidden, and kept as an example of a wrong extraction."""
    _decide(event_id, False, note)


@events_app.command("coverage")
def events_coverage() -> None:
    """For every watchlist stock: filings that may announce events, how each was handled, QA."""
    from stock_news_analyzer.agents import events as ev

    with get_session() as session:
        rows = ev.coverage(session)
    typer.echo(
        f"{'':<11} {'filings':>7} {'events':>6} {'none':>5} {'copies':>6} {'failed':>6} "
        f"{'no PDF':>6} {'unread':>6} | {'events':>6} {'passed':>6} {'flagged':>7} "
        f"{'QA fail':>7} {'repeat':>6}"
    )
    for r in rows:
        typer.echo(
            f"{r['symbol']:<11} {r['filings']:>7} {r['extracted']:>6} {r['no_event']:>5} "
            f"{r['copies']:>6} {r['failed']:>6} {r['no_pdf']:>6} {r['unread']:>6} | "
            f"{r['events']:>6} {r['passed']:>6} {r['flagged']:>7} {r['qa_failed']:>7} "
            f"{r['same_event']:>6}"
        )
    typer.echo(
        "Left: filings whose title names an event; with events, none (routine), copies (the "
        "other exchange's), failed (unusable answer), no PDF and unread (run `sna events run`). "
        "Right: events; passed, flagged (in `sna events review`), failed QA, and repeats of an "
        "event from an earlier filing."
    )


@events_app.command("reset")
def events_reset(
    symbol: str = typer.Option(None, help="Only this NSE symbol (default: every stock)."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask for confirmation."),
) -> None:
    """Forget events (and your reviews of them) so `sna events run` reads the filings again."""
    from stock_news_analyzer.agents.events import reset

    what = f"{symbol}'s" if symbol else "all"
    if not yes and not typer.confirm(f"Forget {what} events, including your reviews?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = reset(session, symbol)
    typer.echo(f"{count} rows removed; run `sna events run` to read them again")


# --- red flags -------------------------------------------------------------------


@flags_app.command("run")
def flags_run() -> None:
    """Raise red flags from the checked events and from overdue results (no LLM)."""
    from stock_news_analyzer.agents import redflags

    with get_session() as session:
        result = redflags.scan(session)
    counts = ", ".join(f"{n} {s}" for s, n in sorted(result.by_severity.items())) or "none new"
    regraded = f"; {result.regraded} re-graded" if result.regraded else ""
    typer.echo(
        f"{result.raised} red flags raised ({counts}){regraded}; see them with: sna flags list"
    )


@flags_app.command("list")
def flags_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: every stock)."),
    days: int = typer.Option(365, help="How many days back."),
    low: bool = typer.Option(False, "--low", help="Also low-severity flags."),
    dismissed: bool = typer.Option(False, "--dismissed", help="Also those you dismissed."),
) -> None:
    """Red flags, most serious first."""
    from stock_news_analyzer.agents import redflags

    severities = redflags.SEVERITIES if low else ("high", "medium")
    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        rows = redflags.open_flags(session, days, severities, isin, dismissed)
        if not rows:
            typer.echo("no red flags in that window")
            return
        for f, _company in rows:
            detail = f" ({f.detail})" if f.detail else ""
            gone = f"  [dismissed: {f.note or ''}]" if f.dismissed_at else ""
            typer.echo(
                f"#{f.id:<5} {f.severity.upper():<6} {f.flagged_on:%d %b %Y}  "
                f"{f.kind:<25} {f.title}{detail}{gone}"
            )
    typer.echo("`sna events show` with the event behind a flag; `sna flags dismiss ID --note ...`")


@flags_app.command("dismiss")
def flags_dismiss(
    flag_id: int = typer.Argument(..., help="Flag number, from `sna flags list`."),
    note: str = typer.Option(None, help="Why, for the record."),
) -> None:
    """Dismiss a red flag once dealt with; it stays on record with your note."""
    from stock_news_analyzer.agents import redflags

    with get_session() as session:
        try:
            f = redflags.dismiss(session, flag_id, note)
        except LookupError as exc:
            typer.echo(str(exc))
            raise typer.Exit(1) from exc
        typer.echo(f"#{f.id} dismissed: {f.title}")


# --- bullion ---------------------------------------------------------------------


@bullion_app.command("probe")
def bullion_probe() -> None:
    """Check which sources answer for global gold, silver and USD/INR (stooq, Yahoo)."""
    from datetime import timedelta

    from stock_news_analyzer.sources import markets
    from stock_news_analyzer.sources.news import NewsClient

    client = NewsClient()
    end = datetime.now(fl.IST).date()
    start = end - timedelta(days=14)
    for series in markets.SERIES:
        for source, url, parse in (
            ("yahoo", markets.yahoo_url(series, start, end), markets.parse_yahoo),
            (
                "hourly",
                markets.yahoo_url(series, start, end, interval="60m"),
                markets.parse_yahoo_at,
            ),
            ("stooq", markets.stooq_url(series, start, end), markets.parse_stooq),
        ):
            try:
                rows = parse(client.fetch(url))
                last_day, last = rows[-1]
                typer.echo(f"{series:<7} {source:<6} ok: {len(rows)} days, {last_day} {last:,.4f}")
            except Exception as exc:
                typer.echo(f"{series:<7} {source:<6} FAILED: {str(exc)[:150]}")


@bullion_app.command("run")
def bullion_run(
    notes: bool = typer.Option(True, help="Write notes on recent unusual days (Sonnet)."),
) -> None:
    """Fetch global prices, split each day's move, collect bullion news, explain unusual days."""
    from stock_news_analyzer.agents import bullion as bu
    from stock_news_analyzer.llm import LLM, month_spend
    from stock_news_analyzer.sources.news import NewsClient

    with get_session() as session:
        if not bu.watched_metals(session):
            typer.echo("no bullion on the watchlist; add it with: sna watchlist add gold")
            raise typer.Exit(1)
        llm = LLM(session) if notes and get_settings().anthropic_api_key else None
        result = bu.run(session, llm, NewsClient().fetch, notes=notes, progress=typer.echo)
        spent = month_spend(session)
    sources = ", ".join(f"{s} from {src}" for s, src in result.series.items()) or "none"
    typer.echo(
        f"{result.points} global closes ({sources}); {result.days} days split, "
        f"{result.unusual} unusual; {result.articles} new articles; {result.notes} notes, "
        f"${result.cost_usd:.4f} (this month ${spent:.2f})"
    )
    if result.waiting:
        typer.echo(f"{result.waiting} notes wait for their news; the next run tries again")
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@bullion_app.command("list")
def bullion_list(
    metal: str = typer.Argument("gold", help="gold or silver."),
    days: int = typer.Option(30, help="How many days back."),
    unusual: bool = typer.Option(False, "--unusual", help="Only unusual days."),
) -> None:
    """Day by day: the rupee move, its split, and the note on unusual days."""
    from stock_news_analyzer.agents import bullion as bu

    with get_session() as session:
        rows = bu.recent_moves(session, metal.upper(), days)
        rows = [m for m in rows if m.unusual] if unusual else rows
        if not rows:
            typer.echo(f"no {metal} moves stored for that window; run: sna bullion run")
            return
        typer.echo(
            f"{'day':<10} {metal.upper() + ' ETF':>12} {'rupees':>8} {'global':>8} "
            f"{'rupee':>8} {'other':>8} {'z':>5}  driver"
        )
        for m in rows:
            typer.echo(
                f"{m.trade_date:%d %b %y}  {m.close:>12,.2f} {bu._pct(m.inr_return):>8} "
                f"{bu._pct(m.global_return):>8} {bu._pct(m.fx_return):>8} "
                f"{bu._pct(m.other_return):>8} "
                f"{(f'{m.zscore:+.1f}' if m.zscore is not None else '–'):>5}  "
                f"{'*' if m.unusual else ' '}{m.driver or ''}"
            )
            if m.note:
                typer.echo(f"{'':<12}{m.note}")
    typer.echo(
        "rupees = global + rupee + other (log returns). rupee: USD/INR. other: duty, local "
        "premium, and the gap between the Indian and New York closes. * unusual (2σ)."
    )


@bullion_app.command("explain")
def bullion_explain(
    day: str = typer.Argument(..., help="YYYY-MM-DD."),
    metal: str = typer.Option("gold", help="gold or silver."),
) -> None:
    """Write (or rewrite) the note for one day, after searching that day's news (Sonnet)."""
    from stock_news_analyzer.agents import bullion as bu
    from stock_news_analyzer.llm import LLM
    from stock_news_analyzer.sources.news import NewsClient

    when = datetime.strptime(day, "%Y-%m-%d").date()
    with get_session() as session:
        try:
            m = bu.explain(session, LLM(session), metal.upper(), when, NewsClient().fetch)
        except (LookupError, bu.NoNews) as exc:
            typer.echo(str(exc))
            raise typer.Exit(1) from exc
        typer.echo(f"{m.metal.title()} {m.trade_date:%d %b %Y}: {bu.summary(m)}")
        typer.echo(f"{m.driver}: {m.note}")


@bullion_app.command("reset")
def bullion_reset(yes: bool = typer.Option(False, "--yes", help="Don't ask.")) -> None:
    """Forget global prices, splits and notes, so `sna bullion run` fetches them again."""
    from stock_news_analyzer.agents import bullion as bu

    if not yes and not typer.confirm("Forget bullion prices, splits and notes?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = bu.reset(session)
    typer.echo(f"{count} rows removed; run `sna bullion run` to fetch them again")


# --- themes ----------------------------------------------------------------------


@themes_app.command("run")
def themes_run(
    since: str = typer.Option(None, help="Items from YYYY-MM-DD (default: the last 400 days)."),
    limit: int = typer.Option(None, help="At most this many LLM calls."),
    yes: bool = typer.Option(False, "--yes", help="Don't ask before spending more than $1."),
) -> None:
    """Tag new events, orders and call points with themes (Haiku), then write read-across."""
    from datetime import timedelta

    from stock_news_analyzer.agents import themes as th
    from stock_news_analyzer.llm import LLM, LLMNotConfigured, month_spend

    start = (
        datetime.strptime(since, "%Y-%m-%d").date()
        if since
        else datetime.now(fl.IST).date() - timedelta(days=th.THEME_DAYS)
    )
    model = get_settings().llm_model_triage
    with get_session() as session:
        items = th.pending(session, start)
        calls, estimate = th.estimate(items, model)
        typer.echo(
            f"{len(items)} items to tag since {start:%d %b %Y}: about {calls} calls, "
            f"roughly ${estimate:.2f} with {model}"
        )
        if estimate > 1 and not yes and not typer.confirm("Go ahead?"):
            raise typer.Exit(1)
        try:
            result = th.run(session, LLM(session), since=start, limit=limit, progress=typer.echo)
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        spent = month_spend(session)
    typer.echo(
        f"{result.items} items tagged ({result.tags} tags, {result.untagged} with no theme); "
        f"{result.signals} new read-across signals; {result.calls} LLM calls, "
        f"${result.cost_usd:.4f} (this month ${spent:.2f})"
    )
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        raise typer.Exit(1)


@themes_app.command("list")
def themes_list() -> None:
    """Every theme: items and companies in the last 90 days, against the 90 before."""
    from stock_news_analyzer.agents import themes as th

    with get_session() as session:
        rows = th.summary(session)
    typer.echo(
        f"{'theme':<36} {'90d':>4} {'prev':>5} {'trend':>6} {'+':>3} {'-':>3} "
        f"{'orders Rs cr':>12}  companies"
    )
    for r in rows:
        if not r["items"] and not r["before"]:
            continue
        trend = "new" if not r["before"] else f"{r['items'] / r['before'] - 1:+.0%}"
        typer.echo(
            f"{r['name']:<36} {r['items']:>4} {r['before']:>5} {trend:>6} {r['positive']:>3} "
            f"{r['negative']:>3} {r['order_value_cr']:>12,.0f}  {', '.join(r['companies'])}"
        )
    typer.echo(
        "90d: events, orders and call points tagged with the theme in the last 90 days; prev: "
        "the 90 before. +/-: positive and negative items. `sna themes show KEY` for one theme."
    )


@themes_app.command("show")
def themes_show(
    theme: str = typer.Argument(..., help="Theme key, e.g. data_centres (see config/themes.yaml)."),
    days: int = typer.Option(90, help="Items from this many days back."),
) -> None:
    """One theme: month by month, then its recent items."""
    from stock_news_analyzer.agents import themes as th

    known = th.load_themes()
    if theme not in known:
        typer.echo(f"unknown theme {theme}; known: {', '.join(known)}")
        raise typer.Exit(1)
    with get_session() as session:
        months = th.monthly(session, theme)
        items = th.recent_items(session, theme, days)
    typer.echo(f"{known[theme]['name']}")
    typer.echo(f"{'month':<9} {'items':>5} {'cos':>4} {'+':>3} {'-':>3} {'orders Rs cr':>12}")
    for m in months:
        typer.echo(
            f"{m['month']:%b %Y} {m['items']:>6} {m['companies']:>4} {m['positive']:>3} "
            f"{m['negative']:>3} {m['order_value_cr']:>12,.0f}"
        )
    typer.echo("")
    for t, symbol in items:
        value = f"  Rs {t.value_cr:,.0f} cr" if t.value_cr and t.value_cr >= 1 else ""
        typer.echo(f"{t.on_date:%d %b %Y}  {symbol:<11} {t.title[:110]}{value}")


@themes_app.command("companies")
def themes_companies() -> None:
    """Each watchlist stock's core themes: the ones read-across uses."""
    from sqlalchemy import select

    from stock_news_analyzer.agents import themes as th
    from stock_news_analyzer.models import Company, WatchlistItem

    names = {k: t["name"] for k, t in th.load_themes().items()}
    with get_session() as session:
        core = th.core_themes(session)
        stocks = session.execute(
            select(Company.isin, Company.nse_symbol)
            .join(WatchlistItem, WatchlistItem.isin == Company.isin)
            .order_by(Company.nse_symbol)
        ).all()
    for isin, symbol in stocks:
        themes = ", ".join(names.get(t, t) for t in core.get(isin, [])) or "none yet"
        typer.echo(f"{symbol or isin:<11} {themes}")
    typer.echo(
        "Core themes: a stock's top three of the past year, each with at least two items and 15% "
        "of them. Read-across by theme goes only to stocks with the theme among these."
    )


@themes_app.command("signals")
def themes_signals(
    symbol: str = typer.Argument(None, help="Only read-across for this NSE symbol."),
    days: int = typer.Option(90, help="How many days back."),
) -> None:
    """Read-across: important orders and events at one company worth a look for another."""
    from stock_news_analyzer.agents import themes as th

    with get_session() as session:
        isin = _companies_or_exit(session, symbol)[0].isin if symbol else None
        rows = th.signals(session, isin, days)
        if not rows:
            typer.echo("no read-across in that window")
            return
        for s, target in rows:
            why = "peer" if s.relation == "peer" else s.relation.split(":", 1)[1].replace("_", " ")
            typer.echo(f"{s.on_date:%d %b %Y}  for {target:<11} ({why})  {s.title[:110]}")


@themes_app.command("reset")
def themes_reset(
    signals: bool = typer.Option(
        False, "--signals-only", help="Forget only the read-across, keep the tags (no LLM cost)."
    ),
    yes: bool = typer.Option(False, "--yes", help="Don't ask."),
) -> None:
    """Forget theme tags and read-across, so `sna themes run` tags everything again."""
    from stock_news_analyzer.agents import themes as th

    what = "read-across" if signals else "all theme tags and read-across"
    if not yes and not typer.confirm(f"Forget {what}?"):
        raise typer.Exit(1)
    with get_session() as session:
        count = th.reset(session, signals_only=signals)
    typer.echo(f"{count} rows removed; run `sna themes run` to write them again")


# --- bulk and block deals ------------------------------------------------------


def _deals_report(result) -> None:
    typer.echo(f"{result.seen} deals read, {result.new} new")
    for err in result.errors:
        typer.echo(f"error: {err}")
    if result.errors:
        typer.echo("if NSE keeps failing, try `sna deals probe` and paste its output")
        raise typer.Exit(1)


@deals_app.command("fetch")
def deals_fetch() -> None:
    """New bulk and block deals since the last stored day."""
    from stock_news_analyzer.agents import deals as dl
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    with get_session() as session:
        result = dl.collect(session, ExchangeClient(), dl.resume_date(session), progress=typer.echo)
    _deals_report(result)


@deals_app.command("backfill")
def deals_backfill(
    since: str = typer.Option(..., help="Start date, YYYY-MM-DD (e.g. 2023-10-01)."),
) -> None:
    """Deals from a start date, a month per request. Safe to re-run."""
    from stock_news_analyzer.agents import deals as dl
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    start = datetime.strptime(since, "%Y-%m-%d").date()
    with get_session() as session:
        result = dl.collect(session, ExchangeClient(), start, progress=typer.echo)
    _deals_report(result)


@deals_app.command("load")
def deals_load(
    file: Path = typer.Argument(..., help="A CSV or JSON file saved from NSE's deals page."),
    kind: str = typer.Option(..., help="bulk or block."),
) -> None:
    """Load deals from a file you downloaded from NSE (if the automatic fetch is blocked)."""
    from stock_news_analyzer.agents.deals import store
    from stock_news_analyzer.sources.deals import parse_deals

    deals = parse_deals(file.read_bytes(), kind)
    with get_session() as session:
        new = store(session, deals)
    typer.echo(f"{len(deals)} {kind} deals read, {new} new")


@deals_app.command("probe")
def deals_probe(days: int = typer.Option(7, help="How many days back.")) -> None:
    """Fetch recent deals and show the raw format, to check NSE's response."""
    from datetime import timedelta

    from stock_news_analyzer.sources.deals import parse_deals, records
    from stock_news_analyzer.sources.exchange_http import ExchangeClient, ExchangeError

    client = ExchangeClient()
    end = date.today()
    for kind in ("bulk", "block"):
        try:
            content = client.nse_deals(kind, end - timedelta(days=days), end)
        except ExchangeError as exc:
            typer.echo(f"{kind}: FAILED {exc}")
            continue
        rows = records(content)
        typer.echo(f"{kind}: {len(rows)} rows; first: {rows[0] if rows else '-'}")
        try:
            parsed = parse_deals(content, kind)
            typer.echo(f"  parsed {len(parsed)}; first: {parsed[0] if parsed else '-'}")
        except ValueError as exc:
            typer.echo(f"  could not parse: {exc}")


@deals_app.command("list")
def deals_list(
    symbol: str = typer.Argument(None, help="NSE symbol (default: all watchlist stocks)."),
    days: int = typer.Option(30, help="How many days back."),
) -> None:
    """Bulk and block deals in watchlist stocks, newest first."""
    from datetime import timedelta

    from sqlalchemy import select

    from stock_news_analyzer.models import Deal, WatchlistItem

    since = date.today() - timedelta(days=days)
    query = (
        select(Deal)
        .join(WatchlistItem, WatchlistItem.isin == Deal.isin)
        .where(Deal.trade_date >= since)
        .order_by(Deal.trade_date.desc(), Deal.symbol, Deal.quantity.desc())
    )
    if symbol:
        query = query.where(Deal.symbol == symbol.upper())
    with get_session() as session:
        deals = session.scalars(query).all()
        if not deals:
            typer.echo("no deals in that window")
            return
        for d in deals:
            price = f"{d.price:>10,.2f}" if d.price is not None else f"{'-':>10}"
            typer.echo(
                f"{d.trade_date:%d %b %Y}  {d.symbol:<11} {d.kind:<5} {d.side:<4} "
                f"{d.quantity:>12,} @ {price}  {d.client[:60]}"
            )


def _print_answer(session, answer) -> None:
    from stock_news_analyzer.agents import ask as qa

    typer.echo("")
    typer.echo(answer.text)
    if answer.sources:
        typer.echo("\nSources:")
        for ref in answer.sources:
            typer.echo(qa.describe_source(session, ref))
    typer.echo(f"\n{answer.steps} lookups with {answer.model}, ${answer.cost_usd:.4f}")


def _ask(question: str, model: str | None, name: str | None) -> None:
    from stock_news_analyzer.agents import ask as qa
    from stock_news_analyzer.llm import LLM, LLMError, LLMNotConfigured

    with get_session() as session:
        try:
            answer = qa.ask(
                session,
                LLM(session),
                question,
                model=model,
                name=name,
                progress=lambda line: typer.echo(f"  {line}"),
            )
        except LLMNotConfigured as exc:
            typer.echo(f"{exc}: add ANTHROPIC_API_KEY=... to .env (see .env.example)")
            raise typer.Exit(1) from exc
        except LLMError as exc:
            typer.echo(f"error: {exc}")
            raise typer.Exit(1) from exc
        _print_answer(session, answer)
        if name:
            typer.echo(f"saved as '{name}': ask again with `sna questions rerun {name}`")


@app.command("ask")
def ask_command(
    question: str = typer.Argument(..., help="The question, in quotes."),
    model: str = typer.Option(None, help="Model to use (default: the analysis model)."),
    save: str = typer.Option(None, "--save", help="Keep it as a saved report under this name."),
) -> None:
    """Analyst Q&A: ask a question about your companies; answered from the database, with
    sources."""
    _ask(question, model, save)


@questions_app.command("list")
def questions_list(
    limit: int = typer.Option(20, help="How many recent questions."),
    saved: bool = typer.Option(False, "--saved", help="Saved reports only."),
) -> None:
    """Recent questions (and saved reports) with their cost."""
    from sqlalchemy import select

    from stock_news_analyzer.models import Question

    with get_session() as session:
        q = select(Question).order_by(Question.asked_at.desc()).limit(limit)
        if saved:
            q = q.where(Question.name.is_not(None))
        rows = list(session.scalars(q))
        if not rows:
            typer.echo('no questions yet: try `sna ask "..."`')
        for r in rows:
            label = f"[{r.name}] " if r.name else ""
            typer.echo(
                f"{r.id:>5} {r.asked_at.astimezone(fl.IST):%d %b %H:%M} ${r.cost_usd:.3f} "
                f"{r.steps:>2} steps  {label}{r.question[:90]}"
            )


@questions_app.command("show")
def questions_show(ref: str = typer.Argument(..., help="Question id or saved name.")) -> None:
    """Show a stored answer again (no LLM call)."""
    from stock_news_analyzer.agents import ask as qa
    from stock_news_analyzer.models import Question

    with get_session() as session:
        row = session.get(Question, int(ref)) if ref.isdigit() else qa.saved(session, ref)
        if row is None:
            typer.echo(f"no question {ref}")
            raise typer.Exit(1)
        typer.echo(f"Q: {row.question}  ({row.asked_at.astimezone(fl.IST):%d %b %Y %H:%M})\n")
        typer.echo(row.answer)
        if row.sources:
            typer.echo("\nSources:")
            for s in row.sources:
                typer.echo(qa.describe_source(session, s))


@questions_app.command("rerun")
def questions_rerun(
    name: str = typer.Argument(..., help="The saved report's name."),
    model: str = typer.Option(None, help="Model to use (default: the analysis model)."),
) -> None:
    """Ask a saved report's question again, on today's data."""
    from stock_news_analyzer.agents import ask as qa

    with get_session() as session:
        row = qa.saved(session, name)
        question = row.question if row else None
    if question is None:
        typer.echo(f"no saved report '{name}'")
        raise typer.Exit(1)
    _ask(question, model, name)
