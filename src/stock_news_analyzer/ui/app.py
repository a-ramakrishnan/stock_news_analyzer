"""The dashboard: `sna ui` (or `make ui`) starts it at http://localhost:8501.

Every page only reads, except Manage stocks, which adds, edits and removes watchlist stocks
and can load a new stock's history, and Ask, which asks the Analyst Q&A (an LLM call) and keeps
the question. Regular collecting is done by the scheduler.
"""

import html
import logging
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from stock_news_analyzer.agents.orchestrator import SCHEDULE_FILE, load_schedule, next_runs
from stock_news_analyzer.agents.triage import TOPICS
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import get_engine
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.ui import actions, charts, guide, queries

st.set_page_config(
    page_title="Stock News Analyzer", page_icon=":material/newspaper:", layout="wide"
)

# Our own chart colours (charts.py), not Streamlit's Plotly theme; no Plotly toolbar.
PLOT = {"theme": None, "config": {"displayModeBar": False}}
RANGES = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 3 * 365}


def help_link(section: str = "the-pages") -> None:
    """A link to this page's part of the Guide."""
    st.page_link(
        PAGES["guide"],
        label="How to use this page",
        icon=":material/help:",
        query_params={"section": section},
    )


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
            if s.get("cause"):
                st.caption(f"Likely cause: {s['cause'].replace('_', ' ')}")
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
    help_link("a-daily-routine")
    st.caption(
        f"Last trading day loaded: {latest:%a %d %b %Y}"
        if latest
        else "No prices loaded yet: run `make prices`."
    )
    index_tiles(load("market"))
    red_flag_list(load("red_flags"), "Red flags, last 30 days")

    owned = [s for s in watch if s["owned"]]
    watching = [s for s in watch if not s["owned"]]
    for title, group in (("Stocks I own", owned), ("Watchlist", watching)):
        st.subheader(f"{title} ({len(group)})")
        if not group:
            st.caption("None yet. Add stocks on the Manage stocks page.")
            help_link("getting-started")
            continue
        cols = st.columns(3)
        for i, s in enumerate(group):
            with cols[i % 3]:
                stock_card(s)

    bullion_section()

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
    help_link()
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

    (
        unusual_tab,
        results_tab,
        holdings_tab,
        events_tab,
        calls_tab,
        orders_tab,
        filings_tab,
        news_tab,
        deals_tab,
        reactions_tab,
        actions_tab,
    ) = st.tabs(
        [
            "Unusual days",
            "Results",
            "Shareholding",
            "Events",
            "Earnings calls",
            "Order book",
            "Filings",
            "News",
            "Bulk/block deals",
            "How it reacted",
            "Corporate actions",
        ]
    )
    with deals_tab:
        deals = load("deals", isin=s["isin"])
        if deals.empty:
            no_data("No bulk or block deals stored for this stock.")
        else:
            shown = deals.copy()
            shown["of_volume"] = shown["of_volume"] * 100
            st.dataframe(
                shown,
                hide_index=True,
                width="stretch",
                column_config={
                    "date": st.column_config.DateColumn("Day", format="DD MMM YYYY"),
                    "quantity": st.column_config.NumberColumn("Shares", format="localized"),
                    "price": st.column_config.NumberColumn("Price", format="₹%.2f"),
                    "of_volume": st.column_config.NumberColumn(
                        "% of day's volume", format="%.1f%%"
                    ),
                    "client": st.column_config.TextColumn("Client", width="large"),
                },
            )
    with unusual_tab:
        days = load("unusual_days", isin=s["isin"])
        if days.empty:
            no_data("No unusual days yet.")
        else:
            missing = int(days["cause"].isna().sum())
            shown = days.copy()
            for col in ("stock", "vs_nifty"):
                shown[col] = shown[col] * 100
            st.dataframe(
                shown,
                hide_index=True,
                width="stretch",
                column_config={
                    "date": st.column_config.DateColumn("Day", format="DD MMM YYYY"),
                    "stock": st.column_config.NumberColumn("Stock", format="%+.2f%%"),
                    "vs_nifty": st.column_config.NumberColumn("vs Nifty 50", format="%+.2f%%"),
                    "zscore": st.column_config.NumberColumn("z", format="%+.1f"),
                    "cause": st.column_config.TextColumn("Likely cause"),
                    "confidence": st.column_config.TextColumn("Confidence"),
                    "explanation": st.column_config.TextColumn("Explanation", width="large"),
                    "evidence": st.column_config.TextColumn("Based on", width="medium"),
                },
            )
            if missing:
                st.caption(
                    f"{missing} days not explained yet: the scheduler explains recent days each "
                    "morning; `sna explain run --symbol "
                    f"{s['symbol']}` explains the rest."
                )
    with results_tab:
        results(s)
    with holdings_tab:
        shareholding(s)
    with events_tab:
        events_tab_body(s)
    with calls_tab:
        earnings_calls(s)
    with orders_tab:
        order_book(s)
    with filings_tab:
        filings_table(load("filings", isin=s["isin"], dedupe=True, limit=200), key="stock")
    with news_tab:
        news_table(load("news", isin=s["isin"], limit=200, hide_noise=True))
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


def shareholding(s: dict) -> None:
    """Who owns the company, quarter by quarter, from its shareholding patterns."""
    df = load("shareholding", isin=s["isin"])
    if df.empty:
        no_data(
            "No shareholding patterns yet. The scheduler reads new ones each morning; "
            f"`sna holdings run --symbol {s['symbol']}` reads three years now."
        )
        return
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    cols = st.columns(4)
    for col, (key, label) in zip(
        cols,
        [
            ("promoter", "Promoters"),
            ("fii", "Foreign inst."),
            ("dii", "Domestic inst."),
            ("retail", "Retail"),
        ],
        strict=True,
    ):
        delta = (
            f"{latest[key] - prev[key]:+.2f} pts"
            if prev is not None and pd.notna(latest[key]) and pd.notna(prev[key])
            else None
        )
        col.metric(f"{label}, {latest['quarter']:%b %Y}", _fmt(latest[key], "{:.2f}%"), delta)
    st.line_chart(
        df.set_index("quarter")[["promoter", "fii", "dii", "retail"]].rename(
            columns={
                "promoter": "Promoters",
                "fii": "Foreign institutions",
                "dii": "Domestic institutions",
                "retail": "Retail",
            }
        ),
        y_label="% of shares",
        height=260,
    )
    st.dataframe(
        df.iloc[::-1],
        hide_index=True,
        width="stretch",
        column_config={
            "quarter": st.column_config.DateColumn("Quarter end", format="MMM YYYY"),
            "promoter": st.column_config.NumberColumn("Promoters", format="%.2f%%"),
            "fii": st.column_config.NumberColumn("Foreign inst.", format="%.2f%%"),
            "dii": st.column_config.NumberColumn("Domestic inst.", format="%.2f%%"),
            "mf": st.column_config.NumberColumn("Mutual funds", format="%.2f%%"),
            "insurance": st.column_config.NumberColumn("Insurers", format="%.2f%%"),
            "retail": st.column_config.NumberColumn("Retail", format="%.2f%%"),
            "pledged": st.column_config.NumberColumn(
                "Pledged", format="%.2f%%", help="Percent of the promoters' own shares."
            ),
            "shareholders": st.column_config.NumberColumn("Shareholders", format="localized"),
        },
    )
    st.caption(
        "Percent of all shares, from the quarterly shareholding pattern. Domestic institutions "
        "include mutual funds and insurers; retail is individuals holding up to Rs 2 lakh."
    )


