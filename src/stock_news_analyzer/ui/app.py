"""The dashboard: `sna ui` (or `make ui`) starts it at http://localhost:8501.

Every page only reads, except Manage stocks, which adds, edits and removes watchlist stocks
and can load a new stock's history, and Ask, which asks the Analyst Q&A (an LLM call) and keeps
the question. Regular collecting is done by the scheduler.
"""

import base64
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
from stock_news_analyzer.ui import actions, agent_map, charts, guide, queries

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


# The look shared by every page, in the theme's colours (.streamlit/config.toml): cards and tiles
# on a white (or charcoal) surface, IBM Plex Mono for stock symbols, small tags for kinds and
# confidence, an "AI" tag on AI-written text, and coloured dots for red-flag severity. Up and
# down always carry an arrow or a sign as well as a colour.
PALETTE = {
    "light": dict(
        bg="#fbfaf7",
        text="#141b24",
        card="#ffffff",
        border="#e1ded7",
        muted="#5b646f",
        soft="#f3f0ea",
        accent="#dfeef7",
        accent_text="#004766",
        up="#0f6a31",
        down="#cc2827",
        high="#cc2827",
        medium="#875300",
        low="#5f6469",
    ),
    "dark": dict(
        bg="#0b1015",
        text="#eae7e2",
        card="#13191f",
        border="#262c33",
        muted="#9299a1",
        soft="#1f252b",
        accent="#1a2b36",
        accent_text="#a9d9ef",
        up="#5ac576",
        down="#fa6863",
        high="#fa6863",
        medium="#f2af48",
        low="#8b9095",
    ),
}

STYLE = """
<style>
:root{THEME_VARIABLES}
/* Cards: bordered containers with a key starting "card", e.g. st.container(border=True,
   key="card-LT"). */
[class*="st-key-card"]{background:var(--sna-card)}
[data-testid="stMetricValue"]{font-size:1.5rem;font-variant-numeric:tabular-nums}
[data-testid="stMetricLabel"]{color:var(--sna-muted)}
h1{letter-spacing:-.01em}
/* Section headings are small, as in the design; the page title carries the weight. */
[data-testid="stMainBlockContainer"] h3{font-size:1.1rem;padding-top:.6rem}
/* The index strip: many indices fit on a row and wrap on narrow screens. */
.sna-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:8px;
  margin:4px 0 12px}
.sna-tile{background:var(--sna-card);border:1px solid var(--sna-border);border-radius:.5rem;
  padding:8px 10px}
.sna-tile .l{font-size:.78rem;color:var(--sna-muted);line-height:1.2}
.sna-tile .v{font-size:1.15rem;font-weight:600;margin:2px 0;font-variant-numeric:tabular-nums}
.sna-tile .c{font-size:.8rem;font-weight:600;font-variant-numeric:tabular-nums}
.sna-up{color:var(--sna-up)}
.sna-down{color:var(--sna-down)}
.sna-muted{color:var(--sna-muted)}
.sna-mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-weight:500}
/* The evidence's range: the middle half of the moves as a band, the median as a tick, and a
   line at zero, on one scale for the whole table. */
.sna-range{position:relative;height:16px;min-width:150px}
.sna-range .zero{position:absolute;top:0;bottom:0;width:1px;background:var(--sna-muted)}
.sna-range .band{position:absolute;top:5px;height:6px;border-radius:3px;
  background:color-mix(in srgb,var(--sna-muted) 40%,transparent)}
.sna-range .mid{position:absolute;top:1px;width:3px;height:14px;border-radius:2px;
  margin-left:-1px}
.sna-range .mid.sna-up{background:var(--sna-up)}
.sna-range .mid.sna-down{background:var(--sna-down)}
.sna-tag{display:inline-block;font-size:.75rem;line-height:1.3;padding:1px 7px;border-radius:999px;
  background:var(--sna-soft);color:var(--sna-muted);white-space:nowrap}
.sna-tag.ai{background:var(--sna-accent);color:var(--sna-accent-text);font-weight:600}
.sna-dot{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;margin-right:.35rem;
  vertical-align:.05rem;background:var(--sna-low)}
.sna-dot.high{background:var(--sna-high)}
.sna-dot.medium{background:var(--sna-medium)}
.sna-high{color:var(--sna-high)}
.sna-medium{color:var(--sna-medium)}
.sna-low{color:var(--sna-low)}
.sna-small{font-size:.8rem;line-height:1.45}
.sna-badge{display:inline-block;font-size:.72rem;font-weight:600;padding:2px 8px;
  border-radius:.35rem;background:var(--sna-high);color:#fff;white-space:nowrap}
/* Stock cards on Today. */
.sna-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.sna-card-head .sna-muted{font-size:.85rem}
.sna-symbol{font-size:.9rem;font-weight:700}
.sna-price-row{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;
  margin:10px 0 6px}
.sna-price{font-size:1.3rem;font-weight:600;font-variant-numeric:tabular-nums}
.sna-change{font-size:.9rem;font-weight:500;font-variant-numeric:tabular-nums}
.sna-rule{border-top:1px solid var(--sna-border);margin:2px 0 -6px}
/* Red flags as rows: dot, date, kind, then the stock and what happened. */
.sna-flags{margin:-6px -4px}
.sna-flag{display:flex;align-items:baseline;gap:12px;padding:9px 4px;font-size:.9rem;
  border-top:1px solid var(--sna-border)}
.sna-flag:first-child{border-top:0}
.sna-flag .sna-dot{flex:none;margin-right:0}
.sna-flag-date{flex:none;width:3.6rem;font-variant-numeric:tabular-nums}
.sna-flag-kind{flex:none;font-weight:500}
@media (max-width:640px){.sna-flag{flex-wrap:wrap;gap:4px 10px}}
/* Number tiles: a label, a large value, a line under it. */
.sna-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
  margin:6px 0 10px}
.sna-stat{background:var(--sna-card);border:1px solid var(--sna-border);border-radius:.5rem;
  padding:12px 16px}
.sna-stat .l{font-size:.78rem;color:var(--sna-muted)}
.sna-stat .v{font-size:1.5rem;font-weight:600;margin-top:2px;font-variant-numeric:tabular-nums}
.sna-stat .s{font-size:.8rem;margin-top:2px;color:var(--sna-muted)}
.sna-card-title{font-weight:600;font-size:.95rem}
/* Tables whose text wraps; on a phone each row becomes a card. */
.sna-table-wrap{border:1px solid var(--sna-border);border-radius:.5rem;overflow-x:auto;
  background:var(--sna-card)}
.sna-table{width:100%;border-collapse:collapse;font-size:.87rem}
.sna-table th{text-align:left;font-weight:500;font-size:.78rem;color:var(--sna-muted);
  padding:9px 12px;border-bottom:1px solid var(--sna-border);background:var(--sna-soft)}
.sna-table td{padding:9px 12px;vertical-align:top;border-top:1px solid var(--sna-border);
  line-height:1.45}
.sna-table tr:first-child td{border-top:0}
.sna-table .r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.sna-table a{color:inherit;text-decoration:underline;text-decoration-color:var(--sna-border)}
@media (max-width:640px){
  .sna-table thead{display:none}
  .sna-table,.sna-table tbody,.sna-table tr,.sna-table td{display:block;width:100%}
  .sna-table tr{border-top:1px solid var(--sna-border);padding:6px 0}
  .sna-table tr:first-child{border-top:0}
  .sna-table td{border:0;padding:3px 12px;text-align:left!important;white-space:normal}
  .sna-table td::before{content:attr(data-label);display:block;font-size:.72rem;
    color:var(--sna-muted)}
}
.sna-tag.good{background:color-mix(in srgb,var(--sna-up) 15%,transparent);color:var(--sna-up)}
.sna-tag.warn{background:color-mix(in srgb,var(--sna-medium) 15%,transparent);
  color:var(--sna-medium)}
.sna-tag.bad{background:color-mix(in srgb,var(--sna-high) 15%,transparent);color:var(--sna-high)}
.sna-dot.good{background:var(--sna-up)}
.sna-dot.warn{background:var(--sna-medium)}
.sna-dot.bad{background:var(--sna-high)}
.sna-week p{margin:.2rem 0 .6rem}
/* The research brief, in the briefing grammar: a lede (eyebrow, verdict, summary, stances,
   ruled key numbers, a callout), then numbered folds; every figure wears an evidence badge. */
.sna-lede{padding:.2rem 0 .8rem}
.sna-eyebrow{font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--sna-muted)}
.sna-lede-title{font-size:1.7rem;font-weight:700;line-height:1.25;margin:.35rem 0 .4rem}
.sna-lede-sub{color:var(--sna-muted);margin:0 0 .8rem;max-width:60rem}
.sna-stances{display:flex;flex-wrap:wrap;gap:.5rem;margin:.2rem 0 1rem}
.sna-stance{border:1px solid var(--sna-border);border-radius:999px;padding:.25rem .75rem;
  font-size:.85rem;background:var(--sna-card)}
.sna-stance b{margin-right:.35rem}
.sna-ruled{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  border-top:1px solid var(--sna-border);border-bottom:1px solid var(--sna-border);
  margin:.4rem 0 1rem}
.sna-ruled>div{padding:.7rem .8rem;border-right:1px solid var(--sna-border)}
.sna-ruled>div:last-child{border-right:none}
.sna-ruled .v{font-size:1.35rem;font-weight:700;font-family:"IBM Plex Mono",ui-monospace,monospace}
.sna-ruled .l{font-size:.8rem;color:var(--sna-muted)}
.sna-callout{border-left:3px solid var(--sna-accent-text);background:var(--sna-card);
  padding:.6rem .9rem;border-radius:0 8px 8px 0;margin:.4rem 0 1rem;font-size:.9rem}
.sna-callout.warn{border-left-color:var(--sna-medium)}
.sna-ev{font-size:.68rem;border-radius:999px;padding:.05rem .45rem;margin-left:.35rem;
  border:1px solid var(--sna-border);color:var(--sna-muted);white-space:nowrap;
  vertical-align:middle}
.sna-ev.filed{color:var(--sna-up);border-color:var(--sna-up)}
.sna-ev.ai{color:var(--sna-accent-text);border-color:var(--sna-accent-text)}
.sna-ev.stale{color:var(--sna-medium);border-color:var(--sna-medium)}
.sna-ev.nd{border-style:dashed}
.sna-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.75rem}
.sna-ecard{border:1px solid var(--sna-border);border-radius:10px;padding:.8rem;
  background:var(--sna-card)}
.sna-ecard.subject{border-color:var(--sna-accent-text)}
.sna-ecard .t{font-weight:700;margin:.15rem 0}
.sna-ecard .s{display:flex;gap:1rem;margin-top:.5rem;font-size:.85rem}
.sna-ecard .s b{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace}
.sna-timeline{list-style:none;padding:0;margin:0}
.sna-timeline li{display:flex;gap:1rem;padding:.45rem 0;border-bottom:1px solid var(--sna-border)}
.sna-stance.favor b{color:var(--sna-up)}
.sna-stance.avoid b{color:var(--sna-down)}
.sna-stance.watch b{color:var(--sna-medium)}
.sna-or{display:grid;grid-template-columns:1fr 1fr;gap:.4rem 1.2rem;padding:.7rem 0;
  border-bottom:1px solid var(--sna-border)}
.sna-or p{margin:.15rem 0 0}
.sna-or .sna-cites{grid-column:1/-1}
.sna-cite{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.72rem;
  border:1px solid var(--sna-border);border-radius:4px;padding:0 .3rem;margin-right:.25rem;
  color:var(--sna-muted);cursor:help}
.sna-note{font-size:.85rem;margin:.45rem 0 0}
.sna-check{margin:.3rem 0 0;padding-left:1.1rem}
.sna-sources{list-style:none;padding:0;font-size:.85rem}
.sna-sources li{padding:.2rem 0;border-bottom:1px solid var(--sna-border)}
@media (max-width:640px){.sna-or{grid-template-columns:1fr}}
.sna-timeline li .d{min-width:6.5rem;font-family:"IBM Plex Mono",ui-monospace,monospace}
.sna-week ul{margin:.2rem 0 .8rem;padding-left:1.1rem}
.sna-week li{margin:.15rem 0}
.sna-meter{display:inline-flex;gap:2px;vertical-align:middle}
.sna-meter i{width:7px;height:12px;border-radius:2px;background:var(--sna-soft)}
.sna-meter i.on{background:var(--sna-accent-text)}
.sna-quote{font-style:italic;color:var(--sna-muted);font-size:.82rem}
.sna-tone{font-size:.95rem;display:flex;align-items:center;gap:6px}
.sna-tone .sna-dot{margin-right:0}
.sna-summary{margin:.5rem 0 0;line-height:1.55}
.sna-h3{font-size:1.1rem;font-weight:600;margin:1.2rem 0 .2rem;display:flex;align-items:center;
  gap:8px}
.sna-sources{font-size:.82rem;color:var(--sna-muted);border-top:1px solid var(--sna-border);
  padding-top:8px;margin-top:4px}
.sna-sources ol{margin:4px 0 0 1.2rem;padding:0}
.sna-sources li{margin:2px 0}
.sna-sources a{color:inherit}
</style>
"""


def apply_style() -> None:
    """The shared styles, in the colours of the theme in use."""
    colours = PALETTE["dark" if dark() else "light"]
    variables = ";".join(f"--sna-{k.replace('_', '-')}:{v}" for k, v in colours.items())
    st.html(STYLE.replace("THEME_VARIABLES", variables))


def index_tiles(rows: list[dict]) -> None:
    tiles = []
    for m in rows:
        change = m["change"]
        if change is None:
            delta = '<div class="c">–</div>'
        else:
            arrow, cls = ("▲", "sna-up") if change >= 0 else ("▼", "sna-down")
            delta = f'<div class="c {cls}">{arrow} {change:+.2%}</div>'
        name = html.escape(m["index"])
        value = f"{m['close']:,.2f}" if m["close"] else "–"
        tiles.append(
            f'<div class="sna-tile" title="{name}, {m["date"]}"><div class="l">{name}</div>'
            f'<div class="v">{value}</div>{delta}</div>'
        )
    st.markdown(f'<div class="sna-tiles">{"".join(tiles)}</div>', unsafe_allow_html=True)


def signed(x, digits: int = 2) -> str:
    """A percentage with its sign and a true minus (−1.24%), or a dash."""
    return "–" if x is None or pd.isna(x) else f"{x:+.{digits}%}".replace("-", "−")


def trend(x) -> str:
    """The class that colours a change: up, down or neither."""
    if x is None or pd.isna(x) or x == 0:
        return ""
    return "sna-up" if x > 0 else "sna-down"


def change_html(x) -> str:
    """A day's change with an arrow, coloured: ▲ +1.24%."""
    if x is None or pd.isna(x):
        return '<span class="sna-muted">–</span>'
    return f'<span class="{trend(x)}">{"▲" if x >= 0 else "▼"} {signed(x)}</span>'


