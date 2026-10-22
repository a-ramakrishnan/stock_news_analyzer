"""The dashboard: `sna ui` (or `make ui`) starts it at http://localhost:8501.

Every page only reads, except Manage stocks, which adds, edits and removes watchlist stocks
and can load a new stock's history. Regular collecting is done by the scheduler.
"""

import html
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.orchestrator import SCHEDULE_FILE, load_schedule, next_runs
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import get_engine
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.ui import actions, charts, queries

st.set_page_config(
    page_title="Stock News Analyzer", page_icon=":material/newspaper:", layout="wide"
)

# Our own chart colours (charts.py), not Streamlit's Plotly theme; no Plotly toolbar.
PLOT = {"theme": None, "config": {"displayModeBar": False}}
RANGES = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 3 * 365}


@st.cache_resource
def engine():
    return get_engine()


@st.cache_data(ttl=60, show_spinner=False)
def load(query: str, **kwargs):
    """Run one function from `queries` in a fresh session; results are kept for a minute."""
    with Session(engine()) as session:
        return getattr(queries, query)(session, **kwargs)


def dark() -> bool:
    return st.context.theme.type == "dark"


def pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x:+.2%}"


def stocks() -> list[dict]:
    """Watchlist stocks, the ones you own first."""
    return sorted(load("watchlist"), key=lambda s: not s["owned"])


def label(s: dict) -> str:
    return f"{s['symbol']} · {s['name']}" + ("" if s["owned"] else "  (watchlist)")


def stock_picker(key: str, include_all: bool = True) -> dict | None:
    """A select box of watchlist stocks; returns the chosen stock (None = all)."""
    options = ([None] if include_all else []) + stocks()
    return st.selectbox(
        "Stock",
        options,
        key=key,
        format_func=lambda s: "All stocks" if s is None else label(s),
    )


def no_data(message: str) -> None:
    st.info(message, icon=":material/info:")


# --- pages -------------------------------------------------------------------


# Compact tiles for the index strip: many indices fit on a row and wrap on narrow screens, and
# full names wrap instead of being cut off. Up/down carry an arrow and a sign, not only colour.
TILES_CSS = """
<style>
.sna-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:8px;
  margin:4px 0 12px}
.sna-tile{border:1px solid rgba(128,128,128,.3);border-radius:8px;padding:8px 10px}
.sna-tile .l{font-size:.78rem;opacity:.75;line-height:1.2}
.sna-tile .v{font-size:1.15rem;font-weight:600;margin:2px 0;font-variant-numeric:tabular-nums}
.sna-tile .c{font-size:.8rem;font-weight:600;font-variant-numeric:tabular-nums}
.sna-tile .up{color:#0ca30c}
.sna-tile .down{color:#d03b3b}
[data-testid="stMetricValue"]{font-size:1.6rem}
</style>
"""


def index_tiles(rows: list[dict]) -> None:
    tiles = []
    for m in rows:
        change = m["change"]
        if change is None:
            delta = '<div class="c">–</div>'
        else:
            arrow, cls = ("▲", "up") if change >= 0 else ("▼", "down")
            delta = f'<div class="c {cls}">{arrow} {change:+.2%}</div>'
        name = html.escape(m["index"])
        value = f"{m['close']:,.2f}" if m["close"] else "–"
        tiles.append(
            f'<div class="sna-tile" title="{name}, {m["date"]}"><div class="l">{name}</div>'
            f'<div class="v">{value}</div>{delta}</div>'
        )
    st.markdown(
        TILES_CSS + f'<div class="sna-tiles">{"".join(tiles)}</div>', unsafe_allow_html=True
    )


def stock_card(s: dict) -> None:
    threshold = get_settings().unusual_threshold
    with st.container(border=True):
        head, badge = st.columns([3, 1])
        head.markdown(f"**{s['symbol']}**  \n:gray[{s['name']}]")
        if s["unusual"]:
            badge.badge(
                "Unusual",
                icon=":material/warning:",
                color="red",
                help=f"Move vs Nifty 50 beyond {threshold}σ of the last 60 days",
            )
        spark = load("performance", isin=s["isin"], start=date.today() - timedelta(days=91))
        st.metric(
            f"Close {s['date']:%d %b}" if s["date"] else "Close",
            f"₹{s['close']:,.2f}" if s["close"] else "–",
            pct(s["stock_return"]) if s["stock_return"] is not None else None,
            chart_data=list(spark["stock"]) if not spark.empty else None,
            chart_type="line",
        )
        st.markdown(
            f"vs Nifty 50 **{pct(s['excess_return'])}** · "
            f"vs {s['sector_index'] or 'sector'} **{pct(s['sector_excess_return'])}** · "
            f"z **{s['zscore']:.1f}**"
            if s["zscore"] is not None
            else f"vs Nifty 50 **{pct(s['excess_return'])}**"
        )
        st.caption(f"Last 7 days: {s['filings_7d']} filings, {s['news_7d']} news articles")
        st.page_link(
            stock_page,
            label="Open",
            icon=":material/arrow_forward:",
            query_params={"symbol": s["symbol"]},
        )