TONE = {"positive": "🟢", "neutral": "⚪", "cautious": "🟠", "negative": "🔴"}
CATEGORY = {
    "guidance": "Guidance",
    "demand": "Demand",
    "margins": "Margins",
    "capex": "Capex",
    "order_book": "Order book",
    "risk": "Risks",
    "initiative": "New initiatives",
    "other": "Other",
}


def earnings_calls(s: dict) -> None:
    """The Concall Analyst's reading of each call, and the promise ledger."""
    calls = load("concalls", isin=s["isin"])
    if not calls:
        how = (
            "The scheduler reads new transcripts each morning; "
            f"`sna concalls run --symbol {s['symbol']} --since 2023-10-01` reads older ones."
        )
        no_data(f"No earnings calls analysed yet. {how}")
    else:
        pick = st.selectbox(
            "Call",
            calls,
            format_func=lambda c: f"{c['quarter']} · filed {c['filed']:%d %b %Y} · {c['tone']}",
            key="concall",
        )
        st.markdown(f"#### {TONE.get(pick['tone'], '')} {pick['quarter']}: {pick['tone']} tone")
        st.write(pick["summary"])
        left, right = st.columns(2)
        with left:
            st.markdown("**To watch**")
            st.markdown("\n".join(f"- {p}" for p in pick["action_points"]) or "–")
        with right:
            st.markdown("**Since the previous call**")
            st.markdown(
                "\n".join(
                    f"- *{c['kind'].replace('_', ' ')}*: {c['text']}" for c in pick["changes"]
                )
                or "First call stored, nothing to compare with."
            )
        if pick["points"]:
            points = pd.DataFrame(pick["points"])
            points["category"] = points["category"].map(CATEGORY).fillna(points["category"])
            st.markdown("**What management said**")
            st.dataframe(
                points,
                hide_index=True,
                width="stretch",
                column_config={
                    "category": st.column_config.TextColumn("Topic"),
                    "point": st.column_config.TextColumn("Point", width="large"),
                    "sentiment": st.column_config.TextColumn("For shareholders"),
                    "quote": st.column_config.TextColumn("In their words", width="medium"),
                },
            )
        if pick["concerns"]:
            st.markdown("**What analysts pressed on**")
            st.dataframe(
                pd.DataFrame(pick["concerns"]),
                hide_index=True,
                width="stretch",
                column_order=["topic", "question", "answer"],
                column_config={
                    "topic": st.column_config.TextColumn("Topic"),
                    "question": st.column_config.TextColumn("Question", width="large"),
                    "answer": st.column_config.TextColumn("Answer"),
                },
            )
        if pick["note"]:
            st.caption(pick["note"])
        with st.expander("Transcript text"):
            st.text(load("concall_text", doc_id=pick["document_id"])[:20000])

    ledger = load("promises", isin=s["isin"])
    st.markdown("**Promise ledger**")
    score = next((c for c in load("credibility") if c["isin"] == s["isin"]), None)
    if score:
        left, right = st.columns([1, 3], vertical_alignment="center")
        left.metric(
            "Promises kept",
            f"{score['score']:.0%}" if score["score"] is not None else "–",
            help="Kept 1, kept late or partly kept 0.5, missed, dropped or long overdue 0, "
            "over the promises settled so far. Shown from 3 settled promises.",
        )
        right.caption(
            f"Of {score['scored']} settled: {score['kept']} kept, {score['kept_late']} kept "
            f"late, {score['partly']} partly, {score['missed']} missed, {score['dropped']} "
            f"dropped, {score['overdue']} long overdue. {score['to_come']} still to come."
        )
    if ledger.empty:
        st.caption("No promises recorded yet.")
    else:
        overdue = int(ledger["overdue"].sum())
        st.dataframe(
            ledger.drop(columns=["symbol"]),
            hide_index=True,
            width="stretch",
            column_config={
                "promise": st.column_config.TextColumn("Promise", width="large"),
                "target": st.column_config.TextColumn("Target"),
                "due": st.column_config.TextColumn("Due (as said)"),
                "status": st.column_config.TextColumn("Status"),
                "due_date": st.column_config.DateColumn("Due by", format="DD MMM YYYY"),
                "overdue": st.column_config.CheckboxColumn("Overdue"),
                "note": st.column_config.TextColumn("Latest update", width="medium"),
                "said_in": st.column_config.TextColumn("Said in"),
                "quote": st.column_config.TextColumn("In their words", width="medium"),
            },
        )
        st.caption(
            "Each later call updates a promise when management mentions it again; once its "
            "date has passed, the Promise Ledger checks it against later results and filings"
            + (f". {overdue} past their date and still open." if overdue else ".")
        )
        checks = load("promise_checks", isin=s["isin"])
        if not checks.empty:
            with st.expander(f"How promises were checked ({len(checks)})"):
                st.dataframe(
                    checks,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "checked": st.column_config.DatetimeColumn("Checked", format="DD MMM YYYY"),
                        "promise": st.column_config.TextColumn("Promise", width="medium"),
                        "note": st.column_config.TextColumn("Finding", width="large"),
                        "based_on": st.column_config.TextColumn("Based on", width="medium"),
                    },
                )
    gaps = load("concall_gaps", isin=s["isin"])
    if not gaps.empty:
        with st.expander(f"Transcripts not read ({len(gaps)})"):
            st.dataframe(gaps, hide_index=True, width="stretch")


def _fmt(x, fmt: str) -> str:
    return "–" if x is None or pd.isna(x) else fmt.format(x)