def sparkline(values: list[float], width: int = 96, height: int = 32) -> str:
    """A small line of the last three months, green if it ended higher, red if lower. An image,
    since st.html leaves out inline SVG."""
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    points = " ".join(
        f"{i / (len(values) - 1) * width:.1f},"
        f"{height - (v - low) / ((high - low) or 1) * (height - 2) - 1:.1f}"
        for i, v in enumerate(values)
    )
    colours = PALETTE["dark" if dark() else "light"]
    colour = colours["up"] if values[-1] >= values[0] else colours["down"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><polyline points="{points}" fill="none" '
        f'stroke="{colour}" stroke-width="1.5"/></svg>'
    )
    data = base64.b64encode(svg.encode()).decode()
    return (
        f'<img src="data:image/svg+xml;base64,{data}" width="{width}" height="{height}" '
        'alt="Last three months">'
    )


def section_title(title: str, link_page=None, link_label: str = "") -> None:
    """A section heading, with an optional link on the right."""
    if link_page is None:
        st.subheader(title)
        return
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    left.subheader(title)
    with right:
        st.page_link(link_page, label=link_label, icon=":material/arrow_forward:")


def stock_card(s: dict) -> None:
    """A card per stock: the close and the day's change with a 3-month line, the move against
    the Nifty 50 and the sector, an Unusual badge with the likely cause, and a link to it."""
    threshold = get_settings().unusual_threshold
    spark = load("performance", isin=s["isin"], start=date.today() - timedelta(days=91))
    badge = (
        f'<span class="sna-badge" title="Move vs Nifty 50 beyond {threshold}σ of the last '
        '60 days">Unusual</span>'
        if s["unusual"]
        else ""
    )
    compare = (
        f'vs Nifty 50 <span class="{trend(s["excess_return"])}">{signed(s["excess_return"])}</span>'
    )
    if s["sector_index"]:
        compare += (
            f" · vs {html.escape(s['sector_index'])} "
            f'<span class="{trend(s["sector_excess_return"])}">'
            f"{signed(s['sector_excess_return'])}</span>"
        )
    if s["zscore"] is not None:
        compare += f" · z {s['zscore']:.1f}".replace("-", "−")
    cause = (
        f'<div class="sna-small"><span class="sna-muted">Likely cause:</span> '
        f"<b>{html.escape(s['cause'].replace('_', ' '))}</b></div>"
        if s["unusual"] and s.get("cause")
        else ""
    )
    close = f"₹{s['close']:,.2f}" if s["close"] else "–"
    with st.container(border=True, key=f"card-{s['isin']}", gap="small"):
        st.html(
            f'<div class="sna-card-head"><div><div class="sna-mono sna-symbol">'
            f"{html.escape(s['symbol'] or '')}</div>"
            f'<div class="sna-muted">{html.escape(s["name"])}</div></div>{badge}</div>'
            f'<div class="sna-price-row"><div><div class="sna-price">{close}</div>'
            f'<div class="sna-change">{change_html(s["stock_return"])}</div></div>'
            f"{sparkline(list(spark['stock'].dropna())) if not spark.empty else ''}</div>"
            f'<div class="sna-small sna-muted">{compare}</div>{cause}'
        )
        st.html('<div class="sna-rule"></div>')
        left, right = st.columns([2, 1], vertical_alignment="center")
        left.caption(f"Last 7 days: {s['filings_7d']} filings, {s['news_7d']} news articles")
        with right:
            st.page_link(
                stock_page,
                label="Open",
                icon=":material/arrow_forward:",
                query_params={"symbol": s["symbol"]},
            )


def page_header(title: str, description: str, section: str, *notes: str) -> None:
    """A page's title with its "How to use this page" link, then a line on what it shows."""
    left, right = st.columns([4, 1], vertical_alignment="bottom")
    left.title(title)
    with right:
        help_link(section)
    for note in notes:
        st.caption(note)
    st.caption(description)


def blank(value) -> bool:
    """Nothing to show: None, NaN (an empty cell from a table) or an empty string."""
    return value is None or value == "" or (not isinstance(value, str | list) and pd.isna(value))


def esc(value) -> str:
    """Text for HTML, or a dash for nothing."""
    if blank(value):
        return '<span class="sna-muted">–</span>'
    return html.escape(str(value))


def study_moves(study: list[dict]) -> None:
    """The study-only stocks (the Nifty 50) in one table, unusual moves first, instead of a
    card each."""
    if not study:
        return
    unusual = [s for s in study if s["unusual"]]
    section_title(f"Nifty 50, study only ({len(study)})")
    st.caption(
        (f"{len(unusual)} moved unusually on the last day. " if unusual else "No unusual moves. ")
        + "Followed for the evidence; untick Study only on Manage stocks to follow one fully."
    )

    def change(x, _row):
        return f'<span class="{trend(x)}">{signed(x)}</span>'

    rows = sorted(study, key=lambda s: (not s["unusual"], -abs(s["excess_return"] or 0)))
    with st.expander("All of them, largest moves against the Nifty first", expanded=bool(unusual)):
        html_table(
            rows,
            [
                ("Stock", "symbol", lambda v, r: f'<span class="sna-mono">{esc(v)}</span>'),
                ("Company", "name", None),
                ("Day>", "stock_return", change),
                ("vs Nifty 50>", "excess_return", change),
                ("Unusual", "unusual", lambda v, r: tag("unusual", "warn") if v else ""),
                ("Likely cause", "cause", None),
            ],
        )


def html_table(rows, columns: list[tuple], empty: str = "Nothing to show.") -> None:
    """A table whose text wraps instead of being cut off; on a narrow screen each row becomes a
    stacked card. `columns`: (label, field, render) where render(value, row) returns HTML, or
    None to show the value as text; a label ending in ">" right-aligns the column."""
    records = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else list(rows)
    if not records:
        st.caption(empty)
        return
    head, body = [], []
    for label, _field, _render in columns:
        right = label.endswith(">")
        head.append(f'<th class="{"r" if right else ""}">{html.escape(label.rstrip(">"))}</th>')
    for row in records:
        cells = []
        for label, field, render in columns:
            value = row.get(field)
            content = render(value, row) if render else esc(value)
            right = label.endswith(">")
            cells.append(
                f'<td class="{"r" if right else ""}" data-label="'
                f'{html.escape(label.rstrip(">"))}">{content}</td>'
            )
        body.append(f"<tr>{''.join(cells)}</tr>")
    st.html(
        f'<div class="sna-table-wrap"><table class="sna-table"><thead><tr>{"".join(head)}'
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def stat_tiles(items: list[tuple[str, str, str]]) -> None:
    """Number tiles in a row: (label, value HTML, line under it HTML)."""
    tiles = "".join(
        f'<div class="sna-stat"><div class="l">{html.escape(label)}</div>'
        f'<div class="v">{value}</div>' + (f'<div class="s">{sub}</div>' if sub else "") + "</div>"
        for label, value, sub in items
    )
    narrow = ' style="max-width:420px"' if len(items) == 1 else ""
    st.html(f'<div class="sna-stats"{narrow}>{tiles}</div>')


def tag(text: str, kind: str = "") -> str:
    """A small pill: kind good, bad, warn or ai colours it."""
    return f'<span class="sna-tag {kind}">{html.escape(text)}</span>'


AI_TAG = '<span class="sna-tag ai" title="Written by AI; check the sources">✦ AI</span>'
SENTIMENT_CLASS = {
    "positive": "sna-up",
    "negative": "sna-down",
    "good": "sna-up",
    "bad": "sna-down",
}
STATUS_KIND = {
    "kept": "good",
    "kept_late": "warn",
    "partly": "warn",
    "delayed": "warn",
    "revised": "warn",
    "missed": "bad",
}


def sentiment_html(value, _row=None) -> str:
    if blank(value):
        return esc(None)
    return f'<span class="{SENTIMENT_CLASS.get(value, "sna-muted")}">{html.escape(value)}</span>'


def quote_html(value, _row=None) -> str:
    """Words quoted from a filing or call, in italics and quotation marks."""
    return esc(None) if blank(value) else f'<span class="sna-quote">“{html.escape(value)}”</span>'


def chart_card(title: str, key: str):
    """A card holding one chart, with its title."""
    box = st.container(border=True, key=f"card-chart-{key}")
    box.html(f'<div class="sna-card-title">{html.escape(title)}</div>')
    return box


def today_page() -> None:
    watch = stocks()
    if not watch:
        no_data("No stocks yet. Add them on the Manage stocks page.")
        return
    latest = max((s["date"] for s in watch if s["date"]), default=None)
    page_header(
        "Today",
        "What changed since yesterday across your stocks.",
        "a-daily-routine",
        f"Last trading day loaded: {latest:%a %d %b %Y}"
        if latest
        else "No prices loaded yet: run the **prices** job on System (Run a job now).",
    )
    index_tiles(load("market"))
    red_flag_list(load("red_flags"), "Red flags, last 30 days")

    owned = [s for s in watch if s["owned"]]
    watching = [s for s in watch if not s["owned"] and not s["study_only"]]
    for title, group in (("Stocks I own", owned), ("Watchlist", watching)):
        section_title(f"{title} ({len(group)})")
        if not group:
            st.caption("None yet. Add stocks on the Manage stocks page.")
            help_link("getting-started")
            continue
        cols = st.columns(3)
        for i, s in enumerate(group):
            with cols[i % 3]:
                stock_card(s)
    study_moves([s for s in watch if s["study_only"]])

    bullion_section()

    left, right = st.columns([2, 1])
    with left:
        section_title("Latest digest")
        digest = queries.latest_digest(get_settings().data_dir)
        if digest:
            name, text = digest
            try:
                label = f"{datetime.strptime(name[:15], '%Y-%m-%d_%H%M'):%d %b %Y, %H:%M} IST"
            except ValueError:
                label = name.removesuffix(".md")
            with st.expander(f"Morning report · {label}", expanded=False):
                st.markdown(text)
        else:
            no_data("No digest saved yet. The scheduler writes one every morning.")
    with right:
        section_title("Data collection")
        last = load("last_runs")
        rows = pd.DataFrame(
            [
                {
                    "Job": job,
                    "Last run": r["started"].strftime("%d %b %H:%M") if r else "never",
                    "Status": ("✅ ok" if r["status"] == "ok" else f"⚠️ {r['status']}")
                    if r
                    else "–",
                }
                for job, r in last.items()
            ]
        )
        colours = PALETTE["dark" if dark() else "light"]
        st.dataframe(
            rows.style.map(
                lambda v: (
                    f"color:{colours['up'] if v.startswith('✅') else colours['high']}"
                    if v[:1] in "✅⚠"
                    else ""
                ),
                subset=["Status"],
            ),
            hide_index=True,
            width="stretch",
        )


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

    left, right = st.columns([4, 1], vertical_alignment="bottom")
    left.title(s["name"])
    with right:
        help_link()
    sector = s["sector_index"] or "no sector index"
    st.caption(
        f"NSE {s['symbol']} · benchmark Nifty 50 and {sector}" + (" · owned" if s["owned"] else "")
    )
    st.caption("One company in depth: its price against its benchmarks, and what moved it.")

    start = date.today() - timedelta(days=RANGES[window])
    perf = load("performance", isin=s["isin"], start=start)
    if perf.empty:
        no_data("No daily moves yet: run the **prices** job on System (Run a job now).")
    else:
        lb = load("labels", isin=s["isin"])
        events = (
            lb[lb["type"].isin(queries.KEY_TYPES)]
            .sort_values("exchange")
            .drop_duplicates(["type", "day0"])
        )
        last = perf.iloc[-1]

        def over(value) -> str:
            change = (value - 100) / 100
            return f'<span class="{trend(change)}">{signed(change)}</span>'

        tiles = [
            (f"{s['symbol']} over {window}", over(last["stock"]), ""),
            (f"Nifty 50 over {window}", over(last["nifty"]), ""),
        ]
        if s["sector_index"] and pd.notna(last["sector"]):
            tiles.append((f"{s['sector_index']} over {window}", over(last["sector"]), ""))
        tiles.append(("Unusual days", str(int(perf["unusual"].sum())), ""))
        stat_tiles(tiles)
        with chart_card("Price, each starting at 100", "price"):
            st.plotly_chart(
                charts.performance_chart(perf, s["symbol"], s["sector_index"], events, dark()),
                width="stretch",
                **PLOT,
            )
        with chart_card("Daily return minus the Nifty 50's", "excess"):
            st.plotly_chart(charts.excess_bars(perf, dark=dark()), width="stretch", **PLOT)
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
            confidence = {"high": "good", "medium": "warn", "low": ""}

            def move(value, _row) -> str:
                return f'<span class="{trend(value)}">{signed(value)}</span>'

            html_table(
                days,
                [
                    ("Day", "date", lambda v, r: f"{v:%d %b %Y}"),
                    ("Move>", "stock", move),
                    ("vs Nifty 50>", "vs_nifty", move),
                    ("z>", "zscore", lambda v, r: f"{v:+.1f}".replace("-", "−")),
                    ("Likely cause", "cause", lambda v, r: esc(v and v.replace("_", " "))),
                    (
                        "Confidence",
                        "confidence",
                        lambda v, r: tag(v, confidence.get(v, "")) if not blank(v) else esc(None),
                    ),
                    (
                        "Explanation",
                        "explanation",
                        lambda v, r: f"{AI_TAG} {html.escape(v)}" if not blank(v) else esc(None),
                    ),
                    (
                        "Based on",
                        "evidence",
                        lambda v, r: (
                            '<span class="sna-small sna-muted">'
                            + "<br>".join(html.escape(t) for t in v.split(" | "))
                            + "</span>"
                            if not blank(v)
                            else esc(None)
                        ),
                    ),
                ],
            )
            if missing:
                st.caption(
                    f"{missing} days not explained yet: the scheduler explains recent days each "
                    "morning; the **explain** job on System explains the rest now."
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
            "the **holdings** job on System reads three years now."
        )
        return
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    tiles = []
    for key, name in (
        ("promoter", "Promoters"),
        ("fii", "Foreign inst."),
        ("dii", "Domestic inst."),
        ("retail", "Retail"),
    ):
        change = ""
        if prev is not None and pd.notna(latest[key]) and pd.notna(prev[key]):
            points = latest[key] - prev[key]
            change = (
                f'<span class="{trend(points)}">{f"{points:+.2f}".replace("-", "−")} pts</span>'
                " since the quarter before"
            )
        tiles.append((f"{name}, {latest['quarter']:%b %Y}", _fmt(latest[key], "{:.2f}%"), change))
    stat_tiles(tiles)
    with chart_card("Who owns it, % of shares", "holdings"):
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

    def share(value, _row) -> str:
        return _fmt(value, "{:.2f}%")

    html_table(
        df.iloc[::-1],
        [
            ("Quarter end", "quarter", lambda v, r: f"{v:%b %Y}"),
            ("Promoters>", "promoter", share),
            ("Foreign inst.>", "fii", share),
            ("Domestic inst.>", "dii", share),
            ("Mutual funds>", "mf", share),
            ("Insurers>", "insurance", share),
            ("Retail>", "retail", share),
            ("Pledged, of promoters' shares>", "pledged", share),
            ("Shareholders>", "shareholders", lambda v, r: _fmt(v, "{:,.0f}")),
        ],
    )
    st.caption(
        "Percent of all shares, from the quarterly shareholding pattern. Domestic institutions "
        "include mutual funds and insurers; retail is individuals holding up to Rs 2 lakh."
    )


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
            "the **concalls** job on System reads any not read yet."
        )
        no_data(f"No earnings calls analysed yet. {how}")
    else:
        pick = st.selectbox(
            "Call",
            calls,
            format_func=lambda c: f"{c['quarter']} · filed {c['filed']:%d %b %Y} · {c['tone']}",
            key="concall",
        )
        tone = {"positive": "good", "cautious": "warn", "negative": "bad"}.get(pick["tone"], "")
        st.html(
            f'<div class="sna-tone"><span class="sna-dot {tone}"></span>Tone: '
            f"<b>{html.escape(pick['tone'])}</b> {AI_TAG}</div>"
            f'<p class="sna-summary">{html.escape(pick["summary"] or "")}</p>'
        )
        left, right = st.columns(2)
        with left:
            st.markdown("**To watch**")
            st.markdown("\n".join(f"- {p}" for p in pick["action_points"]) or "–")
        with right:
            st.markdown("**Since the previous call**")
            st.markdown(
                "\n".join(
                    f"- **{c['kind'].replace('_', ' ')}**: {c['text']}" for c in pick["changes"]
                )
                or "First call stored, nothing to compare with."
            )

        if pick["points"]:
            section_title("What management said")
            html_table(
                pick["points"],
                [
                    ("Topic", "category", lambda v, r: esc(CATEGORY.get(v, v))),
                    ("Point", "point", None),
                    ("For shareholders", "sentiment", sentiment_html),
                    ("In their words", "quote", quote_html),
                ],
            )
        if pick["concerns"]:
            section_title("What analysts pressed on")
            html_table(
                pick["concerns"],
                [
                    ("Topic", "topic", None),
                    ("Question", "question", None),
                    (
                        "Answer",
                        "answer",
                        lambda v, r: (
                            tag(v, {"evasive": "bad", "partial": "warn"}.get(v, ""))
                            if not blank(v)
                            else esc(None)
                        ),
                    ),
                ],
            )
        if pick["note"]:
            st.caption(pick["note"])
        with st.expander("Transcript text"):
            st.text(load("concall_text", doc_id=pick["document_id"])[:20000])

    ledger = load("promises", isin=s["isin"])
    section_title("Promise ledger")
    score = next((c for c in load("credibility") if c["isin"] == s["isin"]), None)
    if score:
        stat_tiles(
            [
                (
                    "Promises kept",
                    f"{score['score']:.0%}" if score["score"] is not None else "–",
                    f"Of {score['scored']} settled: {score['kept']} kept, {score['kept_late']} "
                    f"kept late, {score['partly']} partly, {score['missed']} missed, "
                    f"{score['dropped']} dropped, {score['overdue']} long overdue. "
                    f"{score['to_come']} still to come.",
                )
            ]
        )
        st.caption(
            "Kept counts 1, kept late or partly kept 0.5, missed, dropped or long overdue 0, over "
            "the promises settled so far; shown from 3 settled promises."
        )
    if ledger.empty:
        st.caption("No promises recorded yet.")
    else:
        overdue = int(ledger["overdue"].sum())
        html_table(
            ledger,
            [
                ("Promise", "promise", lambda v, r: f"<b>{esc(v)}</b>"),
                ("Target", "target", None),
                ("Due (as said)", "due", None),
                (
                    "Status",
                    "status",
                    lambda v, r: (
                        tag(v.replace("_", " "), STATUS_KIND.get(v, ""))
                        if not blank(v)
                        else esc(None)
                    ),
                ),
                ("Due by", "due_date", lambda v, r: f"{v:%d %b %Y}" if pd.notna(v) else esc(None)),
                (
                    "Overdue",
                    "overdue",
                    lambda v, r: '<span class="sna-down">✓</span>' if v else esc(None),
                ),
                ("Latest update", "note", None),
                ("Said in", "said_in", None),
                ("In their words", "quote", quote_html),
            ],
        )
        st.caption(
            "Each later call updates a promise when management mentions it again; once its "
            "date has passed, the Promise Ledger checks it against later results and filings"
            + (f". {overdue} past their date and still open." if overdue else ".")
        )
        checks = load("promise_checks", isin=s["isin"])
        if not checks.empty:
            with st.expander(f"How promises were checked ({len(checks)})"):
                html_table(
                    checks,
                    [
                        ("Checked", "checked", lambda v, r: f"{v:%d %b %Y}"),
                        ("Promise", "promise", None),
                        ("Finding", "note", None),
                        ("Based on", "based_on", None),
                    ],
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
            "the **xbrl** and **results** jobs on System read the last two years now."
        )
        return
    latest = periods.iloc[-1]

    def yoy(value) -> str:
        if value is None or pd.isna(value):
            return ""
        return f'<span class="{trend(value)}">{f"{value:+.0%}".replace("-", "−")} y/y</span>'

    stat_tiles(
        [
            (
                f"Revenue, {latest['period']}",
                _fmt(latest["revenue_cr"], "Rs {:,.0f} cr"),
                yoy(latest["revenue_yoy"]),
            ),
            ("Profit after tax", _fmt(latest["pat_cr"], "Rs {:,.0f} cr"), yoy(latest["pat_yoy"])),
            (
                "EBITDA margin",
                _fmt(latest["ebitda_margin"], "{:.1%}"),
                '<span class="sna-muted">PBT + finance costs + depreciation − other income, '
                "÷ revenue</span>",
            ),
        ]
    )
    with chart_card("Revenue and profit, Rs crore", "results"):
        st.plotly_chart(charts.revenue_chart(periods, dark()), width="stretch", **PLOT)

    def crore(value, _row) -> str:
        return _fmt(value, "{:,.0f}")

    def growth(value, _row) -> str:
        if value is None or pd.isna(value):
            return esc(None)
        return f'<span class="{trend(value)}">{f"{value:+.1%}".replace("-", "−")}</span>'

    html_table(
        periods.iloc[::-1],
        [
            ("Period", "period", None),
            ("Revenue>", "revenue_cr", crore),
            ("Revenue y/y>", "revenue_yoy", growth),
            ("EBITDA>", "ebitda_cr", crore),
            ("EBITDA margin>", "ebitda_margin", lambda v, r: _fmt(v, "{:.1%}")),
            ("Profit after tax>", "pat_cr", crore),
            ("Profit y/y>", "pat_yoy", growth),
            ("Net margin>", "pat_margin", lambda v, r: _fmt(v, "{:.1%}")),
            ("EPS (Rs)>", "eps", lambda v, r: _fmt(v, "{:.2f}")),
            ("Basis", "basis", None),
            (
                "Checked",
                "checked",
                lambda v, r: (
                    '<span class="sna-up" title="Every figure was found as written in '
                    'the filing">✓</span>'
                    if v is True
                    else esc(None)
                ),
            ),
        ],
    )
    st.caption(
        "Rs crore, from the results filed with the exchanges (consolidated where given). y/y: "
        "on the same period a year earlier."
    )