def today_page() -> None:
    watch = stocks()
    if not watch:
        no_data("No stocks yet. Add them on the Manage stocks page.")
        return
    latest = max((s["date"] for s in watch if s["date"]), default=None)
    st.title("Today")
    st.caption(
        f"Last trading day loaded: {latest:%a %d %b %Y}"
        if latest
        else "No prices loaded yet: run `make prices`."
    )
    index_tiles(load("market"))

    owned = [s for s in watch if s["owned"]]
    watching = [s for s in watch if not s["owned"]]
    for title, group in (("Stocks I own", owned), ("Watchlist", watching)):
        st.subheader(f"{title} ({len(group)})")
        if not group:
            st.caption("None yet. Add stocks on the Manage stocks page.")
            continue
        cols = st.columns(3)
        for i, s in enumerate(group):
            with cols[i % 3]:
                stock_card(s)

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Latest digest")
        digest = queries.latest_digest(get_settings().data_dir)
        if digest:
            name, text = digest
            with st.expander(name, expanded=False):
                st.markdown(text)
        else:
            no_data("No digest saved yet. The scheduler writes one every morning.")
    with right:
        st.subheader("Data collection")
        last = load("last_runs")
        rows = [
            {
                "job": job,
                "last run": r["started"].strftime("%d %b %H:%M") if r else "never",
                "status": ("✅ ok" if r["status"] == "ok" else f"⚠️ {r['status']}") if r else "–",
            }
            for job, r in last.items()
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def stock_page_body() -> None:
    watch = stocks()
    if not watch:
        no_data("No stocks yet. Add them on the Manage stocks page.")
        return
    wanted = st.query_params.get("symbol")
    index = next((i for i, s in enumerate(watch) if s["symbol"] == wanted), 0)
    pick, span = st.columns([2, 1], vertical_alignment="bottom")
    with pick:
        s = st.selectbox("Stock", watch, index=index, format_func=label)
    with span:
        window = st.segmented_control("Range", list(RANGES), default="1Y", key="range") or "1Y"
    st.query_params["symbol"] = s["symbol"]

    st.title(s["name"])
    sector = s["sector_index"] or "no sector index"
    st.caption(
        f"NSE {s['symbol']} · benchmark Nifty 50 and {sector}" + (" · owned" if s["owned"] else "")
    )

    start = date.today() - timedelta(days=RANGES[window])
    perf = load("performance", isin=s["isin"], start=start)
    if perf.empty:
        no_data("No daily moves yet: run `make prices`.")
    else:
        lb = load("labels", isin=s["isin"])
        events = (
            lb[lb["type"].isin(queries.KEY_TYPES)]
            .sort_values("exchange")
            .drop_duplicates(["type", "day0"])
        )
        last = perf.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"{s['symbol']} over {window}", f"{last['stock'] - 100:+.1f}%")
        m2.metric(f"Nifty 50 over {window}", f"{last['nifty'] - 100:+.1f}%")
        if s["sector_index"] and pd.notna(last["sector"]):
            m3.metric(f"{s['sector_index']} over {window}", f"{last['sector'] - 100:+.1f}%")
        m4.metric("Unusual days", int(perf["unusual"].sum()))
        st.plotly_chart(
            charts.performance_chart(perf, s["symbol"], s["sector_index"], events, dark()),
            width="stretch",
            **PLOT,
        )
        st.markdown("**Daily return minus the Nifty 50's**")
        st.plotly_chart(
            charts.excess_bars(perf, dark=dark()),
            width="stretch",
            **PLOT,
        )
        st.caption(
            f"Adjusted for bonus issues, splits and dividends. Solid bars and circled "
            f"points are unusual days: beyond {get_settings().unusual_threshold}σ of the "
            f"previous 60 days. Diamonds mark key filings."
        )

    filings_tab, news_tab, reactions_tab, actions_tab = st.tabs(
        ["Filings", "News", "How it reacted", "Corporate actions"]
    )
    with filings_tab:
        filings_table(load("filings", isin=s["isin"], dedupe=True, limit=200), key="stock")
    with news_tab:
        news_table(load("news", isin=s["isin"], limit=200))
    with reactions_tab:
        reactions_table(load("labels", isin=s["isin"], news_too=True))
    with actions_tab:
        acts = load("corporate_actions", symbol=s["symbol"])
        if acts.empty:
            no_data("No corporate actions stored.")
        else:
            st.dataframe(
                acts,
                hide_index=True,
                width="stretch",
                column_config={
                    "ex_date": st.column_config.DateColumn("Ex-date", format="DD MMM YYYY"),
                    "price_factor": st.column_config.NumberColumn("Price factor", format="%.4f"),
                    "dividend": st.column_config.NumberColumn("Dividend", format="₹%.2f"),
                },
            )


