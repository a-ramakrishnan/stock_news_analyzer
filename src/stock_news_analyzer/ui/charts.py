"""Plotly figures for the dashboard.

One colour job each: the stock is blue, its sector index orange, the Nifty 50 gray (the
baseline everything is measured against). Bars that can be up or down use blue for up and red
for down. Every chart has one y-axis; the price chart indexes all three lines to 100 instead of
mixing price scales.
"""

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


@dataclass(frozen=True)
class Theme:
    stock: str
    sector: str
    nifty: str
    up: str
    down: str
    text: str
    muted: str
    grid: str
    baseline: str
    surface: str


LIGHT = Theme(
    stock="#2a78d6",
    sector="#eb6834",
    nifty="#898781",
    up="#2a78d6",
    down="#e34948",
    text="#0b0b0b",
    muted="#52514e",
    grid="#e1e0d9",
    baseline="#c3c2b7",
    surface="#fcfcfb",
)
DARK = Theme(
    stock="#3987e5",
    sector="#d95926",
    nifty="#898781",
    up="#3987e5",
    down="#e66767",
    text="#f0efec",
    muted="#c3c2b7",
    grid="#2c2c2a",
    baseline="#383835",
    surface="#1a1a19",
)


# No trading on weekends: leave them out of date axes instead of drawing flat gaps.
WEEKENDS = [dict(bounds=["sat", "mon"])]


def theme(dark: bool) -> Theme:
    return DARK if dark else LIGHT


def _layout(fig: go.Figure, t: Theme, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=32, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t.text, size=13),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(color=t.muted)
        ),
        hoverlabel=dict(bgcolor=t.surface, bordercolor=t.baseline, font=dict(color=t.text)),
    )
    fig.update_xaxes(
        showgrid=False, automargin=True, linecolor=t.baseline, tickfont=dict(color=t.muted)
    )
    fig.update_yaxes(
        gridcolor=t.grid,
        automargin=True,
        zeroline=False,
        linecolor=t.baseline,
        tickfont=dict(color=t.muted),
    )
    return fig


def performance_chart(
    perf: pd.DataFrame,
    symbol: str,
    sector: str | None,
    events: pd.DataFrame | None = None,
    dark: bool = False,
) -> go.Figure:
    """Stock vs sector vs Nifty 50, indexed to 100; filings and unusual days marked on the line.

    `events` has columns day0, type, title (one row per filing to mark).
    """
    t = theme(dark)
    fig = go.Figure()
    if perf.empty:
        return _layout(fig, t, 420)
    lines = [("nifty", "Nifty 50", t.nifty, 1.5), ("stock", symbol, t.stock, 2.5)]
    if sector and perf["sector"].notna().any():
        lines.insert(1, ("sector", sector, t.sector, 1.5))
    for col, name, color, width in lines:
        fig.add_trace(
            go.Scatter(
                x=perf["date"],
                y=perf[col],
                name=name,
                mode="lines",
                line=dict(color=color, width=width),
                hovertemplate=f"{name}: %{{y:.1f}}<extra></extra>",
            )
        )
    level = perf.set_index("date")["stock"]

    unusual = perf[perf["unusual"]]
    if not unusual.empty:
        fig.add_trace(
            go.Scatter(
                x=unusual["date"],
                y=unusual["stock"],
                name="Unusual day",
                mode="markers",
                marker=dict(size=11, color="rgba(0,0,0,0)", line=dict(color=t.down, width=2)),
                customdata=unusual[["excess", "zscore"]].to_numpy(),
                hovertemplate="Unusual: %{customdata[0]:+.2%} vs Nifty "
                "(z %{customdata[1]:.1f})<extra></extra>",
            )
        )
    if events is not None and not events.empty:
        ev = events[events["day0"].isin(level.index)]
        if not ev.empty:
            fig.add_trace(
                go.Scatter(
                    x=ev["day0"],
                    y=[level[d] for d in ev["day0"]],
                    name="Filing",
                    mode="markers",
                    marker=dict(
                        size=9, color=t.stock, symbol="diamond", line=dict(color=t.surface, width=2)
                    ),
                    customdata=ev[["type", "title"]].to_numpy(),
                    hovertemplate="%{customdata[0]}: %{customdata[1]}<extra></extra>",
                )
            )
    fig.add_hline(y=100, line=dict(color=t.baseline, width=1))
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(rangebreaks=WEEKENDS)
    fig.update_yaxes(title=dict(text="Indexed to 100", font=dict(color=t.muted)))
    return _layout(fig, t, 420)


def excess_bars(perf: pd.DataFrame, threshold_note: str = "", dark: bool = False) -> go.Figure:
    """Daily return minus the Nifty 50's; unusual days drawn solid, the rest faded."""
    t = theme(dark)
    fig = go.Figure()
    if perf.empty:
        return _layout(fig, t, 220)
    excess = perf["excess"].astype(float)
    colors = [t.up if (x or 0) >= 0 else t.down for x in excess]
    opacity = [1.0 if u else 0.45 for u in perf["unusual"]]
    fig.add_trace(
        go.Bar(
            x=perf["date"],
            y=excess,
            marker=dict(color=colors, opacity=opacity),
            customdata=perf[["zscore"]].to_numpy(),
            name="vs Nifty 50",
            hovertemplate="%{x|%d %b %Y}: %{y:+.2%} vs Nifty (z %{customdata[0]:.1f})"
            "<extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=t.baseline, width=1))
    fig.update_layout(showlegend=False, bargap=0.15)
    fig.update_xaxes(rangebreaks=WEEKENDS)
    fig.update_yaxes(tickformat="+.0%", title=dict(text=threshold_note, font=dict(color=t.muted)))
    return _layout(fig, t, 220)


HORIZONS = (("avg_1d", "1 day"), ("avg_5d", "5 days"), ("avg_20d", "20 days"))


def event_study_chart(study: pd.DataFrame, dark: bool = False) -> go.Figure:
    """Average return vs Nifty 50 after each filing type: one panel per horizon, same rows."""
    t = theme(dark)
    if study.empty:
        return _layout(go.Figure(), t, 200)
    study = study.sort_values("events")
    labels = [f"{r.type} ({r.events})" for r in study.itertuples()]
    fig = make_subplots(
        rows=1,
        cols=3,
        shared_yaxes=True,
        horizontal_spacing=0.06,
        subplot_titles=[name for _, name in HORIZONS],
    )
    for i, (col, name) in enumerate(HORIZONS, start=1):
        values = study[col].astype(float)
        n = study["events"] if col != "avg_20d" else study["n_20d"]
        fig.add_trace(
            go.Bar(
                y=labels,
                x=values,
                orientation="h",
                marker=dict(color=[t.up if (v or 0) >= 0 else t.down for v in values.fillna(0)]),
                customdata=n.to_numpy(),
                hovertemplate=f"%{{y}}<br>{name}: %{{x:+.2%}} (n=%{{customdata}})<extra></extra>",
            ),
            row=1,
            col=i,
        )
        fig.add_vline(x=0, line=dict(color=t.baseline, width=1), row=1, col=i)
    fig.update_layout(showlegend=False, bargap=0.3)
    # One symmetric scale for all three panels, so bar lengths compare across horizons.
    reach = study[[c for c, _ in HORIZONS]].abs().max().max()
    reach = 1.15 * reach if pd.notna(reach) and reach > 0 else 0.01
    fig.update_xaxes(tickformat="+.1%", range=[-reach, reach], nticks=5)
    fig.update_annotations(font=dict(color=t.muted, size=13))
    return _layout(fig, t, max(220, 34 * len(study) + 80))