def bullion_section() -> None:
    """Each watched metal's last 30 days: the rupee move split into global price, rupee and
    the rest, with notes on unusual days (shaded)."""
    metals = load("bullion_metals")
    if not metals:
        return
    section_title("Bullion")
    colours = PALETTE["dark" if dark() else "light"]

    def colour(v) -> str:
        if v is None or pd.isna(v) or v == 0:
            return ""
        return f"color:{colours['up'] if v > 0 else colours['down']}"

    def shade(row) -> list[str]:
        unusual = row["z"] is not None and pd.notna(row["z"]) and abs(row["z"]) >= 2
        return [f"background-color:{colours['soft']}" if unusual else ""] * len(row)

    with st.container(border=True, key="card-bullion"):
        st.caption(
            "Each day's move of an NSE ETF holding the metal (GOLDBEES, SILVERBEES), split into "
            "the global price, the rupee–dollar rate and the rest (duty, the local premium, the "
            "gap between the Indian and New York closes). Shaded rows are unusual days (2σ), "
            "with a note on what drove them."
        )
        for metal, tab in zip(metals, st.tabs([m.title() for m in metals]), strict=True):
            with tab:
                rows = load("bullion", metal=metal, days=30)
                if rows.empty:
                    no_data("No moves yet: run the **bullion** job on System (Run a job now).")
                    continue
                moves = ["rupees", "global", "rupee", "other"]
                rows = rows.assign(driver=rows["driver"].fillna(""), note=rows["note"].fillna(""))
                styled = (
                    rows.style.apply(shade, axis=1)
                    .map(colour, subset=moves)
                    .format(signed, subset=moves)
                    .format("{:,.2f}", subset=["close"])
                    .format(
                        lambda z: "–" if pd.isna(z) else f"{z:+.1f}".replace("-", "−"), subset=["z"]
                    )
                    .format(lambda d: f"{d:%d %b %Y}", subset=["date"])
                )
                st.dataframe(
                    styled,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "date": st.column_config.TextColumn("Day"),
                        "close": st.column_config.TextColumn(f"{metal.title()} ETF close (₹)"),
                        "rupees": st.column_config.TextColumn("Move (₹)"),
                        "global": st.column_config.TextColumn("Global price"),
                        "rupee": st.column_config.TextColumn("USD/INR"),
                        "other": st.column_config.TextColumn("Other"),
                        "z": st.column_config.TextColumn("z"),
                        "driver": st.column_config.TextColumn("Driver"),
                        "note": st.column_config.TextColumn("Note", width="large"),
                    },
                )


def red_flag_list(flags: list[dict], title: str) -> None:
    """One row per flag: a dot coloured by severity, the date, the kind, the stock and what
    happened. Nothing when there are none."""
    if not flags:
        return
    section_title(title, PAGES["flags"], "All red flags")
    rows = "".join(
        f'<div class="sna-flag"><span class="sna-dot {f["severity"]}" '
        f'title="{f["severity"]}"></span><span class="sna-muted sna-flag-date">'
        f'{f["date"]:%d %b}</span><span class="sna-{f["severity"]} sna-flag-kind">'
        f'{html.escape(f["kind"])}</span><span><b class="sna-mono">{html.escape(f["symbol"])}</b>: '
        f"{html.escape(f['title'])}"
        + (f' <span class="sna-muted">({html.escape(f["detail"])})</span>' if f["detail"] else "")
        + "</span></div>"
        for f in flags
    )
    key = "".join(c if c.isalnum() else "-" for c in title.lower())
    with st.container(border=True, key=f"card-flags-{key}"):
        st.html(f'<div class="sna-flags">{rows}</div>')


def events_tab_body(s: dict) -> None:
    """Events from filings (capex, ratings, management changes...), each checked by the QA
    Checker, with the red flags they raised."""
    red_flag_list(load("red_flags", isin=s["isin"], days=365), "Red flags, last 12 months")
    rows = load("events", isin=s["isin"])
    if rows.empty:
        no_data(
            "No events recorded for this stock yet. The scheduler reads new filings each "
            "morning; the **events** job on System reads them now."
        )
        return

    def importance(value, _row) -> str:
        if value is None or pd.isna(value):
            return esc(None)
        n = int(value)
        return (
            f'<span class="sna-meter" title="Importance {n} of 5">'
            + "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(5))
            + "</span>"
        )

    def qa(value, row) -> str:
        mark = {"checked": "✅ passed", "you accepted it": "✅ you accepted it"}.get(
            value, f"— {value}"
        )
        notes = row.get("qa_notes")
        return html.escape(mark) + (
            f'<div class="sna-small sna-muted">{html.escape(notes)}</div>' if notes else ""
        )

    def link(value, _row) -> str:
        if not value:
            return esc(None)
        return f'<a href="{html.escape(value)}" target="_blank" rel="noopener">filing</a>'

    section_title("Events read from filings")
    html_table(
        rows,
        [
            ("Filed", "filed", lambda v, r: f"{v:%d %b %Y}"),
            ("Type", "type", None),
            ("Importance", "importance", importance),
            ("Sentiment", "sentiment", sentiment_html),
            ("Headline", "headline", lambda v, r: f"<b>{esc(v)}</b>"),
            ("Amount", "amount", lambda v, r: f'<span class="sna-small">{esc(v)}</span>'),
            ("QA", "qa", qa),
            ("From the filing", "quote", quote_html),
            ("Source", "link", link),
        ],
    )
    st.caption(
        "Read from the company's filings (Haiku), every quote and amount checked against the "
        "filing; important or doubtful events checked again by Sonnet. Unchecked: a check "
        "failed and nothing settled it, so treat it with care."
    )


def order_book(s: dict) -> None:
    """Orders announced, the quarterly order book, book-to-bill and peers."""
    data = load("order_book", isin=s["isin"])
    quarters, summary, orders = data["quarters"], data["summary"], data["orders"]
    if quarters.empty:
        no_data(
            "No orders read for this stock yet. The scheduler reads order-win filings each "
            "morning; the **orders** job on System reads them now."
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
        no_data("No labels yet: run the **prices** job on System (Run a job now).")
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
    page_header(
        "Filings",
        "Every filing your stocks made with NSE and BSE. Search by stock, type, words or date, "
        "and select a row to read the filing's text.",
        "the-pages",
    )
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
    page_header(
        "News",
        "Articles about your stocks from news feeds and Google News, with the AI's relevance "
        "and importance where it has read them.",
        "the-pages",
    )
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
        + (f", {untriaged} not triaged yet (the **triage** job on System)" if untriaged else "")
    )
    news_table(df)