def filings_table(df: pd.DataFrame, key: str) -> None:
    if df.empty:
        no_data("No filings match.")
        return
    event = st.dataframe(
        df.drop(columns=["id", "attachment_path"]),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"filings-{key}",
        column_config={
            "published": st.column_config.DatetimeColumn(
                "Published (IST)", format="DD MMM YYYY HH:mm"
            ),
            "title": st.column_config.TextColumn("Title", width="large"),
            "text_status": st.column_config.TextColumn("Text"),
            "attachment_url": st.column_config.LinkColumn("PDF", display_text="open"),
        },
    )
    rows = event.selection.rows
    if rows:
        doc = df.iloc[rows[0]]
        text = load("document_text", doc_id=int(doc["id"]))
        st.markdown(f"**{doc['title']}**")
        st.caption(f"{doc['exchange']} · {doc['type']} · {doc['published']:%d %b %Y %H:%M} IST")
        st.text_area("Extracted text", text or "(no text extracted)", height=320, key=f"text-{key}")
    else:
        st.caption("Select a row to read the filing's text.")


def news_table(df: pd.DataFrame) -> None:
    if df.empty:
        no_data("No articles match.")
        return
    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        column_config={
            "published": st.column_config.DatetimeColumn(
                "Published (IST)", format="DD MMM YYYY HH:mm"
            ),
            "title": st.column_config.TextColumn("Headline", width="large"),
            "url": st.column_config.LinkColumn("Link", display_text="read"),
        },
    )


def reactions_table(df: pd.DataFrame) -> None:
    if df.empty:
        no_data("No labels yet: run `make prices`.")
        return
    shown = df.drop(
        columns=["document_id", "isin", "sector_excess_1d", "sector_excess_5d", "sector_excess_20d"]
    )
    for col in ("excess_1d", "excess_5d", "excess_20d"):
        shown[col] = shown[col] * 100
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config={
            "published": st.column_config.DatetimeColumn(
                "Published (IST)", format="DD MMM YYYY HH:mm"
            ),
            "day0": st.column_config.DateColumn("First close", format="DD MMM"),
            "title": st.column_config.TextColumn("Title", width="large"),
            "excess_1d": st.column_config.NumberColumn("vs Nifty 1d", format="%+.2f%%"),
            "excess_5d": st.column_config.NumberColumn("5d", format="%+.2f%%"),
            "excess_20d": st.column_config.NumberColumn("20d", format="%+.2f%%"),
        },
    )
    st.caption(
        "Return vs Nifty 50 from the first close that could reflect the item. Blank "
        "until enough trading days have passed."
    )


def filings_page() -> None:
    st.title("Filings")
    a, b, c, d = st.columns([1.2, 1.5, 1.5, 1], vertical_alignment="bottom")
    with a:
        s = stock_picker("filings-stock")
    with b:
        types = st.multiselect("Type", load("doc_types"))
    with c:
        search = st.text_input("Search title and text", placeholder="e.g. order, rating")
    with d:
        since = st.date_input("Since", date.today() - timedelta(days=90), format="DD/MM/YYYY")
    dedupe = st.toggle("Show BSE and NSE copies once", value=True)
    df = load(
        "filings",
        isin=s["isin"] if s else None,
        doc_types=types or None,
        search=search or None,
        since=since,
        dedupe=dedupe,
    )
    st.caption(f"{len(df)} filings")
    filings_table(df, key="all")