def results(s: dict) -> None:
    """Revenue, EBITDA and profit by quarter (half year for SME companies), from results."""
    periods = load("results", isin=s["isin"])
    if periods.empty:
        no_data(
            "No results read for this stock yet. The scheduler reads new results each morning; "
            f"`sna results run --symbol {s['symbol']}` reads the last two years now."
        )
        return
    latest = periods.iloc[-1]
    m1, m2, m3 = st.columns(3)
    m1.metric(
        f"Revenue, {latest['period']}",
        _fmt(latest["revenue_cr"], "Rs {:,.0f} cr"),
        delta=_fmt(latest["revenue_yoy"], "{:+.0%} y/y")
        if pd.notna(latest["revenue_yoy"])
        else None,
    )
    m2.metric(
        "Profit after tax",
        _fmt(latest["pat_cr"], "Rs {:,.0f} cr"),
        delta=_fmt(latest["pat_yoy"], "{:+.0%} y/y") if pd.notna(latest["pat_yoy"]) else None,
    )
    m3.metric(
        "EBITDA margin",
        _fmt(latest["ebitda_margin"], "{:.1%}"),
        help="Profit before tax + finance costs + depreciation − other income, ÷ revenue.",
    )
    st.plotly_chart(charts.revenue_chart(periods, dark()), width="stretch", **PLOT)
    st.dataframe(
        periods.iloc[::-1],
        hide_index=True,
        width="stretch",
        column_config={
            "period": st.column_config.TextColumn("Period"),
            "revenue_cr": st.column_config.NumberColumn("Revenue", format="localized"),
            "revenue_yoy": st.column_config.NumberColumn("Revenue y/y", format="percent"),
            "ebitda_cr": st.column_config.NumberColumn("EBITDA", format="localized"),
            "ebitda_margin": st.column_config.NumberColumn("EBITDA margin", format="percent"),
            "pat_cr": st.column_config.NumberColumn("Profit after tax", format="localized"),
            "pat_yoy": st.column_config.NumberColumn("Profit y/y", format="percent"),
            "pat_margin": st.column_config.NumberColumn("Net margin", format="percent"),
            "eps": st.column_config.NumberColumn("EPS (Rs)", format="%.2f"),
            "basis": st.column_config.TextColumn("Basis"),
            "checked": st.column_config.CheckboxColumn(
                "Checked", help="Every figure was found as written in the filing."
            ),
        },
    )
    st.caption(
        "Rs crore, from the results filed with the exchanges (consolidated where given). y/y: "
        "on the same period a year earlier."
    )


def bullion_section() -> None:
    """Each watched metal's last 30 days: the rupee move split into global price, rupee and
    the rest, with notes on unusual days."""
    metals = load("bullion_metals")
    if not metals:
        return
    st.subheader("Bullion")
    for metal, tab in zip(metals, st.tabs([m.title() for m in metals]), strict=True):
        with tab:
            rows = load("bullion", metal=metal, days=30)
            if rows.empty:
                no_data("No moves yet: run `sna bullion run`.")
                continue
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "date": st.column_config.DateColumn("Day", format="DD MMM YYYY"),
                    "close": st.column_config.NumberColumn("ETF close", format="₹%.2f"),
                    "rupees": st.column_config.NumberColumn("In rupees", format="percent"),
                    "global": st.column_config.NumberColumn("Global price", format="percent"),
                    "rupee": st.column_config.NumberColumn("USD/INR", format="percent"),
                    "other": st.column_config.NumberColumn("Other", format="percent"),
                    "z": st.column_config.NumberColumn("z", format="%+.1f"),
                    "driver": st.column_config.TextColumn("Driver"),
                    "note": st.column_config.TextColumn("Note", width="large"),
                },
            )
    st.caption(
        "The Indian price is the close of an NSE ETF holding the metal (GOLDBEES, SILVERBEES). "
        "Other: duty, the local premium, and the gap between the Indian and New York closes. "
        "Notes are written for unusual days (2σ)."
    )


def red_flag_list(flags: list[dict], title: str) -> None:
    """High flags in red, medium in amber; nothing when there are none."""
    if not flags:
        return
    st.subheader(title)
    for f in flags:
        line = f"**{f['date']:%d %b}** · {f['kind']} · {f['title']}"
        if f["detail"]:
            line += f" ({f['detail']})"
        (st.error if f["severity"] == "high" else st.warning)(line)
    st.page_link(
        PAGES["flags"],
        label="All red flags, and dismiss the ones dealt with",
        icon=":material/flag:",
    )


def events_tab_body(s: dict) -> None:
    """Events from filings (capex, ratings, management changes...), each checked by the QA
    Checker, with the red flags they raised."""
    red_flag_list(load("red_flags", isin=s["isin"], days=365), "Red flags, last 12 months")
    rows = load("events", isin=s["isin"])
    if rows.empty:
        no_data(
            "No events recorded for this stock yet. The scheduler reads new filings each "
            f"morning; `sna events run --symbol {s['symbol']}` reads the last 400 days now."
        )
        return
    st.dataframe(
        rows.drop(columns=["id"]),
        hide_index=True,
        width="stretch",
        column_config={
            "filed": st.column_config.DateColumn("Filed", format="DD MMM YYYY"),
            "type": st.column_config.TextColumn("Type"),
            "importance": st.column_config.ProgressColumn(
                "Importance", min_value=1, max_value=5, format="%d"
            ),
            "sentiment": st.column_config.TextColumn("Sentiment"),
            "headline": st.column_config.TextColumn("Event", width="large"),
            "amount": st.column_config.TextColumn(
                "Amount",
                help="Share of revenue: the amount ÷ the 12 months' revenue. A rating's amount "
                "is the debt rated.",
            ),
            "qa": st.column_config.TextColumn("QA"),
            "qa_notes": st.column_config.TextColumn("QA notes", width="medium"),
            "quote": st.column_config.TextColumn("From the filing", width="large"),
            "link": st.column_config.LinkColumn("Filing", display_text="open"),
        },
    )
    st.caption(
        "Read from the company's filings (Haiku), every quote and amount checked against the "
        "filing; important or doubtful events checked again by Sonnet. Unchecked: a check "
        "failed and nothing settled it; `sna events review` lists them for your decision."
    )