def themes_page() -> None:
    page_header(
        "Themes",
        "Themes across your companies, whether they are getting stronger, and news at one "
        "company that may matter to another. Events, orders and earnings-call points are "
        "tagged with themes by AI; items count the last 90 days, before the 90 days before.",
        "the-pages",
    )
    themes = load("themes")
    if themes.empty:
        no_data("No themes yet: run the **themes** job on System (Run a job now).")
        return

    def trend_arrow(value, row) -> str:
        arrow = ""
        if row["items"] > row["before"]:
            arrow = ' <span class="sna-up" title="More than the 90 days before">↑</span>'
        elif row["items"] < row["before"]:
            arrow = ' <span class="sna-down" title="Fewer than the 90 days before">↓</span>'
        return f"<b>{esc(value)}</b>{arrow}"

    def count(cls):
        return lambda v, r: (
            f'<span class="{cls}">{v}</span>' if v else '<span class="sna-muted">0</span>'
        )

    html_table(
        themes,
        [
            ("Theme", "theme", trend_arrow),
            ("Items, 90 days>", "items", None),
            ("90 days before>", "before", None),
            ("Positive>", "positive", count("sna-up")),
            ("Negative>", "negative", count("sna-down")),
            ("Orders, Rs crore>", "orders_cr", lambda v, r: _fmt(v, "{:,.0f}")),
            (
                "Companies",
                "companies",
                lambda v, r: f'<span class="sna-mono sna-small">{esc(v)}</span>',
            ),
        ],
    )
    names = dict(zip(themes["theme"], themes["key"], strict=True))
    choice = st.selectbox("Theme", list(names))
    months, items = load("theme_detail", theme=names[choice])
    if not months.empty:
        with chart_card(f"{choice}: items each month", "theme-months"):
            by_month = months.assign(month=pd.to_datetime(months["month"]).dt.strftime("%b %Y"))
            st.bar_chart(by_month, x="month", y="items", height=220, sort=False)
    html_table(
        items,
        [
            ("Date", "date", lambda v, r: f"{v:%d %b %Y}"),
            ("Stock", "stock", lambda v, r: f'<b class="sna-mono">{esc(v)}</b>'),
            ("Kind", "kind", lambda v, r: esc(v and v.replace("_", " "))),
            ("Item", "item", None),
            ("For shareholders", "sentiment", sentiment_html),
            ("Rs crore>", "value_cr", lambda v, r: _fmt(v, "{:,.0f}")),
        ],
        empty="No items for this theme in the period.",
    )
    st.html(f'<h3 class="sna-h3">Read-across {AI_TAG}</h3>')
    st.caption(
        "Possible connections, not confirmed contracts. An important order or event "
        "(importance 4-5, or an order of 1% or more of a year's revenue) is listed for the "
        "watchlist stocks that are its approved peers or share its theme."
    )
    html_table(
        load("read_across"),
        [
            ("Date", "date", lambda v, r: f"{v:%d %b %Y}"),
            ("Item", "item", None),
            ("May matter to", "for", lambda v, r: f'<b class="sna-mono">{esc(v)}</b>'),
            ("Why", "why", None),
        ],
        empty="None in the last 90 days.",
    )


def sources_html(lines: list[str]) -> str:
    """The sources under an answer, one per line, each with a link when it has one."""
    items = []
    for line in lines:
        text, _, url = line.rpartition(" http")
        if text and url:
            url = "http" + url
            items.append(
                f"<li>{html.escape(text)} "
                f'<a href="{html.escape(url)}" target="_blank" rel="noopener">open</a></li>'
            )
        else:
            items.append(f"<li>{html.escape(line)}</li>")
    return f'<div class="sna-sources"><b>Sources</b><ol>{"".join(items)}</ol></div>'


def ask_page() -> None:
    from stock_news_analyzer.agents import ask as qa
    from stock_news_analyzer.llm import LLM, LLMError

    page_header(
        "Ask",
        "Questions in plain English, answered from your stocks' filings, results and calls. "
        "The Analyst Q&A looks things up in the database (read-only) and answers with its "
        "sources; each question costs a few cents.",
        "how-ai-is-used",
    )
    with st.form("ask", border=False):
        question = st.text_area(
            "Your question",
            value=st.session_state.pop("ask-prefill", ""),
            placeholder="Which of my companies raised guidance this year?",
        )
        name_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
        save = name_col.text_input(
            "Save as report (optional)", max_chars=64, placeholder="Report name"
        )
        asked = button_col.form_submit_button("Ask", icon=":material/search:", type="primary")
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
                with st.container(border=True, key="card-answer"):
                    st.html(f"{AI_TAG}")
                    st.markdown(answer.text)
                    if answer.sources:
                        st.html(
                            sources_html([qa.describe_source(session, r) for r in answer.sources])
                        )
        section_title("Earlier questions")
        rows = qa.history(session)
        if not rows:
            st.caption("None yet.")
        for r in rows:
            when = f"{r.asked_at.astimezone(IST):%d %b %Y, %H:%M}"
            label = f"{r.question[:110]} · {when}" + (f" · {r.name}" if r.name else "")
            with st.expander(label):
                st.html(AI_TAG)
                st.markdown(r.answer)
                lines = []
                for ref in r.sources:
                    try:
                        lines.append(qa.describe_source(session, ref))
                    except AttributeError:  # the source was deleted since
                        lines.append(f"[{ref}] (no longer stored)")
                if lines:
                    st.html(sources_html(lines))
                st.caption(f"{r.steps} lookups with {r.model}, ${r.cost_usd:.4f}")


def moves_page() -> None:
    page_header(
        "What moves the stock",
        "Average return vs Nifty 50 after each kind of filing, 1, 5 and 20 trading days "
        "later. A BSE and an NSE copy of the same announcement count once.",
        "the-pages",
    )
    s = stock_picker("moves-stock")
    study = load("event_study", isin=s["isin"] if s else None)
    if study.empty:
        no_data("No labelled filings yet: run the **prices** job on System (Run a job now).")
        return
    st.warning(
        "Averages of a handful of events are mostly noise. The number of events behind each "
        "type is shown; the 20-day average uses only events at least 20 trading days old.",
        icon=":material/info:",
    )
    with chart_card("Average return vs Nifty 50 after each kind of filing", "moves"):
        st.plotly_chart(charts.event_study_chart(study, dark()), width="stretch", **PLOT)

    def avg(value, _row) -> str:
        if blank(value):
            return esc(None)
        return f'<span class="{trend(value)}">{signed(value)}</span>'

    html_table(
        study,
        [
            ("Kind of filing", "type", lambda v, r: esc(v and v.replace("_", " "))),
            ("Events>", "events", None),
            ("Avg 1 day>", "avg_1d", avg),
            ("Avg 5 days>", "avg_5d", avg),
            ("Avg 20 days>", "avg_20d", avg),
            ("Events with 20 days>", "n_20d", None),
        ],
    )
    if st.toggle("Show the filings behind each type"):
        lb = load("labels", isin=s["isin"] if s else None)
        reactions_table(lb)


HORIZON_LABELS = {1: "1 day", 5: "5 days", 20: "20 days"}


def short_kind(kind: str) -> str:
    from stock_news_analyzer.agents.study import short_kind as short

    return short(kind)


def range_bar(row: dict, scale: float) -> str:
    """The middle half of the moves as a band and the median as a tick, on ±`scale`."""
    if row["low"] is None or row["median"] is None:
        return esc(None)

    def x(v: float) -> float:
        return 50 + 50 * max(-1.0, min(1.0, v / scale))

    left, right = x(row["low"]), x(row["high"])
    return (
        f'<div class="sna-range" title="Middle half: {signed(row["low"], 1)} to '
        f'{signed(row["high"], 1)}; median {signed(row["median"], 1)}">'
        f'<span class="zero" style="left:50%"></span>'
        f'<span class="band" style="left:{left:.1f}%;width:{max(right - left, 0.5):.1f}%"></span>'
        f'<span class="mid {trend(row["median"])}" style="left:{x(row["median"]):.1f}%"></span>'
        "</div>"
    )


def evidence_page() -> None:
    from stock_news_analyzer.agents import study

    page_header(
        "What news does to prices",
        "For each kind of event, across every stock followed (the Nifty 50 too, once added): "
        "how the stock moved against the market afterwards, how often it rose, and how many "
        "cases that rests on. Evidence for or against a rule of thumb; not a forecast.",
        "what-news-does-to-prices",
    )
    data = load("evidence")
    if not data["cases"]:
        no_data(
            "No events with prices yet. Results, order wins and events build up as the agents "
            "run; uv run sna watchlist nifty50 adds the Nifty 50 for more cases."
        )
        return
    view = (
        st.segmented_control(
            "Group the cases by",
            ["Kind of event", "Size of move"],
            default="Kind of event",
            key="ev-view",
        )
        or "Kind of event"
    )
    c1, c2, c3 = st.columns([1.2, 1.2, 1.6], vertical_alignment="bottom")
    horizon = (
        c1.segmented_control(
            "Over", list(HORIZON_LABELS), default=5, format_func=HORIZON_LABELS.get, key="ev-h"
        )
        or 5
    )
    benchmark = (
        c2.segmented_control(
            "Against", ["Nifty 50", "Sector index"], default="Nifty 50", key="ev-b"
        )
        or "Nifty 50"
    )
    groups = c3.pills(
        "Kinds",
        list(study.GROUPS),
        default=list(study.GROUPS),
        selection_mode="multi",
        key="ev-g",
    )
    cases = [c for c in data["cases"] if c.group in (groups or [])]
    rows = [r.__dict__ for r in study.summarise(cases, horizon, sector=benchmark != "Nifty 50")]
    measured = sum(r["cases"] for r in rows)
    stat_tiles(
        [
            ("Cases", f"{measured:,}", f"with {HORIZON_LABELS[horizon]} of prices since"),
            (
                "Kinds of event",
                str(len(rows)),
                f"{sum(not r['few'] for r in rows)} with {study.FEW}+ cases",
            ),
            ("Stocks", str(len({c.isin for c in cases})), "followed, owned or studied"),
            ("From", f"{min(c.at for c in cases):%b %Y}" if cases else "–", "the oldest case"),
        ]
    )
    with st.expander("How to read this", icon=":material/info:"):
        st.markdown(
            f"""
- **Median move:** half the cases did better than this against the {benchmark}, half worse,
  over the {HORIZON_LABELS[horizon]} from the first close that could reflect the news.
- **Middle half:** the band runs from the 25th to the 75th percentile of the moves, the tick is
  the median, and the line is zero. A band clear of the line is a consistent pattern; one
  across it means the kind of event alone says little.
- **Rose:** how often the stock beat the {benchmark}. About 50% is a coin toss.
- **Few cases:** under {study.FEW}, read the numbers as a hint. They firm up as the Nifty 50's
  history is read and new events come in.
- Cases overlap (results and an event from the same filing) and the market moves for many
  reasons at once: this shows what usually followed, not what caused it. Big news is often
  priced in within minutes, before an end-of-day close.
"""
        )
    if not rows:
        st.caption("No cases for these kinds.")
        return
    owned = data["owned"]
    sector = benchmark != "Nifty 50"
    if view == "Size of move":
        evidence_by_move(cases, horizon, sector, owned)
        return
    scale = max([abs(v) for r in rows for v in (r["low"], r["high"]) if v is not None] + [0.01])
    scale = min(scale, 0.15)

    def median(v, _row):
        if blank(v):
            return esc(None)
        v = v if abs(v) >= 0.0005 else 0.0  # not "−0.0%"
        return f'<span class="{trend(v)}">{signed(v, 1)}</span>'

    def rose(v, row):
        if blank(v):
            return esc(None)
        note = " " + tag("few cases", "warn") if row["few"] else ""
        return f"{v:.0%}{note}"

    for group in study.GROUPS:
        group_rows = [r for r in rows if r["group"] == group]
        if not group_rows:
            continue
        section_title(group)
        html_table(
            group_rows,
            [
                ("Kind of event", "kind", lambda v, r: esc(short_kind(v))),
                ("Cases>", "cases", None),
                ("Median move>", "median", median),
                (f"Middle half (±{scale:.0%} scale)", "median", lambda v, r: range_bar(r, scale)),
                ("Rose>", "up", rose),
            ],
        )

    section_title("The cases behind a kind")
    kinds = [r["kind"] for r in rows]
    kind = st.selectbox("Kind of event", kinds, key="ev-kind")
    picked = sorted((c for c in cases if c.kind == kind), key=lambda c: c.at, reverse=True)
    evidence_cases(picked, owned, sector)


def evidence_cases(cases: list, owned: set[str], sector: bool, with_kind: bool = False) -> None:
    """A list of cases: when, which stock (owned marked), what happened, and the moves."""
    from stock_news_analyzer.agents import study

    def change(v, _row):
        return f'<span class="{trend(v)}">{signed(v, 1)}</span>' if not blank(v) else esc(None)

    columns = [
        ("Date", "when", None),
        ("Stock", "stock", lambda v, r: f'<span class="sna-mono">{esc(v)}</span>'),
    ]
    if with_kind:
        columns.append(("Kind of event", "kind", None))
    columns += [
        ("What", "detail", None),
        ("1 day>", "m1", change),
        ("5 days>", "m5", change),
        ("20 days>", "m20", change),
    ]
    html_table(
        [
            {
                "when": f"{c.at.astimezone(IST):%d %b %Y}",
                "stock": c.symbol + (" (own)" if c.isin in owned else ""),
                "kind": c.kind,
                "detail": c.detail,
                **{f"m{n}": study.move_of(c, n, sector) for n in study.HORIZONS},
            }
            for c in cases
        ],
        columns,
    )


def evidence_by_move(cases: list, horizon: int, sector: bool, owned: set[str]) -> None:
    """The cases by how far the stock moved: for each band of moves, how many cases, which
    kinds of event lay behind them and which stocks, then the cases of a band."""
    from stock_news_analyzer.agents import study

    bands = study.by_move(cases, horizon, sector)
    biggest = max((len(b.cases) for b in bands), default=0) or 1
    st.caption(
        f"Every case put in a band by its move over {HORIZON_LABELS[horizon]}, biggest falls "
        'first. "5 of 15" beside a kind means 5 of its 15 cases moved this much: a kind '
        "spread evenly over the bands says little; one bunched at one end is a pattern."
    )

    def count(v, row):
        width = 90 * v / biggest  # pixels
        colour = "var(--sna-down)" if (row["high"] or 1) <= 0 else "var(--sna-up)"
        return (
            f'<div style="display:flex;align-items:center;gap:.5rem"><span>{v}</span>'
            f'<span style="height:8px;border-radius:4px;width:{width:.0f}px;'
            f'background:{colour};opacity:.7"></span></div>'
        )

    def kinds(v, _row):
        if not v:
            return esc(None)
        return "<br>".join(
            f'{html.escape(k)} <span class="sna-muted">{n} of {total}</span>'
            for k, n, total in v[:6]
        ) + (
            f'<br><span class="sna-muted">and {len(v) - 6} more kinds</span>' if len(v) > 6 else ""
        )

    def stocks(v, _row):
        if not v:
            return esc(None)
        own = {c.symbol for c in cases if c.isin in owned}
        return ", ".join(
            (f"<b>{html.escape(sym)}</b>" if sym in own else html.escape(sym))
            + (f" ×{n}" if n > 1 else "")
            for sym, n in v[:12]
        ) + (f" and {len(v) - 12} more" if len(v) > 12 else "")

    html_table(
        [
            {
                "band": b.label,
                "n": len(b.cases),
                "high": b.high,
                "kinds": b.kinds,
                "stocks": b.stocks,
            }
            for b in bands
        ],
        [
            ("Move", "band", lambda v, r: f'<span class="sna-mono">{esc(v)}</span>'),
            ("Cases", "n", count),
            ("What came before (kind, cases of that kind)", "kinds", kinds),
            ("Stocks (yours in bold)", "stocks", stocks),
        ],
    )
    section_title("The cases in a band")
    filled = [b for b in bands if b.cases]
    if not filled:
        st.caption("No cases with prices over this horizon yet.")
        return
    band = st.selectbox(
        "Move",
        filled,
        index=next((i for i, b in enumerate(filled) if b.low == 0.0), 0),
        format_func=lambda b: f"{b.label} ({len(b.cases)} cases)",
        key="ev-band",
    )
    evidence_cases(band.cases, owned, sector, with_kind=True)