def news_page() -> None:
    st.title("News")
    a, b, c = st.columns([1.2, 2, 1], vertical_alignment="bottom")
    with a:
        s = stock_picker("news-stock")
    with b:
        search = st.text_input("Search headlines")
    with c:
        since = st.date_input(
            "Since", date.today() - timedelta(days=30), format="DD/MM/YYYY", key="news-since"
        )
    df = load("news", isin=s["isin"] if s else None, search=search or None, since=since)
    st.caption(f"{len(df)} articles")
    news_table(df)


def moves_page() -> None:
    st.title("What moves the stock")
    st.caption(
        "Average return vs Nifty 50 after each kind of filing, 1, 5 and 20 trading days "
        "later. A BSE and an NSE copy of the same announcement count once."
    )
    s = stock_picker("moves-stock")
    study = load("event_study", isin=s["isin"] if s else None)
    if study.empty:
        no_data("No labelled filings yet: run `make prices` (and optionally a filings backfill).")
        return
    st.plotly_chart(charts.event_study_chart(study, dark()), width="stretch", **PLOT)
    st.warning(
        "Averages of a handful of events are mostly noise. The number in brackets is how "
        "many events each row is based on; the 20-day average uses only events at least "
        "20 trading days old.",
        icon=":material/info:",
    )
    table = study.copy()
    for col in ("avg_1d", "avg_5d", "avg_20d"):
        table[col] = table[col] * 100
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "avg_1d": st.column_config.NumberColumn("Avg 1d", format="%+.2f%%"),
            "avg_5d": st.column_config.NumberColumn("Avg 5d", format="%+.2f%%"),
            "avg_20d": st.column_config.NumberColumn("Avg 20d", format="%+.2f%%"),
            "n_20d": st.column_config.NumberColumn("Events with 20d"),
        },
    )
    if st.toggle("Show the filings behind each type"):
        lb = load("labels", isin=s["isin"] if s else None)
        reactions_table(lb)


def manage_page() -> None:
    st.title("Manage stocks")
    st.caption(
        "Changes here take effect straight away: the scheduler picks up new stocks on its next "
        "run. `make watchlist` re-applies config/watchlist.yaml, so a stock listed there comes "
        "back as written in the file."
    )
    with Session(engine()) as session:
        add_stock_form(session)
        st.divider()
        edit_stocks(session)


def add_stock_form(session: Session) -> None:
    st.subheader("Add a stock")
    query = st.text_input(
        "Company name, NSE symbol, BSE code or ISIN", placeholder="e.g. Mrs Bectors, BECTORFOOD"
    )
    matches = actions.search(session, query) if query else []
    if query and not matches:
        st.warning(
            "No listed company matches. If it listed recently, refresh the company list with "
            "`make securities`.",
            icon=":material/search_off:",
        )
    if not matches:
        return
    pick = st.radio(
        "Matches",
        matches,
        format_func=lambda m: (
            f"{m['symbol'] or '–'} · {m['name']} · BSE {m['bse_code'] or '–'}"
            + ("  (already tracked)" if m["tracked"] else "")
        ),
    )
    a, b, c = st.columns([1, 1.5, 1.5])
    with a:
        kind = st.radio("List", ["Stocks I own", "Watchlist"], horizontal=False)
    with b:
        aliases = st.text_input(
            "Other names in the news",
            placeholder="comma-separated, e.g. KVB, Karur Vysya",
            help="The company name without 'Limited' is always matched.",
        )
    with c:
        sector = st.selectbox(
            "Sector benchmark (besides Nifty 50)",
            [""] + actions.index_names(session),
            format_func=lambda n: n or "None",
        )
    if st.button("Update" if pick["tracked"] else "Add", type="primary", icon=":material/add:"):
        company = actions.add_stock(
            session,
            pick["isin"],
            owned=kind == "Stocks I own",
            aliases=aliases,
            sector_index=sector,
        )
        load.clear()
        st.session_state["just_added"] = company.isin
        verb = "Updated" if pick["tracked"] else "Added"
        st.success(f"{verb} {company.name} in {kind}.", icon=":material/check:")

    added = st.session_state.get("just_added")
    if added == pick["isin"]:
        st.info(
            "New stocks get filings and news from the last few days on the scheduler's next "
            f"run. To load everything since {actions.HISTORY_SINCE:%d %b %Y} now (a few "
            "minutes), use the button.",
            icon=":material/history:",
        )
        if st.button("Load history now", icon=":material/download:"):
            with st.status("Loading history...", expanded=True) as status:
                try:
                    errors = actions.load_history(
                        session, added, get_settings().data_dir, progress=status.write
                    )
                except Exception as exc:  # show it here; what was stored so far is kept
                    session.rollback()
                    errors = [f"stopped: {type(exc).__name__}: {exc}"[:500]]
                for err in errors:
                    status.write(f"⚠️ {err}")
                status.update(
                    label="History loaded" + (" with errors" if errors else ""),
                    state="error" if errors else "complete",
                )
            load.clear()