def order_book(s: dict) -> None:
    """Orders announced, the quarterly order book, book-to-bill and peers."""
    data = load("order_book", isin=s["isin"])
    quarters, summary, orders = data["quarters"], data["summary"], data["orders"]
    if quarters.empty:
        no_data(
            "No orders read for this stock yet. The scheduler reads order-win filings each "
            f"morning; `sna orders run --symbol {s['symbol']}` reads them now."
        )
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Order book",
        _fmt(summary["order_book_cr"], "Rs {:,.0f} cr"),
        help=f"As reported for {summary['order_book_quarter'] or '–'}.",
    )
    m2.metric(
        "Years of revenue",
        _fmt(summary["years_of_revenue"], "{:.1f}"),
        help="Latest order book ÷ revenue of the last four quarters.",
    )
    m3.metric(
        "Book-to-bill",
        _fmt(summary["book_to_bill"], "{:.2f}x"),
        help="Orders won ÷ revenue, last four quarters. Above 1: the order book is growing.",
    )
    m4.metric(
        "Execution",
        _fmt(summary["execution"], "{:.0%}"),
        help="Revenue of the last four quarters ÷ the order book a year earlier.",
    )
    st.plotly_chart(charts.order_inflow_chart(quarters, dark()), width="stretch", **PLOT)
    if summary["revenue_from"] and summary["revenue_from"].startswith("results"):
        st.caption(
            f"Revenue: the 12 months to {summary['order_book_quarter']}, from the results "
            f"filings ({summary['revenue_from'].removeprefix('results, ')}). Orders won: "
            + (
                "the inflow the company reported."
                if summary["inflow_from"] == "reported"
                else "the orders it announced, as it did not report its inflow each quarter."
            )
        )
    st.caption(
        "Announced: orders the company filed with the exchanges, valued in Rs crore (the "
        "midpoint where only a range was given). Reported inflow: what results or the call "
        "said was won in the quarter. "
        + (
            f"Government and PSU clients gave {summary['government_share']:.0%} of the value "
            "announced in the last year"
            if summary["government_share"] is not None
            else ""
        )
        + (
            f"; the largest client, {summary['top_client']}, {summary['top_client_share']:.0%}."
            if summary["top_client"]
            else ""
        )
    )
    shown = quarters.drop(columns=["period_end"]).iloc[::-1]
    st.dataframe(
        shown,
        hide_index=True,
        width="stretch",
        column_config={
            "quarter": st.column_config.TextColumn("Quarter"),
            "announced_cr": st.column_config.NumberColumn("Announced", format="localized"),
            "announced": st.column_config.NumberColumn("Orders"),
            "unvalued": st.column_config.NumberColumn("No value"),
            "inflow_cr": st.column_config.NumberColumn("Reported inflow", format="localized"),
            "order_book_cr": st.column_config.NumberColumn("Order book", format="localized"),
            "revenue_cr": st.column_config.NumberColumn("Revenue", format="localized"),
            "revenue_from": st.column_config.TextColumn(
                "Revenue from", help="The order-book document, or the results filing."
            ),
            "book_to_bill": st.column_config.NumberColumn("Book-to-bill", format="%.2f"),
            "announced_share": st.column_config.NumberColumn(
                "Announced ÷ reported", format="percent"
            ),
            "unexplained_cr": st.column_config.NumberColumn(
                "Unexplained change",
                format="localized",
                help="Closing book − (opening book + inflow − revenue). Negative: cancellations "
                "or revenue from outside the order book; positive: orders not counted.",
            ),
        },
    )
    with st.expander(f"Orders announced ({len(orders)})"):
        st.dataframe(
            orders,
            hide_index=True,
            width="stretch",
            column_config={
                "announced": st.column_config.DatetimeColumn("Date", format="DD MMM YYYY"),
                "value_cr": st.column_config.NumberColumn("Rs crore", format="localized"),
                "range": st.column_config.TextColumn("Range given"),
                "client_type": st.column_config.TextColumn("Client type"),
                "months": st.column_config.NumberColumn("Months"),
                "description": st.column_config.TextColumn("What for", width="large"),
            },
        )
    peers = load("order_peers")
    if len(peers) > 1:
        st.markdown("**Compared with your other order-driven stocks**")
        st.dataframe(
            peers,
            hide_index=True,
            width="stretch",
            column_config={
                "symbol": st.column_config.TextColumn("Stock"),
                "book_to_bill": st.column_config.NumberColumn("Book-to-bill", format="%.2f"),
                "years_of_revenue": st.column_config.NumberColumn("Years", format="%.1f"),
                "execution": st.column_config.NumberColumn("Execution", format="percent"),
                "announced_growth": st.column_config.NumberColumn("Order growth", format="percent"),
                "order_book_cr": st.column_config.NumberColumn("Order book", format="localized"),
                "government_share": st.column_config.NumberColumn("Govt", format="percent"),
                "top_client_share": st.column_config.NumberColumn("Top client", format="percent"),
                "orders_last_year": st.column_config.NumberColumn("Orders (1y)"),
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
            "importance": st.column_config.NumberColumn(
                "★", help="Importance from the triage, 1 (noise) to 5 (could move the stock)"
            ),
            "topic": st.column_config.TextColumn("Topic"),
            "sentiment": st.column_config.TextColumn("For shareholders"),
            "title": st.column_config.TextColumn("Headline", width="large"),
            "summary": st.column_config.TextColumn("Summary", width="large"),
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
    st.caption(
        "Every filing your stocks made with NSE and BSE. Search by stock, type, words or date, "
        "and select a row to read the filing's text."
    )
    help_link()
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
    st.caption(
        "Articles about your stocks from news feeds and Google News, with the AI's relevance "
        "and importance where it has read them."
    )
    help_link()
    a, b, c = st.columns([1.2, 2, 1], vertical_alignment="bottom")
    with a:
        s = stock_picker("news-stock")
    with b:
        search = st.text_input("Search headlines")
    with c:
        since = st.date_input(
            "Since", date.today() - timedelta(days=30), format="DD/MM/YYYY", key="news-since"
        )
    d, e, f = st.columns([1, 1, 2], vertical_alignment="bottom")
    with d:
        hide = st.toggle(
            "Hide off-topic and repeats",
            value=True,
            help="Uses the triage; articles not triaged yet are still shown.",
        )
    with e:
        min_importance = st.select_slider("Importance at least", [1, 2, 3, 4, 5], value=1)
    with f:
        topics = st.multiselect("Topic", list(TOPICS))
    df = load(
        "news",
        isin=s["isin"] if s else None,
        search=search or None,
        since=since,
        hide_noise=hide,
        min_importance=min_importance,
        topics=topics or None,
    )
    untriaged = int(df["importance"].isna().sum()) if not df.empty else 0
    st.caption(
        f"{len(df)} articles"
        + (f", {untriaged} not triaged yet (`sna triage run`)" if untriaged else "")
    )
    news_table(df)


def themes_page() -> None:
    st.title("Themes")
    help_link()
    st.caption(
        "Events, orders and earnings-call points of your stocks, tagged with themes (Haiku). "
        "Items: the last 90 days; before: the 90 days before that."
    )
    themes = load("themes")
    if themes.empty:
        no_data("No themes yet: run `sna themes run`.")
        return
    st.dataframe(
        themes.drop(columns=["key"]),
        hide_index=True,
        width="stretch",
        column_config={
            "theme": st.column_config.TextColumn("Theme"),
            "items": st.column_config.NumberColumn("Items, 90 days"),
            "before": st.column_config.NumberColumn("90 days before"),
            "positive": st.column_config.NumberColumn("Positive"),
            "negative": st.column_config.NumberColumn("Negative"),
            "orders_cr": st.column_config.NumberColumn("Orders, Rs crore", format="localized"),
            "companies": st.column_config.TextColumn("Companies", width="large"),
        },
    )
    names = dict(zip(themes["theme"], themes["key"], strict=True))
    choice = st.selectbox("Theme", list(names))
    months, items = load("theme_detail", theme=names[choice])
    if not months.empty:
        st.bar_chart(months, x="month", y="items", height=220)
    st.dataframe(
        items,
        hide_index=True,
        width="stretch",
        column_config={
            "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
            "item": st.column_config.TextColumn("Item", width="large"),
            "value_cr": st.column_config.NumberColumn("Rs crore", format="localized"),
        },
    )
    st.subheader("Read-across")
    signals = load("read_across")
    if signals.empty:
        st.caption("None in the last 90 days.")
    else:
        st.dataframe(
            signals,
            hide_index=True,
            width="stretch",
            column_config={
                "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                "item": st.column_config.TextColumn("Item", width="large"),
            },
        )
    st.caption(
        "An important order or event (importance 4-5, or an order of 1% or more of a year's "
        "revenue) is listed for the watchlist stocks that are its approved peers or share its "
        "theme."
    )


def ask_page() -> None:
    from stock_news_analyzer.agents import ask as qa
    from stock_news_analyzer.llm import LLM, LLMError

    st.title("Ask")
    help_link("how-ai-is-used")
    st.caption(
        "Ask about your companies in plain English. The Analyst Q&A looks things up in the "
        "database (read-only) and answers with sources; each question costs a few cents."
    )
    with st.form("ask"):
        question = st.text_area(
            "Question", placeholder="Which of my companies raised guidance this year?"
        )
        save = st.text_input("Save as report (optional name)", max_chars=64)
        asked = st.form_submit_button("Ask", icon=":material/search:")
    with Session(engine()) as session:
        if asked and question.strip():
            steps = st.status("Looking things up...", expanded=True)
            try:
                answer = qa.ask(
                    session,
                    LLM(session),
                    question.strip(),
                    name=save.strip() or None,
                    progress=steps.write,
                )
            except LLMError as exc:
                steps.update(label="Failed", state="error")
                st.error(str(exc))
            else:
                steps.update(
                    label=f"{answer.steps} lookups, ${answer.cost_usd:.4f}",
                    state="complete",
                    expanded=False,
                )
                st.markdown(answer.text)
                for ref in answer.sources:
                    st.caption(qa.describe_source(session, ref))
        st.subheader("Earlier questions")
        rows = qa.history(session)
        if not rows:
            st.caption("None yet.")
        for r in rows:
            label = (
                f"{r.asked_at.astimezone(IST):%d %b %H:%M} "
                + (f"[{r.name}] " if r.name else "")
                + r.question[:100]
            )
            with st.expander(label):
                st.markdown(r.answer)
                for ref in r.sources:
                    try:
                        st.caption(qa.describe_source(session, ref))
                    except AttributeError:  # the source was deleted since
                        st.caption(f"[{ref}] (no longer stored)")
                st.caption(f"{r.steps} lookups with {r.model}, ${r.cost_usd:.4f}")


def moves_page() -> None:
    st.title("What moves the stock")
    help_link()
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
    help_link("getting-started")
    st.caption(
        "Changes here take effect straight away: the scheduler picks up new stocks on its next "
        "run. `make watchlist` re-applies config/watchlist.yaml, so a stock listed there comes "
        "back as written in the file."
    )
    with Session(engine()) as session:
        add_stock_form(session)
        st.divider()
        edit_stocks(session)


def add_stock_form(session: Session, offer_history: bool = True) -> None:
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
    if offer_history and added == pick["isin"]:
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
        column_order=["symbol", "name", "owned", "sector_index", "aliases", "peers", "remove"],
        column_config={
            "symbol": st.column_config.TextColumn("Symbol", width="small"),
            "name": st.column_config.TextColumn("Company"),
            "owned": st.column_config.CheckboxColumn("I own it", width="small"),
            "sector_index": st.column_config.SelectboxColumn("Sector benchmark", options=indices),
            "aliases": st.column_config.TextColumn("Other names in the news"),
            "peers": st.column_config.TextColumn(
                "Peers",
                help="NSE symbols to compare with, comma-separated. Empty: the largest "
                "companies in the same NSE industry, when known.",
            ),
            "remove": st.column_config.CheckboxColumn("Remove", width="small"),
        },
        key="edit-stocks",
    )
    if st.button("Save changes", icon=":material/save:"):
        updated, removed, unknown = actions.save_changes(session, edited.to_dict("records"))
        load.clear()
        st.success(f"{updated} updated, {removed} removed.", icon=":material/check:")
        if unknown:
            st.warning(f"Not NSE symbols, left out of peers: {', '.join(unknown)}")
        st.rerun()


SEVERITY = {"high": "🔴 high", "medium": "🟠 medium", "low": "⚪ low"}


def flags_page() -> None:
    from stock_news_analyzer.agents import redflags

    st.title("Red flags")
    st.caption(
        "Warnings about governance and money: an auditor or CFO leaving, a rating cut, a "
        "pledge, promoters selling, a penalty, results filed late. Dismiss one once you have "
        "looked into it; it stays on record with your note."
    )
    help_link("words-used")
    c1, c2, c3 = st.columns([2, 1, 1])
    severities = c1.multiselect(
        "Severity", list(SEVERITY), default=["high", "medium"], format_func=SEVERITY.get
    )
    days = c2.selectbox(
        "Raised in the last",
        [30, 90, 365, 3 * 365],
        index=2,
        format_func=lambda d: f"{d} days" if d < 365 else f"{d // 365} year{'s' * (d > 365)}",
    )
    dismissed = c3.toggle("Show dismissed")
    flags = load("flag_table", days=days, severities=tuple(severities), include_dismissed=dismissed)
    symbols = sorted(flags["symbol"].unique())
    pick = st.multiselect("Stocks", symbols, placeholder="All stocks")
    if pick:
        flags = flags[flags["symbol"].isin(pick)]
    if flags.empty:
        no_data("No red flags for these choices.")
        return
    shown = flags.assign(severity=flags["severity"].map(SEVERITY))
    selection = st.dataframe(
        shown.drop(columns=["id"]),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "date": st.column_config.DateColumn("Raised", format="DD MMM YYYY"),
            "severity": st.column_config.TextColumn("Severity"),
            "symbol": st.column_config.TextColumn("Stock"),
            "kind": st.column_config.TextColumn("Kind"),
            "title": st.column_config.TextColumn("What happened", width="large"),
            "status": st.column_config.TextColumn("Status"),
            "note": st.column_config.TextColumn("Your note"),
            "link": st.column_config.LinkColumn("Filing", display_text="open"),
        },
        key="flags",
    )
    rows = selection.selection.rows
    if not rows:
        st.caption("Select a flag to dismiss it, or to open a dismissed one again.")
        return
    flag = flags.iloc[rows[0]]
    st.markdown(f"**{flag['symbol']}:** {flag['title']}")
    with Session(engine()) as session:
        if flag["status"] == "open":
            with st.form("dismiss", clear_on_submit=True):
                note = st.text_input(
                    "Note (optional)", placeholder="e.g. a planned retirement; successor named"
                )
                if st.form_submit_button("Dismiss", icon=":material/done:"):
                    redflags.dismiss(session, int(flag["id"]), note.strip() or None)
                    load.clear()
                    st.rerun()
        elif st.button("Open it again", icon=":material/undo:"):
            redflags.restore(session, int(flag["id"]))
            load.clear()
            st.rerun()