VERDICT_TAG = {
    "In line with the news": "good",
    "Against the news": "warn",
    "Moved without news": "",
    "Quiet": "",
}
ITEM_LABELS = {
    "result": "Results",
    "order": "Order win",
    "event": "Event",
    "flag": "Red flag",
    "deal": "Deal",
}


LEAN_TAG = {"positive": "good", "neutral": "", "negative": "bad"}
EVIDENCE_CLASS = {
    "Filed": "filed",
    "Read by AI": "ai",
    "Market": "",
    "Stale": "stale",
    "Not disclosed": "nd",
    "Not tracked": "nd",
}


def evidence(badge: str) -> str:
    """A small badge saying how far a figure can be trusted (agents/research.py)."""
    return f'<span class="sna-ev {EVIDENCE_CLASS.get(badge, "")}">{html.escape(badge)}</span>'


def amount(value, unit: str) -> str:
    if value is None:
        return '<span class="sna-muted">–</span>'
    if unit == "cr":
        return f"₹{value:,.0f} cr".replace("₹-", "−₹")
    if unit == "x":
        return f"{value:.2f}×"
    if unit == "%":
        return signed(value, 1)
    return f"{value:,.2f}"


def research_page() -> None:
    from stock_news_analyzer.agents import brief as bf
    from stock_news_analyzer.agents import research as rs

    page_header(
        "Research brief",
        "One stock on one page, conclusion first: the view, the key numbers, then a fold for "
        "each part of the research. Every figure says where it came from and how far it can "
        "be trusted.",
        "research-brief",
    )
    s = stock_picker("brief-stock", include_all=False)
    if s is None:
        no_data("No stocks yet. Add them on the Manage stocks page.")
        return
    f = load("research", isin=s["isin"])
    v = f.valuation
    today = datetime.now(IST).date()
    versions = load("briefs", isin=s["isin"])

    # --- the view: write one, or pick a saved one -----------------------------------
    c1, c2 = st.columns([3, 1.3], vertical_alignment="bottom")
    chosen = None
    if versions:
        chosen = c1.selectbox(
            "View",
            versions,
            format_func=lambda b: (
                f"Written {b['created_at'].astimezone(IST):%d %b %Y, %H:%M} by {b['model']}"
                f" · ${b['cost_usd']:.3f}"
            ),
            key=f"brief-version-{s['isin']}",
        )
    else:
        c1.caption(
            "No view written yet. The view is the verdict, stances, what the facts mean, "
            "notes on the peers and the decisions to make, written by the analysis model from "
            "the facts on this page only."
        )
    settings = get_settings()
    if not settings.anthropic_api_key:
        c2.caption("Add an API key on Settings to write the view.")
    elif c2.button(
        "Write a new view" if versions else "Write the view",
        icon=":material/edit_note:",
        type="primary" if not versions else "secondary",
        help=f"One call to {settings.llm_model_analysis}, about $0.03–0.10.",
    ):
        from stock_news_analyzer.llm import LLM, LLMError

        with st.status("Writing the view...", expanded=True) as status:
            try:
                with Session(engine()) as session:
                    written = bf.write(session, LLM(session), s["isin"], progress=status.write)
                status.update(label=f"View written for ${written.cost_usd:.3f}", state="complete")
            except LLMError as exc:
                status.update(label=f"No view: {exc}", state="error")
        load.clear()
        st.rerun()
    view = chosen["view"] if chosen else None
    known = {x[0]: x[1] for x in chosen["facts"]} if chosen else {}
    if chosen:
        now = bf.diff_facts(chosen["facts"], bf.fact_lines(f, today), filed_only=True)
        moved = len(now["changed"]) + len(now["added"]) + len(now["removed"])
        if moved:
            examples = [k for k, _, _ in now["changed"][:3]] + now["added"][:2]
            st.info(
                f"{moved} fact{'s' if moved > 1 else ''} changed since this view was written"
                f" ({'; '.join(e[:60] for e in examples)}). Write a new view to bring it up "
                "to date.",
                icon=":material/update:",
            )

    def cite(ids: list[str]) -> str:
        return " ".join(
            f'<span class="sna-cite" title="{html.escape(known.get(i, ""))}">'
            f"{html.escape(i)}</span>"
            for i in ids
        )

    # --- the lede ------------------------------------------------------------------
    headline, stances = brief_lede(f)
    quarters_with_data = sum(1 for q in f.quarters if q["revenue"] is not None)
    since = f"{f.first_filing.astimezone(IST):%b %Y}" if f.first_filing else "–"
    latest = f.quarters[0] if f.quarters else None
    sub_line = (
        f"Latest quarter ({latest['period']}): revenue {signed(latest['revenue_growth'], 0)} and "
        f"profit {signed(latest['pat_growth'], 0)} on the year; margin "
        f"{latest['margin']:.1%}."
        if latest and latest["margin"] is not None
        else "No quarterly results stored yet."
    )
    if view:
        headline = view["verdict"]
        sub_line = html.escape(view["summary"]) or sub_line
        stance_html = "".join(
            f'<span class="sna-stance {x["label"].lower()}"><b>{html.escape(x["label"])}</b>'
            f"{html.escape(x['text'])}</span>"
            for x in view["stances"]
        )
    else:
        stance_html = "".join(
            f'<span class="sna-stance"><b>{html.escape(k)}</b>{html.escape(t)}</span>'
            for k, t in stances
        )

    def ruled(value: str, label: str, badge: str) -> str:
        return (
            f'<div><div class="v">{value}</div><div class="l">{label}{evidence(badge)}</div></div>'
        )

    debt_equity = next((b for b in f.balance if b.label == "Debt to equity"), None)
    nxt = f.coming[0] if f.coming else None
    stats = "".join(
        [
            ruled(
                f"{v.pe:.1f}" if v.pe else "–",
                "P/E, trailing" + (f" · median {v.pe_median:.0f}" if v.pe_median else ""),
                rs.MARKET if v.pe else rs.NOT_DISCLOSED,
            ),
            ruled(
                signed(v.eps_growth, 0) if v.eps_growth is not None else "–",
                "EPS growth, trailing year",
                rs.FILED if v.eps_growth is not None else rs.NOT_DISCLOSED,
            ),
            ruled(
                f"{debt_equity.value:.2f}×"
                if debt_equity and debt_equity.value is not None
                else "–",
                "Debt to equity",
                debt_equity.badge if debt_equity else rs.NOT_DISCLOSED,
            ),
            ruled(
                f"{nxt.day:%d %b}" if nxt else "–",
                (nxt.what if nxt else "nothing announced"),
                nxt.badge if nxt else rs.NOT_DISCLOSED,
            ),
        ]
    )
    written_note = ""
    if chosen:
        dropped = len(chosen["dropped"])
        written_note = (
            f" The view was written by {esc(chosen['model'])} on "
            f"{chosen['created_at'].astimezone(IST):%d %b %Y} from {len(chosen['facts'])} facts "
            f"(listed under Sources), for ${chosen['cost_usd']:.3f}; every number in it was "
            "checked against them"
            + (
                f", and {dropped} part{'s' if dropped > 1 else ''} with numbers not among them "
                "dropped."
                if dropped
                else "."
            )
        )
    st.html(
        f'<div class="sna-lede"><div class="sna-eyebrow">{esc(f.symbol)} · {esc(f.name)} · NSE'
        f"{' · ' + esc(f.industry) if f.industry else ''} · brief of {today:%d %b %Y}</div>"
        f'<div class="sna-lede-title">{esc(headline)}</div>'
        f'<p class="sna-lede-sub">{sub_line}</p>'
        f'<div class="sna-stances">{stance_html}</div>'
        f'<div class="sna-ruled">{stats}</div>'
        f'<div class="sna-callout">Built from {f.filings:,} filings and {f.news:,} news articles '
        f"since {since}, {quarters_with_data} quarters of results and NSE's daily prices. Each "
        "figure carries its evidence: <b>Filed</b> as filed (XBRL or the exchange), <b>Read by "
        "AI</b> from a filing, <b>Market</b> from prices, <b>Stale</b> older than a half year, "
        f"<b>Not disclosed</b> when the filings don't carry it.{written_note}</div>"
        + (
            f'<div class="sna-callout warn"><b>What changed</b> {esc(view["changed"])}</div>'
            if view and view.get("changed")
            else ""
        )
        + "</div>"
    )

    # --- the folds -----------------------------------------------------------------
    n = iter(range(1, 50))

    def fold(title: str, count: str):
        return st.expander(f"{next(n)}. {title} · {count}")

    if view:
        with fold("The view", f"{len(view['observations'])} points"):
            cards = "".join(
                f'<div class="sna-or"><div><span class="sna-eyebrow">Observed</span>'
                f'<p>{esc(o["observed"])}</p></div><div><span class="sna-eyebrow">Read</span>'
                f'<p>{esc(o["read"])}</p></div><div class="sna-cites">{cite(o["facts"])}</div>'
                "</div>"
                for o in view["observations"]
            )
            subject = view["subject"]
            if subject["why_it_matters"]:
                cards += (
                    f'<div class="sna-callout">Why it matters: {esc(subject["why_it_matters"])}'
                    f"</div>"
                )
            if subject["key_risk"]:
                cards += f'<div class="sna-callout warn">Key risk: {esc(subject["key_risk"])}</div>'
            st.html(cards)

    if chosen:
        older = [b for b in versions if b["created_at"] < chosen["created_at"]]
        if older:
            before = older[0]
            d = bf.diff_facts(before["facts"], chosen["facts"])
            words = bf.diff_views(before["view"], chosen["view"])
            count = len(d["changed"]) + len(d["added"]) + len(d["removed"])
            with fold(
                "What changed",
                f"since {before['created_at'].astimezone(IST):%d %b} · {count} "
                f"fact{'' if count == 1 else 's'}",
            ):
                if words:
                    st.html(
                        '<ul class="sna-check">'
                        + "".join(f"<li>{esc(w)}</li>" for w in words)
                        + "</ul>"
                    )
                if d["changed"]:
                    html_table(
                        [{"k": k, "was": a, "now": b} for k, a, b in d["changed"]],
                        [("Fact", "k", None), ("Was", "was", None), ("Now", "now", None)],
                    )
                for label, items in (("New", d["added"]), ("Gone", d["removed"])):
                    if items:
                        st.html(
                            f'<p><b>{label}</b></p><ul class="sna-check">'
                            + "".join(f"<li>{esc(t)}</li>" for t in items)
                            + "</ul>"
                        )
                if not (words or count):
                    st.caption("Nothing changed.")

    with fold("Valuation", f"P/E {v.pe:.1f}" if v.pe else "no P/E"):
        if v.note:
            st.caption(f"No P/E: {v.note}.")
        if v.series:
            st.plotly_chart(charts.pe_chart(v, dark()), width="stretch", **PLOT)
        rows = [
            ("Close", f"₹{v.close:,.2f} on {v.close_date:%d %b}" if v.close else None, rs.MARKET),
            ("Trailing EPS", f"₹{v.eps_ttm:,.2f}" if v.eps_ttm is not None else None, rs.FILED),
            ("P/E", f"{v.pe:.1f}" if v.pe else None, rs.MARKET),
            (
                f"Its own range, {val_years()} years",
                f"{v.pe_low:.0f} to {v.pe_high:.0f}, median {v.pe_median:.0f}; today higher than "
                f"{v.pe_percentile:.0%} of days"
                if v.pe_median and v.pe_percentile is not None
                else None,
                rs.MARKET,
            ),
            (
                f"{v.sector_index or 'Sector index'} P/E",
                f"{v.sector_pe:.1f} (its median {v.sector_pe_median:.1f})" if v.sector_pe else None,
                rs.MARKET,
            ),
            (
                "Nifty 50 P/E",
                f"{v.nifty_pe:.1f} (its median {v.nifty_pe_median:.1f})" if v.nifty_pe else None,
                rs.MARKET,
            ),
            (
                "Market cap",
                f"₹{v.market_cap_cr:,.0f} cr" if v.market_cap_cr else None,
                rs.MARKET,
            ),
        ]
        brief_kv(rows)
        if v.quarters:
            st.caption(
                "Trailing EPS = "
                + " + ".join(f"{q.eps:.2f} ({q.end:%b %Y})" for q in v.quarters)
                + ", adjusted for any bonus issue or split since."
            )

    def change(x, _row):
        return f'<span class="{trend(x)}">{signed(x, 0)}</span>' if not blank(x) else esc(None)

    with fold("Results", f"{len(f.quarters)} quarters"):
        if not f.quarters:
            st.caption("No quarterly results stored yet.")
        else:
            html_table(
                f.quarters,
                [
                    ("Quarter", "period", lambda x, r: f"{esc(x)}{evidence(r['badge'])}"),
                    ("Revenue>", "revenue", lambda x, r: amount(x, "cr")),
                    ("On the year>", "revenue_growth", change),
                    ("Profit>", "pat", lambda x, r: amount(x, "cr")),
                    ("On the year >", "pat_growth", change),
                    ("Margin>", "margin", lambda x, r: f"{x:.1%}" if not blank(x) else esc(None)),
                    ("EPS>", "eps", lambda x, r: f"₹{x:,.2f}" if not blank(x) else esc(None)),
                ],
            )

    end = f"{f.balance_end:%d %b %Y}" if f.balance_end else "none stored"
    with fold("Balance sheet and cash flow", end):
        if not f.balance:
            st.caption(
                "None stored yet: balance sheets come from the half-yearly and annual XBRL "
                "files, with the xbrl job."
            )
        else:
            html_table(
                [b.__dict__ for b in f.balance],
                [
                    ("Line", "label", None),
                    ("Value>", "value", lambda x, r: amount(x, r["unit"])),
                    ("Evidence", "badge", lambda x, r: evidence(x)),
                    ("From", "note", lambda x, r: f'<span class="sna-muted">{esc(x)}</span>'),
                ],
            )
            if f.balance[0].source:
                st.caption(f"As at {end}, from {f.balance[0].source}")

    ob = f.order_book
    with fold(
        "Order book",
        f"₹{ob['order_book_cr']:,.0f} cr" if ob and ob.get("order_book_cr") else "not reported",
    ):
        if not ob:
            st.caption("The company doesn't report an order book, or none has been read yet.")
        else:
            brief_kv(
                [
                    (
                        "Order book",
                        amount(ob.get("order_book_cr"), "cr")
                        + (f" ({ob['order_book_quarter']})" if ob.get("order_book_quarter") else "")
                        if ob.get("order_book_cr")
                        else None,
                        rs.AI,
                    ),
                    (
                        "Years of revenue",
                        f"{ob['years_of_revenue']:.1f}" if ob.get("years_of_revenue") else None,
                        rs.AI,
                    ),
                    (
                        "Book-to-bill",
                        f"{ob['book_to_bill']:.2f}" if ob.get("book_to_bill") else None,
                        rs.AI,
                    ),
                    (
                        "Orders announced, last 4 quarters on the 4 before",
                        signed(ob["announced_growth"], 0)
                        if ob.get("announced_growth") is not None
                        else None,
                        rs.AI,
                    ),
                    (
                        "Government and PSU share",
                        f"{ob['government_share']:.0%}"
                        if ob.get("government_share") is not None
                        else None,
                        rs.AI,
                    ),
                    ("Largest client, last year", ob.get("top_client"), rs.AI),
                ]
            )

    c = f.credibility
    with fold(
        "Management",
        f"{len(f.management)} changes · "
        + (
            f"promises {c['score']:.0%} kept"
            if c and c.get("score") is not None
            else "no promise score yet"
        ),
    ):
        if c:
            st.html(
                f"<p>Promises: <b>{c['kept']}</b> kept, {c['kept_late']} kept late, "
                f"{c['partly']} partly, <b>{c['missed']}</b> missed, {c['dropped']} dropped, "
                f"{c['overdue']} overdue, {c['to_come']} to come{evidence(rs.AI)}</p>"
            )
        if f.promises:
            html_table(
                f.promises,
                [
                    ("Promise", "metric", lambda x, r: f"{esc(x)}: {esc(r['target'])}"),
                    ("Due", "due", None),
                    (
                        "Status",
                        "status",
                        lambda x, r: tag(x, {"kept": "good", "missed": "bad"}.get(x, "")),
                    ),
                    ("Note", "note", None),
                ],
            )
        if f.management:
            items = "".join(
                f'<li><span class="d">{m["when"]:%d %b %Y}</span><span>{esc(m["headline"])}'
                f"{evidence(rs.AI)}</span></li>"
                for m in f.management
            )
            st.html(f'<ul class="sna-timeline">{items}</ul>')
        if not (c or f.promises or f.management):
            st.caption("No earnings-call promises or management changes stored.")

    with fold("Ownership", f"{len(f.ownership)} quarters"):
        if not f.ownership:
            st.caption("No shareholding patterns stored yet.")
        else:

            def share(x, _row):
                return f"{x:.1%}" if not blank(x) else esc(None)

            html_table(
                f.ownership,
                [
                    ("Quarter", "quarter", lambda x, r: f"{x:%b %Y}{evidence(rs.FILED)}"),
                    ("Promoters>", "promoter", share),
                    ("FIIs>", "fii", share),
                    ("DIIs>", "dii", share),
                    ("Mutual funds>", "mf", share),
                    ("Retail>", "retail", share),
                    ("Pledged>", "pledged", share),
                ],
            )

    basis = {"approved": "your approved peers", "industry": "the largest in its NSE industry"}
    notes = {p["symbol"]: p for p in view["peers"]} if view else {}
    if view:
        notes[f.symbol] = view["subject"]
    with fold("Peers", f"{max(len(f.peers) - 1, 0)} companies"):
        st.caption(
            f"Against {basis.get(f.peer_basis, 'no peers yet')}; set peers on Manage stocks."
        )
        cards = []
        for p in f.peers:
            note = notes.get(p.symbol)
            extra = ""
            if note and note.get("why_it_matters"):
                extra += (
                    f'<p class="sna-note"><b>Why it matters</b> {esc(note["why_it_matters"])}</p>'
                )
            if note and note.get("key_risk"):
                extra += f'<p class="sna-note"><b>Key risk</b> {esc(note["key_risk"])}</p>'
            cards.append(
                f'<div class="sna-ecard{" subject" if p.is_subject else ""}">'
                f'<div class="sna-eyebrow">NSE · {esc(p.symbol)}'
                f"{' · this stock' if p.is_subject else ''}</div>"
                f'<div class="t">{esc(p.name)}</div>{evidence(p.badge)}'
                f'<div class="s"><span><b>{f"{p.pe:.1f}" if p.pe else "–"}</b>P/E</span>'
                f'<span><b class="{trend(p.return_1y)}">{signed(p.return_1y, 0)}</b>1 year</span>'
                f'<span><b class="{trend(p.revenue_growth)}">{signed(p.revenue_growth, 0)}</b>'
                f"revenue{', ' + esc(p.period) if p.period else ''}</span></div>"
                f'<div class="sna-muted" style="font-size:.8rem;margin-top:.4rem">'
                f"{f'₹{p.market_cap_cr:,.0f} cr market cap' if p.market_cap_cr else ''}</div>"
                f"{extra}</div>"
            )
        st.html(f'<div class="sna-cards">{"".join(cards)}</div>')
        buttons = st.columns(min(len(f.peers), 4) or 1)
        for i, p in enumerate(f.peers):
            if buttons[i % len(buttons)].button(
                f"Ask about {p.symbol}", key=f"ask-{f.isin}-{p.symbol}", icon=":material/forum:"
            ):
                st.session_state["ask-prefill"] = (
                    f"What should I know about {p.name} ({p.symbol}) from its filings, results "
                    "and news of the last year"
                    + (
                        "?"
                        if p.is_subject
                        else f", and how does it compare with {f.name} ({f.symbol})?"
                    )
                )
                st.switch_page(PAGES["ask"])

    h = f.lean
    with fold("What moves this stock", f"leans {h.lean}" if h else "no evidence yet"):
        if h is None or not h.reasons:
            st.caption("No results, order wins, events or deals in the last 90 days.")
        else:
            st.html(
                f"<p>{tag('leans ' + h.lean, LEAN_TAG[h.lean])} score {signed(h.score, 1)}; last "
                f'12 weeks <span class="{trend(h.move_12w)}">{signed(h.move_12w, 1)}</span> '
                "against the Nifty 50. See Portfolio and Week by week for how this is worked "
                "out.</p>"
            )
            html_table(
                [
                    {
                        "when": f"{r.case.at.astimezone(IST):%d %b}",
                        "kind": r.case.kind,
                        "median": r.median,
                        "evidence": f"{r.cases} cases" if r.cases else "no cases",
                        "since": r.since,
                    }
                    for r in h.reasons[:6]
                ],
                [
                    ("Date", "when", None),
                    ("Event", "kind", None),
                    ("Usually, 20 days>", "median", change),
                    ("Evidence", "evidence", None),
                    ("Since then>", "since", change),
                ],
            )

    with fold("What's coming", f"{len(f.coming)} dates"):
        if not f.coming:
            st.caption("Nothing announced for the next four months.")
        else:
            items = "".join(
                f'<li><span class="d">{x.day:%a %d %b}</span><span>{esc(x.what)}'
                f"{evidence(x.badge)}</span></li>"
                for x in f.coming
            )
            st.html(f'<ul class="sna-timeline">{items}</ul>')

    with fold("Red flags", f"{len(f.flags)} open"):
        if not f.flags:
            st.caption("No open red flags.")
        for flag in f.flags:
            st.html(
                f'<div class="sna-flag"><span class="sna-dot {flag.severity}"></span>'
                f"{flag.flagged_on:%d %b %Y} · {esc(flag.kind.replace('_', ' '))} · "
                f"{esc(flag.title)}</div>"
            )

    if view:
        with fold("What to watch and decide", f"{len(view['decisions'])} calls"):
            tags = {"Review now": "bad", "Watch": "warn", "Hold steady": "good", "Check": ""}
            cards = "".join(
                f'<div class="sna-ecard"><div>{tag(d["tag"], tags.get(d["tag"], ""))}</div>'
                f'<div class="t">{esc(d["title"])}</div><p class="sna-note">{esc(d["why"])}</p>'
                f'<div class="sna-cites">{cite(d["facts"])}</div></div>'
                for d in view["decisions"]
            )
            checklist = "".join(f"<li>{esc(q)}</li>" for q in view["decide_now"])
            st.html(
                f'<div class="sna-cards">{cards}</div>'
                + (
                    '<div class="sna-callout"><span class="sna-eyebrow">Decisions to make now'
                    f'</span><ul class="sna-check">{checklist}</ul></div>'
                    if checklist
                    else ""
                )
            )
            st.caption("Inputs for your own decisions, not advice.")

        with fold("Sources", f"{len(chosen['facts'])} facts"):
            st.caption(
                "The facts the view was written from, as the model saw them; the ids are the "
                "ones cited above (hover a citation to read its fact)."
            )
            items = "".join(
                f'<li><span class="sna-cite">{esc(i)}</span> {esc(t)}</li>'
                for i, t in chosen["facts"]
            )
            st.html(f'<ul class="sna-sources">{items}</ul>')
            if chosen["dropped"]:
                st.warning(
                    "Dropped because a number in it was not among the facts: "
                    + "; ".join(
                        f"{d['part']} ({', '.join(d['numbers'])})" for d in chosen["dropped"]
                    ),
                    icon=":material/rule:",
                )