def edit_stocks(session: Session) -> None:
    st.subheader("Your stocks")
    rows = actions.tracked_stocks(session)
    if not rows:
        st.caption("None yet.")
        return
    indices = [""] + actions.index_names(session)
    edited = st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        disabled=["symbol", "name"],
        column_order=["symbol", "name", "owned", "sector_index", "aliases", "remove"],
        column_config={
            "symbol": st.column_config.TextColumn("Symbol", width="small"),
            "name": st.column_config.TextColumn("Company"),
            "owned": st.column_config.CheckboxColumn("I own it", width="small"),
            "sector_index": st.column_config.SelectboxColumn("Sector benchmark", options=indices),
            "aliases": st.column_config.TextColumn("Other names in the news"),
            "remove": st.column_config.CheckboxColumn("Remove", width="small"),
        },
        key="edit-stocks",
    )
    if st.button("Save changes", icon=":material/save:"):
        updated, removed = actions.save_changes(session, edited.to_dict("records"))
        load.clear()
        st.success(f"{updated} updated, {removed} removed.", icon=":material/check:")
        st.rerun()


def system_page() -> None:
    st.title("System")
    left, right = st.columns(2)
    with left:
        st.subheader("Schedule (India time)")
        try:
            schedule = load_schedule(SCHEDULE_FILE)
            upcoming = next_runs(schedule, datetime.now(IST))
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "job": j.name,
                            "cron": j.cron,
                            "next run": upcoming[j.name].strftime("%a %d %b %H:%M")
                            if j.enabled
                            else "paused",
                        }
                        for j in schedule
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        except (OSError, ValueError) as exc:
            st.error(f"Could not read {SCHEDULE_FILE}: {exc}")
    with right:
        st.subheader("Stored data")
        counts = load("data_counts")
        st.dataframe(
            pd.DataFrame({"what": list(counts), "count": [str(v) for v in counts.values()]}),
            hide_index=True,
            width="stretch",
        )
    st.subheader("Recent runs")
    runs = load("runs", limit=200)
    if runs.empty:
        no_data("No runs yet. Start the scheduler with `make scheduler`, or run `make run-all`.")
    else:
        only_errors = st.toggle("Only errors")
        if only_errors:
            runs = runs[runs["status"] != "ok"]
        st.dataframe(
            runs,
            hide_index=True,
            width="stretch",
            column_config={
                "started": st.column_config.DatetimeColumn("Started (IST)", format="DD MMM HH:mm"),
                "seconds": st.column_config.NumberColumn("Seconds", format="%.0f"),
                "summary": st.column_config.TextColumn("Result", width="large"),
                "error": st.column_config.TextColumn("Error", width="large"),
            },
        )


stock_page = st.Page(stock_page_body, title="Stock", icon=":material/show_chart:", url_path="stock")
PAGES = {
    "today": st.Page(today_page, title="Today", icon=":material/today:", default=True),
    "stock": stock_page,
    "filings": st.Page(
        filings_page, title="Filings", icon=":material/description:", url_path="filings"
    ),
    "news": st.Page(news_page, title="News", icon=":material/newspaper:", url_path="news"),
    "moves": st.Page(
        moves_page, title="What moves the stock", icon=":material/insights:", url_path="moves"
    ),
    "manage": st.Page(
        manage_page, title="Manage stocks", icon=":material/playlist_add:", url_path="manage"
    ),
    "system": st.Page(system_page, title="System", icon=":material/settings:", url_path="system"),
}


def main() -> None:
    with st.sidebar:
        if st.button("Refresh data", icon=":material/refresh:"):
            load.clear()
        st.caption("Collecting happens in the scheduler; add stocks on Manage stocks.")
    st.navigation(list(PAGES.values())).run()


if __name__ == "__main__":  # `streamlit run` runs this file as __main__
    main()