class _StatusLog:
    """Shows the log lines of a job run by hand inside its status box, as they happen."""

    def __init__(self, box):
        self.box = box
        self.handler = logging.Handler(logging.INFO)
        self.handler.emit = lambda record: box.write(f"`{record.getMessage()[:300]}`")
        self.logger = logging.getLogger("stock_news_analyzer")

    def __enter__(self):
        self.level = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.level)


def run_now_section() -> None:
    """Run any job now, with its log lines shown as it goes."""
    from stock_news_analyzer.agents import orchestrator as orch

    st.subheader("Run a job now")
    notes = orch.job_notes(SCHEDULE_FILE)
    names = [n for n in orch.RUN_ALL if n in orch.JOBS] + sorted(set(orch.JOBS) - set(orch.RUN_ALL))
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    name = c1.selectbox(
        "Job", names, format_func=lambda n: f"{n}: {notes.get(n, '')}", key="run_job"
    )
    with Session(engine()) as session:
        busy = orch.running(session, name)
    if busy:
        st.info(
            f"{name} is already running (started {busy.started_at.astimezone(IST):%H:%M}); "
            "wait for it to finish.",
            icon=":material/hourglass_top:",
        )
    if c2.button("Run now", icon=":material/play_arrow:", disabled=bool(busy)):
        with st.status(f"Running {name}...", expanded=True) as box:
            st.caption("This can take several minutes; keep this tab open until it finishes.")
            with _StatusLog(box):
                run = orch.run_job(name)
            if run.status == "ok":
                box.update(label=f"{name}: {run.summary}", state="complete", expanded=False)
            else:
                box.update(label=f"{name} failed", state="error", expanded=True)
                st.error(run.error or run.summary or "failed")
        load.clear()
    st.caption(
        "The same jobs the scheduler runs each day; running one by hand is safe, and also "
        "works for a job turned off on Settings."
    )