def val_years() -> int:
    from stock_news_analyzer.agents import valuation

    return valuation.YEARS


def brief_kv(rows: list[tuple[str, str | None, str]]) -> None:
    from stock_news_analyzer.agents import research as rs

    html_table(
        [{"k": k, "v": v, "b": b if v is not None else rs.NOT_DISCLOSED} for k, v, b in rows],
        [
            ("", "k", lambda x, r: f"<b>{esc(x)}</b>"),
            ("", "v", None),
            ("Evidence", "b", lambda x, r: evidence(x)),
        ],
    )


def brief_lede(f) -> tuple[str, list[tuple[str, str]]]:
    """The brief's headline and stances, from the facts alone (the AI-written view comes on
    top later): what the valuation, the balance sheet and the calendar say."""
    v = f.valuation
    parts, stances = [], []
    if v.pe and v.pe_median:
        side = "below" if v.pe < v.pe_median else "above"
        parts.append(f"P/E {v.pe:.0f}, {side} its {val_years()}-year median of {v.pe_median:.0f}")
        stances.append(
            ("Valuation", f"{side} its own history ({v.pe_percentile:.0%} of days lower)")
        )
    elif v.pe:
        parts.append(f"P/E {v.pe:.0f}")
    de = next((b for b in f.balance if b.label == "Debt to equity"), None)
    net = next((b for b in f.balance if b.label == "Net debt"), None)
    if net and net.value is not None:
        if net.value < 0:
            parts.append("net cash on the balance sheet")
            stances.append(("Balance sheet", "net cash"))
        elif de and de.value is not None:
            parts.append(f"debt {de.value:.1f}× equity")
            word = (
                "leveraged" if de.value > 1 else "moderate debt" if de.value > 0.3 else "low debt"
            )
            stances.append(("Balance sheet", f"{word}, {de.value:.2f}× equity"))
    latest = f.quarters[0] if f.quarters else None
    if latest and latest["pat_growth"] is not None:
        stances.append(("Last quarter", f"profit {signed(latest['pat_growth'], 0)} on the year"))
    if f.coming:
        c = f.coming[0]
        stances.append(("Next", f"{c.what.lower()} {c.day:%d %b}"))
    if f.flags:
        stances.append(("Watch", f"{len(f.flags)} open red flag{'s' if len(f.flags) > 1 else ''}"))
    headline = "; ".join(parts) + "." if parts else f"{f.name}: the facts so far."
    return headline[:1].upper() + headline[1:], stances[:4]


def portfolio_page() -> None:
    from stock_news_analyzer.agents import portfolio as pf
    from stock_news_analyzer.agents import study

    page_header(
        "Portfolio",
        "Each stock you own with a lean (positive, neutral or negative) and the evidence "
        "behind it: its recent events, what such events usually did to prices, and how far "
        "it has moved since. Then your sectors against the Nifty 50's. Inputs for your "
        "decisions, not advice.",
        "portfolio",
    )
    data = load("portfolio")
    held = data["holdings"]
    if not held:
        no_data("No stocks marked as owned. Tick **I own it** on Manage stocks.")
        return
    leans = {k: sum(h.lean == k for h in held) for k in ("positive", "neutral", "negative")}
    stat_tiles(
        [
            ("Stocks owned", str(len(held)), "marked I own it"),
            ("Leaning positive", str(leans["positive"]), "recent events point up"),
            ("Neutral", str(leans["neutral"]), "mixed, or little evidence yet"),
            ("Leaning negative", str(leans["negative"]), "recent events point down"),
        ]
    )
    with st.expander("How the lean is worked out", icon=":material/info:"):
        st.markdown(
            f"""
- Each event of the last **{pf.LOOKBACK} days** (results, order wins, events, red flags,
  deals) counts for what followed events of its kind across every stock followed: the
  median move against the Nifty 50 over **{pf.HORIZON} trading days**, from
  **What news does to prices**.
- **Thin evidence counts less:** a kind with fewer than {study.FEW} cases counts in
  proportion (4 cases: 40%). **Older events count less:** an event's weight halves every
  {pf.HALF_LIFE:.0f} days.
- The weighted medians add up to the **score**. Above +{pf.THRESHOLD:.0%} the lean is
  positive, below −{pf.THRESHOLD:.0%} negative, otherwise neutral. An open high-severity red
  flag keeps a lean from being positive.
- **Since then** is how far the stock has already moved against the Nifty 50 after the
  event. If it already moved as much as such events usually bring, the news may be priced
  in.
- The lean is only as good as the evidence: it firms up as the Nifty 50's history is read.
  It says what usually followed such news, not what will happen, and is not advice.
"""
        )

    def change(v, _row):
        return f'<span class="{trend(v)}">{signed(v, 1)}</span>' if not blank(v) else esc(None)

    for h in held:
        with st.container(border=True, key=f"card-hold-{h.isin}"):
            value = f" · {h.quantity:,.0f} shares, ₹{h.value:,.0f}" if h.value else ""
            close = f"Close ₹{h.close:,.2f}" if h.close is not None else "No price yet"
            weeks = h.weeks
            moved = weeks.get("In line with the news", 0) + weeks.get("Against the news", 0)
            in_line = weeks.get("In line with the news", 0)
            without = weeks.get("Moved without news", 0)
            news_weeks = (
                f"{in_line} of {moved} week{'s' if moved > 1 else ''} that moved with news "
                "went its way"
                if moved
                else "no week moved with news"
            )
            st.html(
                f'<div class="sna-card-head"><div><span class="sna-mono sna-symbol">'
                f'{esc(h.symbol)}</span> <span class="sna-muted">{esc(h.name)}</span></div>'
                f"<div>{tag('leans ' + h.lean, LEAN_TAG[h.lean])} "
                f'<span class="sna-muted">score {signed(h.score, 1)}</span></div></div>'
                f"<p>{close}{value} · last 12 weeks "
                f'<span class="{trend(h.move_12w)}">{signed(h.move_12w, 1)}</span> vs Nifty 50'
                f" · {news_weeks}, {without} moved without news</p>"
            )
            for f in h.flags:
                st.html(
                    f'<div class="sna-flag"><span class="sna-dot {f.severity}"></span>'
                    f"<b>Open red flag</b> · {esc(f.title)}</div>"
                )
            if not h.reasons:
                st.caption(
                    f"No results, order wins, events or deals in the last {pf.LOOKBACK} days: "
                    "nothing to lean on."
                )
                continue
            html_table(
                [
                    {
                        "when": f"{r.case.at.astimezone(IST):%d %b}",
                        "kind": r.case.kind,
                        "detail": r.case.detail,
                        "median": r.median,
                        "evidence": (
                            f"{r.cases} cases, {r.up:.0%} rose" if r.up is not None else "no cases"
                        ),
                        "weight": r.weight,
                        "since": r.since,
                    }
                    for r in h.reasons[:8]
                ],
                [
                    ("Date", "when", None),
                    ("Event", "kind", lambda v, r: esc(v)),
                    ("What happened", "detail", None),
                    (f"Usually, {pf.HORIZON} days>", "median", change),
                    ("Evidence", "evidence", None),
                    ("Weight>", "weight", lambda v, r: f"{v:.0%}"),
                    ("Since then>", "since", change),
                ],
            )

    section_title("Your sectors against the Nifty 50")
    sectors = data["sectors"]
    no_index = all(r["nifty"] is None for r in sectors)
    no_values = all(h.value is None for h in held)
    notes = []
    if no_values:
        notes.append(
            "Without quantities (Manage stocks) and prices for every stock, each counts equally."
        )
    if no_index:
        notes.append("Run uv run sna watchlist nifty50 to compare with the index.")
    else:
        notes.append("The Nifty 50 by market cap (BSE's figures), not NSE's free-float weights.")
    st.caption(" ".join(notes))

    def weight(v, _row):
        if blank(v):
            return esc(None)
        return (
            f'<div style="display:flex;align-items:center;gap:.5rem"><span>{v:.0%}</span>'
            f'<span style="height:8px;border-radius:4px;width:{90 * v:.0f}px;'
            'background:var(--sna-accent-text);opacity:.75"></span></div>'
        )

    def gap(_v, row):
        if row["nifty"] is None:
            return esc(None)
        d = row["mine"] - row["nifty"]
        word = "over" if d > 0.005 else "under" if d < -0.005 else "about even"
        return f"{signed(d, 0).replace('%', ' pts')} {word}" if word != "about even" else word

    html_table(
        sectors,
        [
            ("Industry", "industry", None),
            ("Yours", "mine", weight),
            ("Nifty 50", "nifty", weight),
            ("Difference", "mine", gap),
        ],
    )


def weeks_page() -> None:
    from stock_news_analyzer.agents import weekly

    page_header(
        "Week by week",
        "One stock's last weeks: how it moved against the Nifty 50 and its sector, everything "
        "that came out (results, order wins, events, red flags, deals, news and filings), and "
        "whether the move went the way the news pointed.",
        "week-by-week",
    )
    c1, c2 = st.columns([3, 1.4], vertical_alignment="bottom")
    with c1:
        s = stock_picker("weeks-stock", include_all=False)
    count = (
        c2.segmented_control(
            "Weeks",
            list(weekly.PERIODS),
            default=12,
            format_func=lambda n: f"{n} weeks",
            key="weeks-n",
        )
        or 12
    )
    if s is None:
        no_data("No stocks yet. Add them on the Manage stocks page.")
        return
    ws = load("weeks", isin=s["isin"], count=count)
    priced = [w for w in ws if w.excess is not None]
    if not priced:
        no_data("No prices for this stock in these weeks yet: run the **prices** job on System.")
        return

    def total(field: str) -> float | None:
        values = [getattr(w, field) for w in priced]
        if any(v is None for v in values):
            return None
        out = 1.0
        for v in values:
            out *= 1 + v
        return out - 1

    counts = {v: sum(w.verdict == v for w in priced) for v in weekly.VERDICTS}
    moved = counts["In line with the news"] + counts["Against the news"]
    usual = weekly.usual_move(ws)
    stat_tiles(
        [
            (
                f"{s['symbol']}, {count} weeks",
                f'<span class="{trend(total("stock"))}">{signed(total("stock"), 1)}</span>',
                f"vs Nifty 50 about {signed(sum(w.excess for w in priced), 1)}",
            ),
            (
                "In line with the news",
                f"{counts['In line with the news']}",
                (f"of {moved} week{'s' if moved > 1 else ''} that moved with news")
                if moved
                else "no weeks moved with news",
            ),
            ("Against the news", str(counts["Against the news"]), "moved the other way"),
            (
                "Moved without news",
                str(counts["Moved without news"]),
                f"{counts['Quiet']} quiet weeks (under ±{usual:.1%})",
            ),
        ]
    )
    with st.expander("How to read this", icon=":material/info:"):
        st.markdown(
            f"""
- **A week** runs Monday to Friday. Its move is the stock against the Nifty 50, compounded over
  its trading days. News out after Friday's close counts in the next week, when prices could
  react to it.
- **The news tone** adds up the week: news and events of importance {weekly.NEWS_IMPORTANCE}+
  count +importance if positive and −importance if negative; good results and order wins add,
  weak results and red flags take away. Off-topic and repeated articles don't count.
- **In line / against the news:** the stock moved more than in its usual week ({usual:.1%} for
  {s["symbol"]} over these weeks) and went the way the tone pointed, or the other way.
  **Moved without news:** a bigger move with nothing either way, often the market or the
  sector; compare its move against the sector. **Quiet:** a smaller move than usual.
- Mostly in line means the stock trades on its news. Often against or without news means
  something else drives it, or the news was expected.
"""
        )
    with chart_card(f"{s['symbol']} against the Nifty 50, week by week", "weeks"):
        st.plotly_chart(charts.weekly_chart(ws, dark()), width="stretch", **PLOT)

    section_title("The weeks, newest first")
    for n, w in enumerate(ws):
        move = "no prices" if w.excess is None else f"{signed(w.excess, 1)} vs Nifty 50"
        label = f"{w.start:%d %b} – {w.end:%d %b %Y}  ·  {move}  ·  {w.verdict}"
        notable = w.verdict != "Quiet" or any(i.kind not in ("news", "filing") for i in w.items)
        with st.expander(label, expanded=n < 4 and notable):
            week_detail(w)


def week_detail(w) -> None:
    """One week: its move, unusual days, what happened, the news and the filings."""
    parts = []
    if w.excess is not None:
        sector = (
            f' · vs sector <span class="{trend(w.sector_excess)}">'
            f"{signed(w.sector_excess, 1)}</span>"
            if w.sector_excess is not None
            else ""
        )
        close = f" · close ₹{w.close:,.2f}" if w.close is not None else ""
        parts.append(
            f'<p>Stock <span class="{trend(w.stock)}">{signed(w.stock, 1)}</span> · vs Nifty 50 '
            f'<span class="{trend(w.excess)}">{signed(w.excess, 1)}</span>{sector}{close} · '
            f"{w.days} trading days · news tone {w.tone:+d} · "
            f"{tag(w.verdict, VERDICT_TAG[w.verdict])}</p>"
        )
    for u in w.unusual:
        cause = f": {html.escape(u['cause'].replace('_', ' '))}" if u["cause"] else ""
        why = f" {AI_TAG} {html.escape(u['explanation'])}" if u["explanation"] else ""
        parts.append(
            f"<p>Unusual day {u['date']:%a %d %b}, "
            f'<span class="{trend(u["excess"])}">{signed(u["excess"], 1)}</span> vs Nifty'
            f"{cause}.{why}</p>"
        )

    def line(i) -> str:
        sign = f' <span class="sna-dot {"good" if i.tone > 0 else "bad"}"></span>' if i.tone else ""
        when = f'<span class="sna-muted">{i.at.astimezone(IST):%a %d %b}</span>'
        title = html.escape(i.title)
        if i.url:
            title = f'<a href="{html.escape(i.url)}" target="_blank">{title}</a>'
        extra = f' <span class="sna-muted">· {html.escape(i.detail)}</span>' if i.detail else ""
        return f"<li>{when} {title}{extra}{sign}</li>"

    happened = [i for i in w.items if i.kind in ITEM_LABELS]
    if happened:
        parts.append("<b>What happened</b><ul>")
        parts += [
            line(i).replace("<li>", f"<li><b>{ITEM_LABELS[i.kind]}:</b> ", 1) for i in happened
        ]
        parts.append("</ul>")
    news = w.of("news")
    if news:
        parts.append(f"<b>News ({len(news)})</b><ul>")
        parts += [line(i) for i in news[:8]]
        if len(news) > 8:
            parts.append(f'<li class="sna-muted">and {len(news) - 8} less important</li>')
        parts.append("</ul>")
    filings = w.of("filing")
    if filings:
        parts.append(f"<b>Filings ({len(filings)})</b><ul>")
        parts += [line(i) for i in filings[:10]]
        if len(filings) > 10:
            parts.append(f'<li class="sna-muted">and {len(filings) - 10} more</li>')
        parts.append("</ul>")
    if not (happened or news or filings):
        parts.append('<p class="sna-muted">Nothing came out about the stock this week.</p>')
    st.html('<div class="sna-week">' + "".join(parts) + "</div>")