def system_page() -> None:
    st.title("System")
    st.caption(
        "Whether the scheduled jobs ran, what is stored, and this month's AI spend. "
        "The schedule is in config/schedule.yaml."
    )
    help_link("keeping-it-running")
    run_now_section()
    left, right = st.columns(2)
    with left:
        st.subheader("Schedule (India time)")
        try:
            from stock_news_analyzer.settings_store import paused_jobs

            schedule = load_schedule(SCHEDULE_FILE)
            upcoming = next_runs(schedule, datetime.now(IST))
            off = paused_jobs(get_settings())
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "job": j.name,
                            "next run": "off on Settings"
                            if j.name in off
                            else upcoming[j.name].strftime("%a %d %b %H:%M")
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
    st.subheader("AI usage")
    usage = load("llm_usage")
    a, b, c = st.columns(3)
    a.metric(f"Spent in {usage['month']}", f"${usage['spent']:.2f}")
    b.metric(
        "Monthly budget",
        f"${usage['budget']:.2f}",
        help="Set on Settings; calls stop for the month when reached.",
    )
    c.metric("Articles waiting for triage", usage["pending_triage"])
    st.progress(min(1.0, usage["spent"] / usage["budget"]) if usage["budget"] else 1.0)
    if usage["by_task"].empty:
        st.caption("No LLM calls this month yet.")
    else:
        st.dataframe(
            usage["by_task"],
            hide_index=True,
            width="stretch",
            column_config={"cost $": st.column_config.NumberColumn(format="$%.4f")},
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


MODEL_NAMES = {
    "claude-haiku-5-5": "Haiku 5.5 (cheapest)",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-opus-5-5": "Opus 5.5 (strongest, about 2x Sonnet)",
}


SETTING_NAMES = {
    "anthropic_api_key": "API key",
    "llm_monthly_budget_usd": "Monthly budget",
    "llm_model_triage": "Model for sorting and extracting",
    "llm_model_analysis": "Model for explaining and analysing",
    "unusual_threshold": "Unusual-day threshold",
    "paused_jobs": "Jobs turned off",
}


def settings_page() -> None:
    from stock_news_analyzer import settings_store as store
    from stock_news_analyzer.agents.orchestrator import job_notes
    from stock_news_analyzer.llm import PRICES, check_key

    st.title("Settings")
    st.caption(
        "The AI key and budget, the unusual-day threshold, and which scheduled jobs run. "
        "Saved here, a setting takes the place of the same one in .env; the scheduler picks "
        "changes up within a minute."
    )
    help_link("settings")
    cfg = get_settings()
    with Session(engine()) as session:
        st.subheader("AI features")
        key_from = store.source(session, "anthropic_api_key")
        if cfg.anthropic_api_key:
            st.success(
                f"An API key is set (from {key_from}), ending in ...{cfg.anthropic_api_key[-4:]}.",
                icon=":material/key:",
            )
        else:
            st.warning(
                "No API key: the AI features are off. Collecting, prices, shareholding and the "
                "dashboard still work.",
                icon=":material/key_off:",
            )
        with st.form("key", clear_on_submit=True):
            new_key = st.text_input(
                "Anthropic API key",
                type="password",
                placeholder="sk-ant-...",
                help="From console.anthropic.com. It is checked with Anthropic before saving, "
                "and kept in this computer's database.",
            )
            if st.form_submit_button("Check and save the key", icon=":material/check:"):
                problem = check_key(new_key.strip()) if new_key.strip() else "enter a key first"
                if problem:
                    st.error(problem)
                else:
                    store.save(session, "anthropic_api_key", new_key.strip())
                    st.rerun()
        c1, c2 = st.columns(2)
        if cfg.anthropic_api_key and c1.button("Check the current key"):
            problem = check_key(cfg.anthropic_api_key)
            (st.error if problem else st.success)(problem or "Anthropic accepts the key.")
        if key_from == "Settings page" and c2.button("Remove the saved key"):
            store.remove(session, "anthropic_api_key")
            st.rerun()

        usage = queries.llm_usage(session)
        spent, budget = usage["spent"], cfg.llm_monthly_budget_usd
        st.progress(
            min(spent / budget, 1.0) if budget else 1.0,
            # "\\$": two plain $ signs would be read as a formula.
            text=f"{usage['month']}: \\${spent:.2f} spent of the \\${budget:.2f} budget",
        )
        models = list(PRICES)
        with st.form("ai"):
            new_budget = st.number_input(
                "Monthly budget, US$",
                min_value=0.0,
                step=1.0,
                value=float(budget),
                help="AI calls stop for the rest of the month when this much has been spent. "
                "0 turns the AI features off.",
            )
            triage = st.selectbox(
                "Model for sorting and extracting (news triage, events, orders, results, themes)",
                models,
                index=models.index(cfg.llm_model_triage) if cfg.llm_model_triage in models else 0,
                format_func=lambda m: MODEL_NAMES.get(m, m),
            )
            analysis = st.selectbox(
                "Model for explaining and analysing (unusual days, earnings calls, promises, Ask)",
                models,
                index=models.index(cfg.llm_model_analysis)
                if cfg.llm_model_analysis in models
                else 1,
                format_func=lambda m: MODEL_NAMES.get(m, m),
            )
            if st.form_submit_button("Save", icon=":material/save:"):
                store.save(session, "llm_monthly_budget_usd", new_budget)
                store.save(session, "llm_model_triage", triage)
                store.save(session, "llm_model_analysis", analysis)
                st.rerun()

        st.subheader("Unusual days")
        with st.form("unusual"):
            threshold = st.slider(
                "Mark a day unusual when the stock's move against the Nifty 50 is at least this "
                "many standard deviations of its last 60 days",
                min_value=1.5,
                max_value=3.0,
                step=0.1,
                value=float(cfg.unusual_threshold),
                help="2.0 marks about 1 trading day in 20; 2.5 about 1 in 80. Applies to days "
                "worked out from now on.",
            )
            if st.form_submit_button("Save", icon=":material/save:"):
                store.save(session, "unusual_threshold", threshold)
                st.rerun()

        st.subheader("Scheduled jobs")
        schedule = load_schedule(SCHEDULE_FILE)
        notes = job_notes(SCHEDULE_FILE)
        paused = store.paused_jobs(cfg)
        upcoming = next_runs(schedule, datetime.now(IST))
        jobs = pd.DataFrame(
            [
                {
                    "on": j.enabled and j.name not in paused,
                    "job": j.name,
                    "what": notes.get(j.name, ""),
                    "next": upcoming[j.name].strftime("%a %d %b %H:%M")
                    if j.name in upcoming
                    else "off in schedule.yaml",
                }
                for j in schedule
            ]
        )
        edited = st.data_editor(
            jobs,
            hide_index=True,
            width="stretch",
            disabled=["job", "what", "next"],
            height=35 * (len(jobs) + 1) + 3,  # every job, no scrolling
            column_config={
                "on": st.column_config.CheckboxColumn("On", width="small"),
                "job": st.column_config.TextColumn("Job"),
                "what": st.column_config.TextColumn("What it does", width="large"),
                "next": st.column_config.TextColumn("Next run (India time)"),
            },
            key="jobs",
        )
        off = sorted(set(edited.loc[~edited["on"], "job"]))
        if off != sorted(paused) and st.button("Save the jobs", icon=":material/save:"):
            store.save(session, "paused_jobs", ",".join(off))
            st.rerun()
        st.caption(
            "A job turned off here doesn't run on its schedule; it still runs when started by "
            "hand. Times are changed in config/schedule.yaml."
        )

        st.subheader("First-run setup")
        if st.button("Run the setup again", icon=":material/rocket_launch:"):
            from stock_news_analyzer.agents import setup

            setup.start(session)
            st.session_state["setup_step"] = 0
            st.rerun()
        st.caption("The welcome screens: AI key, stocks and history. Nothing is removed.")

        st.subheader("Where each setting comes from")
        st.dataframe(
            pd.DataFrame(
                [
                    {"setting": label, "from": store.source(session, k)}
                    for k, label in SETTING_NAMES.items()
                ]
            ),
            hide_index=True,
        )
        st.caption(
            "Settings page: saved here, in this computer's database. .env: the project's .env "
            "file. default: neither. Removing a saved value goes back to .env or the default."
        )


SETUP_STEPS = ["Welcome", "AI features", "Your stocks", "History"]


def setup_page() -> None:
    """First-run setup: four screens, shown to a new copy until finished or skipped."""
    from stock_news_analyzer.agents import setup

    step = st.session_state.setdefault("setup_step", 0)
    st.progress((step + 1) / len(SETUP_STEPS), text=f"Step {step + 1} of 4: {SETUP_STEPS[step]}")
    with Session(engine()) as session:
        [_setup_welcome, _setup_ai, _setup_stocks, _setup_history][step](session, setup)


def _go(step: int) -> None:
    st.session_state["setup_step"] = step
    st.rerun()


def _finish_setup(session: Session, setup) -> None:
    setup.finish(session)
    st.session_state.pop("setup_step", None)
    load.clear()
    st.rerun()


def _setup_welcome(session: Session, setup) -> None:
    st.title("Welcome to Stock News Analyzer")
    st.markdown(
        "It follows a list of Indian stocks for you. Every morning it reads what each company "
        "filed with NSE and BSE, the news about it, its price, results and earnings calls, and "
        "tells you what changed: why a stock moved, new orders, what management promised, and "
        "red flags. It runs on this computer; your stocks and data stay here.\n\n"
        "**It needs:**\n"
        "- this computer on, with Docker running, in the morning (07:10 to 08:00 India time)\n"
        "- optionally an Anthropic API key for the AI features, which you pay for "
        "(a few dollars a month for 15 stocks)\n\n"
        "The next three screens take about five minutes, plus the time to load history."
    )
    st.caption("Not advice: everything it shows is information to check.")
    a, b = st.columns([1, 3])
    if a.button("Start", type="primary", icon=":material/arrow_forward:"):
        setup.start(session)
        _go(1)
    if b.button("Skip the setup; I'll set it up myself"):
        _finish_setup(session, setup)


def _setup_ai(session: Session, setup) -> None:
    from stock_news_analyzer import settings_store as store
    from stock_news_analyzer.llm import check_key

    st.title("AI features")
    st.markdown(
        "With an Anthropic API key, Claude explains unusual days, reads earnings calls and "
        "results, sorts the news, extracts orders and events, and answers questions. Without "
        "one, collecting, prices, shareholding, some red flags and the dashboard "
        "still work, and you can add a key later on **Settings**."
    )
    cfg = get_settings()
    if cfg.anthropic_api_key:
        st.success(
            f"A key is set (from {store.source(session, 'anthropic_api_key')}).",
            icon=":material/key:",
        )
    else:
        st.markdown(
            "Get a key at [console.anthropic.com](https://console.anthropic.com) (API keys), "
            "and paste it here."
        )
        with st.form("setup_key", clear_on_submit=True):
            key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-...")
            if st.form_submit_button("Check and save the key"):
                problem = check_key(key.strip()) if key.strip() else "enter a key first"
                if problem:
                    st.error(problem)
                else:
                    store.save(session, "anthropic_api_key", key.strip())
                    st.rerun()
    new_budget = st.number_input(
        "Monthly budget, US$ (AI calls stop when it is reached)",
        min_value=0.0,
        step=1.0,
        value=5.0
        if store.source(session, "llm_monthly_budget_usd") == "default"
        else float(cfg.llm_monthly_budget_usd),
        help="$5 covers the daily work for about 15 stocks once their history has been read. "
        "Reading a new stock's history the first time costs more.",
    )
    a, b, c = st.columns([1, 1, 3])
    if a.button("Back"):
        _go(0)
    label = "Next" if cfg.anthropic_api_key else "Continue without AI"
    if b.button(label, type="primary"):
        store.save(session, "llm_monthly_budget_usd", new_budget)
        _go(2)


def _setup_stocks(session: Session, setup) -> None:
    st.title("Your stocks")
    if not setup.has_companies(session):
        st.markdown(
            "First, the list of companies listed on NSE and BSE, so you can search them. It "
            "takes about a minute."
        )
        if st.button("Download the company list", type="primary", icon=":material/download:"):
            failed = None
            with st.status("Downloading the NSE and BSE lists...") as box:
                try:
                    warnings = setup.download_companies(session, get_settings().data_dir)
                except Exception as exc:  # no internet, or NSE refused: say so, let them retry
                    session.rollback()
                    failed, warnings = f"{type(exc).__name__}: {str(exc)[:300]}", []
                for w in warnings:
                    box.write(f"⚠️ {w}")
                box.update(
                    label="The download failed" if failed else "Company list downloaded",
                    state="error" if failed else "complete",
                )
            if failed:
                st.error(f"{failed}. Check the internet connection and try again in a few minutes.")
            else:
                st.rerun()
        if st.button("Back"):
            _go(1)
        return
    st.markdown(
        "Add the stocks you own and the ones you follow. **Stocks I own** also get their "
        "earnings calls read. You can change the list any time on **Manage stocks**."
    )
    add_stock_form(session, offer_history=False)
    stocks = actions.tracked_stocks(session)
    st.divider()
    if stocks:
        st.markdown(
            f"**{len(stocks)} stock{'s' * (len(stocks) != 1)}:** "
            + ", ".join(
                f"{s['symbol'] or s['name']}" + (" (own)" if s["owned"] else "") for s in stocks
            )
        )
    elif st.button(
        "Or start with five large companies (Reliance, HDFC Bank, Infosys, L&T, ITC)",
        icon=":material/playlist_add:",
    ):
        setup.add_examples(session)
        load.clear()
        st.rerun()
    a, b, c = st.columns([1, 1, 3])
    if a.button("Back"):
        _go(1)
    if b.button("Next", type="primary", disabled=not stocks):
        _go(3)


def _setup_history(session: Session, setup) -> None:
    st.title("History")
    stocks = actions.tracked_stocks(session)
    st.markdown(
        "To compare today with the past, the system needs history: daily prices for every "
        f"listed stock, and the filings and news of your {len(stocks)} stock"
        f"{'s' * (len(stocks) != 1)}. It is safe to "
        "stop and run again: what is loaded is kept."
    )
    choice = st.radio("How far back", list(setup.HISTORY_CHOICES), horizontal=True)
    start = setup.history_start(choice)
    days = len(pd.bdate_range(start, datetime.now(IST).date()))
    st.caption(
        f"From {start:%d %b %Y}: prices for about {days} trading days (about "
        f"{max(1, days * 3 // 60)} minutes), then a few minutes per stock. Keep this tab open."
    )
    a, b, c = st.columns([1, 2, 2])
    if a.button("Back"):
        _go(2)
    if b.button("Load history", type="primary", icon=":material/download:"):
        data_dir = get_settings().data_dir
        errors = []
        with st.status("Loading history...", expanded=True) as box:
            try:
                errors += setup.load_prices(session, data_dir, start, progress=box.write)
            except Exception as exc:  # NSE unreachable: say so and go on with the stocks
                session.rollback()
                errors.append(f"prices: stopped: {type(exc).__name__}: {exc}"[:300])
            for s in stocks:
                box.write(f"**{s['symbol'] or s['name']}**")
                try:
                    errors += actions.load_history(
                        session, s["isin"], data_dir, since=start, progress=box.write
                    )
                except Exception as exc:  # keep going with the next stock
                    session.rollback()
                    errors.append(f"{s['symbol']}: stopped: {type(exc).__name__}: {exc}"[:300])
            box.update(
                label="History loaded" + (f" ({len(errors)} problems)" if errors else ""),
                state="error" if errors else "complete",
            )
        for err in errors[:20]:
            st.warning(err)
        st.session_state["setup_loaded"] = len(errors)
    if c.button("Skip; load it later on Manage stocks"):
        _finish_setup(session, setup)
    if "setup_loaded" in st.session_state:
        if st.session_state["setup_loaded"]:
            st.warning(
                "Some history could not be loaded (see above). Load history again to fill the "
                "gaps (what is already loaded is kept), or go on and use Manage stocks later.",
                icon=":material/warning:",
            )
        st.success(
            "To keep it up to date every morning, start the scheduler: `make scheduler` in the "
            "project folder. Each new day's filings, news and prices then arrive on their own.",
            icon=":material/schedule:",
        )
        if st.button("Go to Today", type="primary", icon=":material/today:"):
            st.session_state.pop("setup_loaded", None)
            _finish_setup(session, setup)


def guide_page() -> None:
    st.title("Guide")
    st.caption(
        "How to use Stock News Analyzer: what it does, a daily routine, and each page. "
        "Open a section to read it."
    )
    wanted = st.query_params.get("section")
    for i, (title, body) in enumerate(guide.sections().items()):
        # A page's help link opens its section; with no link, the first one is open.
        opened = guide.slug(title) == wanted if wanted else i == 0
        with st.expander(title, expanded=opened):
            st.markdown(body)


stock_page = st.Page(stock_page_body, title="Stock", icon=":material/show_chart:", url_path="stock")
PAGES = {
    "today": st.Page(today_page, title="Today", icon=":material/today:", default=True),
    "flags": st.Page(flags_page, title="Red flags", icon=":material/flag:", url_path="flags"),
    "stock": stock_page,
    "filings": st.Page(
        filings_page, title="Filings", icon=":material/description:", url_path="filings"
    ),
    "news": st.Page(news_page, title="News", icon=":material/newspaper:", url_path="news"),
    "themes": st.Page(themes_page, title="Themes", icon=":material/hub:", url_path="themes"),
    "ask": st.Page(ask_page, title="Ask", icon=":material/question_answer:", url_path="ask"),
    "moves": st.Page(
        moves_page, title="What moves the stock", icon=":material/insights:", url_path="moves"
    ),
    "manage": st.Page(
        manage_page, title="Manage stocks", icon=":material/playlist_add:", url_path="manage"
    ),
    "settings": st.Page(
        settings_page, title="Settings", icon=":material/tune:", url_path="settings"
    ),
    "system": st.Page(
        system_page, title="System", icon=":material/monitor_heart:", url_path="system"
    ),
    "guide": st.Page(guide_page, title="Guide", icon=":material/help:", url_path="guide"),
}


SETUP_PAGE = st.Page(setup_page, title="Setup", icon=":material/rocket_launch:", url_path="setup")


def setup_needed() -> bool:
    """A new copy (no stocks), or a setup started and not finished (also from Settings)."""
    from stock_news_analyzer.agents.setup import needs_setup

    try:
        with Session(engine()) as session:
            return needs_setup(session)
    except Exception:  # no database or tables yet: the pages say so themselves
        return False


# The sidebar's groups, in order.
NAV = {
    "Today": ["today", "flags"],
    "Research": ["stock", "ask", "themes", "moves"],
    "Library": ["filings", "news"],
    "Set up": ["manage", "settings", "system"],
    "Help": ["guide"],
}


def main() -> None:
    if setup_needed():
        st.navigation([SETUP_PAGE, PAGES["guide"]]).run()
        return
    with st.sidebar:
        if st.button("Refresh data", icon=":material/refresh:"):
            load.clear()
        st.caption("Collecting happens in the scheduler; add stocks on Manage stocks.")
        st.page_link(PAGES["guide"], label="New here? Read the Guide", icon=":material/help:")
    st.navigation({group: [PAGES[k] for k in keys] for group, keys in NAV.items()}).run()


if __name__ == "__main__":  # `streamlit run` runs this file as __main__
    main()