def manage_page() -> None:
    page_header(
        "Manage stocks",
        "Add, edit and remove your stocks. Changes take effect straight away: the scheduler "
        "picks up new stocks on its next run. Load a new stock's history with the button that "
        "appears after adding it.",
        "getting-started",
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
            "the **securities** job on System (Run a job now).",
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
        column_order=[
            "symbol",
            "name",
            "owned",
            "study_only",
            "sector_index",
            "aliases",
            "peers",
            "remove",
        ],
        column_config={
            "symbol": st.column_config.TextColumn("Symbol", width="small"),
            "name": st.column_config.TextColumn("Company"),
            "owned": st.column_config.CheckboxColumn("I own it", width="small"),
            "study_only": st.column_config.CheckboxColumn(
                "Study only",
                help="Followed for the evidence (the Nifty 50): collected and read by the cheap "
                "agents, but no earnings calls, promises or move explanations, and no card on "
                "Today. Untick to follow it fully.",
            ),
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


SEVERITY = {"high": "● high", "medium": "● medium", "low": "● low"}


def flags_page() -> None:
    from stock_news_analyzer.agents import redflags

    page_header(
        "Red flags",
        "Warnings about governance and money: an auditor or CFO leaving, a rating cut, a "
        "pledge, promoters selling, a penalty, results filed late. Dismiss one once you have "
        "looked into it; it stays on record with your note.",
        "words-used",
    )
    c1, c2, c3, c4 = st.columns([1.4, 1, 1.4, 1], vertical_alignment="bottom")
    severities = c1.pills(
        "Severity",
        list(SEVERITY),
        default=["high", "medium"],
        selection_mode="multi",
        format_func={
            "high": ":red[●] high",
            "medium": ":orange[●] medium",
            "low": ":gray[●] low",
        }.get,
    )
    days = c2.selectbox(
        "Raised in the last",
        [30, 90, 365, 3 * 365],
        index=2,
        format_func=lambda d: f"{d} days" if d < 365 else f"{d // 365} year{'s' * (d > 365)}",
    )
    dismissed = c4.toggle("Show dismissed")
    flags = load(
        "flag_table", days=days, severities=tuple(severities or []), include_dismissed=dismissed
    )
    symbols = sorted(flags["symbol"].unique())
    pick = c3.multiselect("Stocks", symbols, placeholder="All stocks")
    if pick:
        flags = flags[flags["symbol"].isin(pick)]
    if flags.empty:
        no_data("No red flags for these choices.")
        return
    open_count = int((flags["status"] == "open").sum())
    st.caption(f"{len(flags)} flags · {open_count} open")
    colours = PALETTE["dark" if dark() else "light"]
    shown = flags.drop(columns=["id"]).assign(
        severity=flags["severity"].map(SEVERITY),
        note=flags["note"].fillna(""),
        link=flags["link"].fillna(""),
    )
    styled = shown.style.map(
        lambda v: f"color:{colours[v.split()[-1]]}" if isinstance(v, str) else "",
        subset=["severity"],
    ).map(lambda v: f"color:{colours['muted']}" if v == "dismissed" else "", subset=["status"])
    selection = st.dataframe(
        styled,
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
    with st.container(border=True, key="card-flag-chosen"):
        st.html(
            f'<div class="sna-flag"><span class="sna-dot {flag["severity"]}"></span>'
            f'<span class="sna-muted sna-flag-date">{flag["date"]:%d %b}</span>'
            f'<span class="sna-{flag["severity"]} sna-flag-kind">{html.escape(flag["kind"])}'
            f'</span><span><b class="sna-mono">{html.escape(flag["symbol"])}</b>: '
            f"{html.escape(flag['title'])}</span></div>"
        )
        with Session(engine()) as session:
            if flag["status"] == "open":
                with st.form("dismiss", clear_on_submit=True, border=False):
                    note_col, button_col = st.columns([4, 1], vertical_alignment="bottom")
                    note = note_col.text_input(
                        "Note (optional)", placeholder="e.g. a planned retirement; successor named"
                    )
                    if button_col.form_submit_button("Dismiss", icon=":material/done:"):
                        redflags.dismiss(session, int(flag["id"]), note.strip() or None)
                        load.clear()
                        st.rerun()
            else:
                if flag["note"]:
                    st.caption(f"Your note: {flag['note']}")
                if st.button("Open it again", icon=":material/undo:"):
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


def agents_page() -> None:
    page_header(
        "Agent map",
        "How an agentic system works, shown on this one: the collectors perceive, the "
        "scheduler plans, the AI agents think, the database remembers, tools act, and "
        "guardrails and the run log watch over all of it. Watch today's action live, or replay "
        "how information moved through it over the last seven days.",
        "keeping-it-running",
    )
    mode = st.segmented_control(
        "Show",
        ["Today, live", "Replay the last 7 days"],
        default="Today, live",
        label_visibility="collapsed",
        key="agent-map-mode",
    )
    if mode != "Replay the last 7 days":
        catch_up_section("catch-up-map")
    if mode == "Replay the last 7 days":
        with Session(engine()) as session:
            status = queries.agent_status(session)
            events = queries.agent_events(session, days=7)
        st.iframe(
            agent_map.render(status, theme_palette(), dark(), events, mode="replay"),
            height="content",
        )
        st.caption(
            f"{len(events)} runs and questions from the run log and the AI call log. Play "
            "starts at the beginning; drag the slider to jump to a time."
        )
    else:
        live_agent_map()


def _pct(value) -> str:
    return "–" if value is None else f"{value:.0%}"


def evals_page() -> None:
    page_header(
        "Agent evals",
        "How well each AI agent does its job, measured on fixed cases whose answers you have "
        "checked: the share it gets fully right, how many cases pass and fail, and how that "
        "changes run by run. Agents without an eval yet show how they could be measured.",
        "agent-evals",
    )
    with Session(engine()) as session:
        overview = queries.eval_overview(session)
    measured = {job: o for job, o in overview.items() if o["current"]}
    current = [o["current"] for o in measured.values()]
    cols = st.columns(4)
    cols[0].metric("Agents with an eval", f"{len(measured)} of {len(agent_map.THINKERS)}")
    cols[1].metric("Cases passing", sum(r.get("passed", 0) for r in current))
    cols[2].metric("Cases failing", sum(r.get("failed", 0) for r in current))
    last = max((r["finished_at"] for r in current), default=None)
    cols[3].metric("Last run", f"{last.astimezone(IST):%d %b, %H:%M}" if last else "–")

    st.subheader("The agents")
    grid = st.columns(3)
    agents = sorted(agent_map.THINKERS, key=lambda a: a[0] not in measured)  # measured first
    for i, (job, name, model, _) in enumerate(agents):
        with grid[i % 3].container(border=True):
            o = overview.get(job)
            run = o["current"] if o else None
            st.markdown(f"**{name}**  \n:gray[{model}]")
            if run is None:
                st.markdown(
                    ":gray-badge[No eval yet]"
                    if job not in queries.EVAL_FLOWS
                    else ":orange-badge[Eval not run yet]"
                )
                st.caption(queries.EVAL_PLANS.get(job, "Cases and checked answers to come."))
                continue
            before = o["previous"]
            delta = (
                f"{100 * (run.get('correct', 0) - before.get('correct', 0)):+.0f} pts"
                if before
                else None
            )
            st.metric(
                "Fully correct",
                f"{run.get('correct', 0):.0%}",
                delta,
                help=f"±{run.get('margin', 0):.0%} at 95%: a change smaller than this may be "
                "chance.",
            )
            total = run.get("passed", 0) + run.get("failed", 0)
            st.progress(run.get("passed", 0) / total if total else 0.0)
            st.caption(
                f"{run.get('passed', 0)} of {total} cases pass every run · "
                f"recall {_pct(run.get('recall'))}, precision {_pct(run.get('precision'))}, "
                f"specificity {_pct(run.get('specificity'))}"
            )
            if run["cases_verified"] < run["cases"]:
                st.markdown(
                    f":orange-badge[{run['cases'] - run['cases_verified']} answers not checked]"
                )
            if run["errors"]:
                calls = "call" if run["errors"] == 1 else "calls"
                st.markdown(f":red-badge[{run['errors']} failed {calls}]")

    if not measured:
        st.info(
            "No eval has run yet. The Event Extractor's is ready: `uv run sna eval events "
            "sample`, then `draft`, check the answers, and `run` (the Guide has the steps)."
        )
        return

    st.subheader("Look closer")
    names = {job: name for job, name, _, _ in agent_map.THINKERS}
    job = st.selectbox(
        "Agent", list(measured), format_func=lambda j: names.get(j, j), key="evals-agent"
    )
    o = measured[job]
    st.plotly_chart(charts.eval_history_chart(o["runs"], dark()), width="stretch", **PLOT)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Variant": r["variant"],
                    "Model": r["model"],
                    "Prompt": r["prompt_version"],
                    "Run": r["finished_at"].astimezone(IST),
                    "Correct": r.get("correct"),
                    "±": r.get("margin"),
                    "Passing": r.get("passed"),
                    "Failing": r.get("failed"),
                    "Detect": r.get("detect"),
                    "Types F1": r.get("types"),
                    "Amounts": r.get("amounts"),
                    "Quotes found": r.get("quotes"),
                    "Cost": r["cost_usd"],
                }
                for r in o["latest"].values()
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Run": st.column_config.DatetimeColumn(format="D MMM, HH:mm"),
            **{
                k: st.column_config.NumberColumn(format="percent")
                for k in ("Correct", "±", "Detect", "Types F1", "Amounts", "Quotes found")
            },
            "Cost": st.column_config.NumberColumn(format="$%.4f"),
        },
    )
    variant = st.segmented_control(
        "Cases of", list(o["latest"]), default=next(iter(o["latest"])), key="evals-variant"
    ) or next(iter(o["latest"]))
    run = o["latest"][variant]
    with Session(engine()) as session:
        cases = queries.eval_cases(session, run["id"])
    failing = [c for c in cases if not c["passing"]]
    only = st.toggle(f"Only the {len(failing)} failing cases", value=bool(failing))
    shown = failing if only else cases
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Case": c["case"],
                    "Filing": c["title"],
                    "Kind": ", ".join(c["tags"]),
                    "Right": f"{c['right']} of {c['runs']}",
                    "Detect": c.get("detect"),
                    "Types F1": c.get("types"),
                    "Amounts": c.get("amounts"),
                    "Quotes found": c.get("quotes"),
                    "Failed calls": len(c["errors"]),
                }
                for c in shown
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            k: st.column_config.NumberColumn(format="percent")
            for k in ("Detect", "Types F1", "Amounts", "Quotes found")
        },
    )
    for c in failing[:12]:
        with st.expander(f"{c['case']}: {c['title']} ({c['right']} of {c['runs']} right)"):
            detail = c["detail"] or {}
            left, right = st.columns(2)
            left.markdown("**Expected**")
            right.markdown("**Found (a wrong run)**")
            for col, key in ((left, "expected_events"), (right, "found_events")):
                events = detail.get(key) or []
                if not events:
                    col.caption("No event.")
                for e in events:
                    value = f" · Rs {e['value_cr']:,g} crore" if e.get("value_cr") else ""
                    col.markdown(f"- `{e['event_type']}`{value}  \n  {e.get('headline', '')}")
            for err in c["errors"]:
                st.caption(f"Failed call: {err}")
    st.caption(
        f"Run with `uv run sna eval {o['flow']} run`; a variant: `--variant v1 --model ...`. "
        "Results and transcripts are also in `.claude/hillclimb/" + o["flow"] + "/`."
    )


def theme_palette() -> dict[str, str]:
    return PALETTE["dark" if dark() else "light"]


@st.fragment(run_every=30)
def live_agent_map() -> None:
    with Session(engine()) as session:
        status = queries.agent_status(session)
        events = queries.agent_events(session, days=1)
    st.iframe(
        agent_map.render(status, theme_palette(), dark(), events, mode="live"), height="content"
    )
    st.caption(f"As of {status['now']:%d %b %Y, %H:%M:%S} IST; refreshed every 30 seconds.")


def catch_up_section(key: str) -> None:
    """Jobs that missed a scheduled run (the computer asleep, Docker stopped), and a button
    that runs them all now, in the scheduler's order, each from where it last stopped."""
    from stock_news_analyzer.agents import orchestrator as orch

    with Session(engine()) as session:
        try:
            missed = orch.missed_runs(session)
        except (OSError, ValueError):
            return
    if not missed:
        st.caption("Every scheduled job ran on time; nothing to catch up.")
        return
    names = ", ".join(f"{job} ({when:%a %d %b %H:%M})" for job, when in missed.items())
    left, right = st.columns([4, 1], vertical_alignment="center")
    left.warning(
        f"{len(missed)} job{'s' * (len(missed) != 1)} missed a scheduled run: {names}. "
        "Catch up runs them now; each picks up from where it last stopped.",
        icon=":material/schedule:",
    )
    if right.button("Catch up", type="primary", icon=":material/fast_forward:", key=key):
        with st.status("Catching up...", expanded=True) as box:
            st.caption("This can take several minutes; keep this tab open until it finishes.")
            with Session(engine()) as session, _StatusLog(box):
                done = orch.catch_up(session, progress=box.write)
            failed = [name for name, run in done if run.status != "ok"]
            box.update(
                label=f"Caught up {len(done)} job{'s' * (len(done) != 1)}"
                + (f"; {', '.join(failed)} failed" if failed else ""),
                state="error" if failed else "complete",
                expanded=bool(failed),
            )
        load.clear()


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
    page_header(
        "System",
        "Whether the scheduled jobs ran, what is stored, and this month's AI spend. The "
        "schedule is in config/schedule.yaml.",
        "keeping-it-running",
    )
    run_now_section()
    section_title("Catch up missed runs")
    catch_up_section("catch-up-system")
    left, right = st.columns(2)
    with left:
        section_title("Schedule (India time)")
        try:
            from stock_news_analyzer.settings_store import paused_jobs

            schedule = load_schedule(SCHEDULE_FILE)
            upcoming = next_runs(schedule, datetime.now(IST))
            off = paused_jobs(get_settings())
            html_table(
                [
                    {
                        "job": j.name,
                        "next": "off on Settings"
                        if j.name in off
                        else upcoming[j.name].strftime("%a %d %b, %H:%M")
                        if j.enabled
                        else "paused",
                    }
                    for j in schedule
                ],
                [
                    ("Job", "job", lambda v, r: f'<span class="sna-mono">{esc(v)}</span>'),
                    (
                        "Next run",
                        "next",
                        lambda v, r: (
                            f'<span class="sna-muted">{esc(v)}</span>'
                            if v in ("off on Settings", "paused")
                            else esc(v)
                        ),
                    ),
                ],
            )
        except (OSError, ValueError) as exc:
            st.error(f"Could not read {SCHEDULE_FILE}: {exc}")
    with right:
        section_title("Stored data")
        counts = load("data_counts")
        html_table(
            [{"what": k, "count": v} for k, v in counts.items()],
            [
                ("Data", "what", lambda v, r: esc(v[:1].upper() + v[1:])),
                (
                    "Count>",
                    "count",
                    lambda v, r: f"{v:,}" if isinstance(v, int) else esc(v),
                ),
            ],
        )
    section_title("AI usage")
    usage = load("llm_usage")
    spent, budget = usage["spent"], usage["budget"]
    stat_tiles(
        [
            (f"Spent in {usage['month']}", f"${spent:.2f}", ""),
            ("Monthly budget", f"${budget:.2f}", "Set on Settings; AI calls stop when reached"),
            ("Articles waiting for triage", f"{usage['pending_triage']:,}", ""),
        ]
    )
    st.progress(
        min(1.0, spent / budget) if budget else 1.0,
        text=f"{spent / budget:.0%} of the monthly budget used" if budget else "No budget set",
    )
    html_table(
        usage["by_task"],
        [
            ("Task", "task", None),
            ("Model", "model", None),
            ("Calls>", "calls", None),
            ("Failed>", "failed", lambda v, r: f'<span class="sna-down">{v}</span>' if v else "0"),
            ("Input tokens>", "input tokens", lambda v, r: f"{v:,}"),
            ("Output tokens>", "output tokens", lambda v, r: f"{v:,}"),
            ("Cost>", "cost $", lambda v, r: f"${v:.4f}"),
        ],
        empty="No AI calls this month yet.",
    )
    section_title("Recent runs")
    runs = load("runs", limit=200)
    if runs.empty:
        no_data("No runs yet. The scheduler runs the jobs each day; or run one above.")
    else:
        only_errors = st.toggle("Only errors")
        if only_errors:
            runs = runs[runs["status"] != "ok"]
        colours = PALETTE["dark" if dark() else "light"]
        st.dataframe(
            runs.style.map(
                lambda v: f"color:{colours['up'] if v == 'ok' else colours['high']}",
                subset=["status"],
            ),
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

    page_header(
        "Settings",
        "The AI key and budget, the unusual-day threshold, and which scheduled jobs run. "
        "Saved here, a setting takes the place of the same one in .env; the scheduler picks "
        "changes up within a minute.",
        "settings",
    )
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

        section_title("Where each setting comes from")
        html_table(
            [
                {"setting": label, "from": store.source(session, k)}
                for k, label in SETTING_NAMES.items()
            ],
            [
                ("Setting", "setting", None),
                (
                    "Source",
                    "from",
                    lambda v, r: (
                        f'<span class="sna-muted">{esc(v)}</span>' if v == "default" else esc(v)
                    ),
                ),
            ],
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
        "Add the stocks you own and the ones you follow. **Stocks I own** come first on "
        "**Today** and in the digest. You can change the list any time on **Manage stocks**."
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
            "The scheduler keeps it up to date every morning: it starts with the system when you "
            "use the start script (or `make scheduler`). Each new day's filings, news and prices "
            "then arrive on their own.",
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
    "portfolio": st.Page(
        portfolio_page, title="Portfolio", icon=":material/work:", url_path="portfolio"
    ),
    "stock": stock_page,
    "filings": st.Page(
        filings_page, title="Filings", icon=":material/description:", url_path="filings"
    ),
    "news": st.Page(news_page, title="News", icon=":material/newspaper:", url_path="news"),
    "themes": st.Page(themes_page, title="Themes", icon=":material/hub:", url_path="themes"),
    "ask": st.Page(ask_page, title="Ask", icon=":material/question_answer:", url_path="ask"),
    "research": st.Page(
        research_page, title="Research brief", icon=":material/description:", url_path="research"
    ),
    "weeks": st.Page(
        weeks_page, title="Week by week", icon=":material/calendar_view_week:", url_path="weeks"
    ),
    "evidence": st.Page(
        evidence_page,
        title="What news does to prices",
        icon=":material/balance:",
        url_path="evidence",
    ),
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
    "agents": st.Page(
        agents_page, title="Agent map", icon=":material/account_tree:", url_path="agents"
    ),
    "evals": st.Page(evals_page, title="Agent evals", icon=":material/rule:", url_path="evals"),
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
    "Today": ["today", "portfolio", "flags", "agents", "evals"],
    "Research": ["research", "stock", "weeks", "ask", "themes", "moves", "evidence"],
    "Library": ["filings", "news"],
    "Set up": ["manage", "settings", "system"],
    "Help": ["guide"],
}


def main() -> None:
    apply_style()
    if setup_needed():
        st.navigation([SETUP_PAGE, PAGES["guide"]]).run()
        return
    with st.sidebar:
        if st.button("Refresh data", icon=":material/refresh:"):
            load.clear()
        st.caption("Collecting happens in the scheduler; add stocks on Manage stocks.")
        st.page_link(PAGES["guide"], label="New here? Read the Guide", icon=":material/help:")
    st.navigation(
        {group: [PAGES[k] for k in keys] for group, keys in NAV.items()}, expanded=True
    ).run()


if __name__ == "__main__":  # `streamlit run` runs this file as __main__
    main()
