"""The Agent map: the whole system laid out as an agent's anatomy (perceive, plan, think,
remember, act, guardrails, observe) with each part's live state, from `queries.agent_status`.

`render` returns a complete HTML page, shown in an iframe by the dashboard (the iframe keeps its
own styles, and inline SVG would be dropped by `st.html`).
"""

import html
from datetime import datetime
from pathlib import Path
from string import Template

CSS = Path(__file__).with_name("agent_map.css")

# (job, name, what it does): the collectors, which use no AI.
COLLECTORS = [
    ("filings", "Filings", "BSE + NSE announcements, every 30 min"),
    ("news", "News", "feeds and Google News, hourly"),
    ("prices", "Prices", "NSE daily files, moves and labels"),
    ("deals", "Deals", "bulk and block deals"),
    ("xbrl", "Results (XBRL)", "exact figures from NSE"),
    ("holdings", "Shareholding", "quarterly patterns"),
    ("bullion", "Bullion", "gold and silver; notes on unusual days"),
    ("securities", "Company lists", "NSE and BSE listings, weekly"),
]
# (job, name, model, LLM task names): the agents that reason with Claude.
THINKERS = [
    ("triage", "News triage", "Haiku", ["triage"]),
    ("results", "Results reader", "Haiku", ["results"]),
    ("events", "Events + QA checker", "Haiku · Sonnet", ["events", "qa"]),
    ("explain", "Move explainer", "Sonnet", ["explain"]),
    ("concalls", "Earnings calls", "Sonnet", ["concall"]),
    ("promises", "Promise ledger", "Sonnet", ["promises"]),
    ("orders", "Order books", "Haiku · Sonnet", ["orders", "order_book"]),
    ("themes", "Themes, read-across", "Haiku", ["themes"]),
    ("ask", "Ask (when you ask)", "Sonnet", ["ask"]),
]
RULES = [("flags", "Red-flag rules", "no AI: events, holdings, late results")]
OUTPUTS = [("digest", "Morning digest", "08:00, everything since the last one")]

LAYER = {
    "input": "#6b7280",
    "perceive": "#64748b",
    "plan": "#8a63c9",
    "think": "#3f72c4",
    "remember": "#2f8a85",
    "act": "#3f8f4f",
    "output": "#a16207",
    "guard": "#e0533d",
    "observe": "#d9822b",
}


def _state(status: dict, job: str) -> tuple[str, str]:
    """(state, the line under the name): running, ok, error, off or waiting."""
    run = status["jobs"].get(job)
    if job in status["paused"] or status["scheduled"].get(job) is False:
        return "off", "turned off" + (f" · last {run['started']:%d %b %H:%M}" if run else "")
    if run and run["status"] == "running":
        return "running", f"running for {int(run['seconds'] // 60)} min"
    if run:
        line = f"{run['started']:%d %b %H:%M} · {run['seconds']:.0f}s"
        return ("error" if run["status"] == "error" else "ok"), line
    return "waiting", "not run yet"


def _next(status: dict, job: str) -> str:
    when: datetime | None = status["next"].get(job)
    return f"next {when:%a %H:%M}" if when else ""


def _chip(status: dict, job: str, name: str, note: str, tasks=(), model: str = "") -> str:
    if job == "ask":
        state, line = "ok" if status["stored"]["questions"] else "waiting", "on demand"
    else:
        state, line = _state(status, job)
    calls = sum(status["ai_today"].get(t, {}).get("calls", 0) for t in tasks)
    cost = sum(status["ai_today"].get(t, {}).get("cost", 0.0) for t in tasks)
    ai = (
        f'<div class="ai">{calls} AI call{"s" * (calls != 1)} today · ${cost:.2f}</div>'
        if calls
        else ""
    )
    run = status["jobs"].get(job) or {}
    tip = html.escape(run.get("error") or run.get("summary") or note)
    nxt = _next(status, job)
    return (
        f'<div class="chip {state}" title="{tip}"><div class="head"><span class="dot"></span>'
        f"<b>{html.escape(name)}</b>"
        + (f'<span class="model">{html.escape(model)}</span>' if model else "")
        + f'</div><div class="note">{html.escape(note)}</div>'
        f'<div class="when">{html.escape(line)}{" · " + nxt if nxt else ""}</div>{ai}</div>'
    )


def _layer(kind: str, label: str, title: str, body: str, extra: str = "") -> str:
    return (
        f'<section class="layer {kind}" style="--c:{LAYER[kind]}"><div class="band">'
        f'{html.escape(label)}</div><div class="inner"><h2>{html.escape(title)}</h2>'
        f"{body}{extra}</div></section>"
    )


def _count(n: int, word: str) -> str:
    """'1 call', '2 calls', '1,204 articles'."""
    return f"{n:,} {word}{'s' * (n != 1)}"


def _flow(text: str, arrow: str = "↓") -> str:
    return f'<div class="flow"><span>{arrow}</span>{html.escape(text)}</div>'


def render(status: dict, palette: dict[str, str], dark: bool = False) -> str:
    """The Agent map as a complete HTML page in the theme's colours."""
    p = palette
    running = [j for j, r in status["jobs"].items() if r["status"] == "running"]
    upcoming = sorted(
        (when, job)
        for job, when in status["next"].items()
        if job not in status["paused"] and status["scheduled"].get(job, True)
    )[:4]
    spent, budget = status["spent"], status["budget"]
    used = min(spent / budget, 1.0) if budget else 1.0
    s = status["stored"]

    inputs = "".join(
        f'<span class="src">{html.escape(t)}</span>'
        for t in (
            "NSE and BSE websites",
            "News feeds, Google News",
            "Yahoo Finance (gold, silver, USD)",
            "The schedule, 07:00–23:00",
            "Your questions on Ask",
        )
    )
    perceive = (
        '<div class="chips">'
        + "".join(
            _chip(status, job, name, note, [job] if job == "bullion" else [])
            for job, name, note in COLLECTORS
        )
        + "</div>"
    )
    plan_body = (
        '<div class="kv"><b>Running now</b>'
        + (
            "".join(f'<span class="pill run">{html.escape(j)}</span>' for j in running)
            or '<span class="muted">nothing</span>'
        )
        + '</div><div class="kv"><b>Next</b>'
        + (
            "".join(f'<span class="pill">{html.escape(j)} {w:%H:%M}</span>' for w, j in upcoming)
            or '<span class="muted">no schedule</span>'
        )
        + '</div><p class="muted">The scheduler starts each job at its time '
        "(config/schedule.yaml) in a fixed order: collect, then judge, then measure, then "
        "report. Each job is one step; a missed one catches up on its next run.</p>"
    )
    think = (
        '<div class="chips">'
        + "".join(
            _chip(status, job, name, "", tasks, model) for job, name, model, tasks in THINKERS
        )
        + "".join(_chip(status, job, name, note) for job, name, note in RULES)
        + "</div>"
    )
    remember = (
        '<div class="mem"><h3>Short-term</h3><p>Each run\'s working set: the filings, news, '
        "prices and earlier calls put in front of the model for one decision; Ask's lookups "
        "for one question.</p></div>"
        '<div class="mem"><h3>Long-term (Postgres)</h3><p>'
        + " · ".join(
            _count(s[key], word)
            for key, word in (
                ("filings", "filing"),
                ("news", "article"),
                ("events", "event"),
                ("calls", "call"),
                ("promises", "promise"),
                ("questions", "question"),
            )
        )
        + '</p><p class="muted">Every agent reads what the others wrote: the explainer uses '
        "triaged news and events; promises are checked against results.</p></div>"
    )
    calls_today = sum(v["calls"] for v in status["ai_today"].values())
    cost_today = sum(v["cost"] for v in status["ai_today"].values())
    act = (
        '<div class="tools">'
        f'<div class="tool"><b>Anthropic API</b><span>{calls_today} calls today · '
        f"${cost_today:.2f}</span></div>"
        '<div class="tool"><b>Exchange downloads</b><span>browser-like, at a polite rate</span>'
        "</div>"
        '<div class="tool"><b>Database</b><span>agents write; Ask reads only</span></div>'
        '<div class="tool"><b>data folder</b><span>filing PDFs, digests</span></div>'
        "</div>"
    )
    output = (
        '<div class="chips">'
        + "".join(_chip(status, job, name, note) for job, name, note in OUTPUTS)
        + (
            '<div class="chip ok"><div class="head"><span class="dot"></span><b>Dashboard</b></div>'
            '<div class="note">these pages</div></div>'
            f'<div class="chip {"error" if status["open_flags"] else "ok"}"><div class="head">'
            '<span class="dot"></span><b>Red flags</b></div>'
            f'<div class="note">{status["open_flags"]} open, for you to look into</div></div>'
        )
        + "</div>"
    )
    guards = [
        (
            "Monthly budget",
            f"${spent:.2f} of ${budget:.2f}",
            f'<div class="bar"><i style="width:{used * 100:.0f}%"></i></div>',
        ),
        ("API key", "set" if status["has_key"] else "none: AI agents skip their turn", ""),
        (
            "Job switches",
            f"{len(status['paused'])} turned off" if status["paused"] else "all on",
            "",
        ),
        (
            "QA checker",
            f"{_count(status['unchecked_events'], 'event')} unchecked"
            if status["unchecked_events"]
            else "every event checked",
            "",
        ),
        ("Ask", "read-only SQL, row limits, step limit", ""),
        ("You decide", "dismiss flags; accept or reject doubtful events", ""),
        ("Rate limits", "exchanges and news fetched politely", ""),
    ]
    guard = "".join(
        f'<div class="g"><b>{html.escape(n)}</b><span>{html.escape(v)}</span>{x}</div>'
        for n, v, x in guards
    )
    observe = "".join(
        f'<div class="o"><span>{html.escape(n)}</span><b>{html.escape(v)}</b></div>'
        for n, v in (
            ("Runs, last 24 h", f"{status['runs_24h']}"),
            ("Errors, last 24 h", f"{status['errors_24h']}"),
            ("Average run", f"{status['avg_seconds']:.0f}s"),
            ("AI calls, last 24 h", f"{status['ai_calls_24h']} ({status['ai_failed_24h']} failed)"),
            ("AI spend this month", f"${spent:.2f}"),
        )
    )
    css = Template(CSS.read_text()).substitute(
        bg=p["bg"],
        card=p["card"],
        text=p["text"],
        muted=p["muted"],
        border=p["border"],
        soft=p["soft"],
        up=p["up"],
        down=p["down"],
        medium=p["medium"],
        run=p["accent_text"],
        guard=LAYER["guard"],
        observe=LAYER["observe"],
        guard_mix="22" if dark else "10",
        observe_mix="20" if dark else "9",
    )
    legend = (
        "".join(
            f'<span><i style="{style}"></i>{text}</span>'
            for style, text in (
                (f"background:{p['accent_text']}", "running"),
                (f"background:{p['up']}", "last run ok"),
                (f"background:{p['down']}", "last run failed"),
                (f"border:1.5px solid {p['muted']}", "turned off"),
                (f"background:{p['muted']}", "not run yet"),
            )
        )
        + "<span>Hover over a box for its last result.</span>"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
{css}
</style></head><body>
<div class="map">
<aside class="guard"><h2>Guardrails</h2>{guard}</aside>
<div class="main">
<div class="inputs"><span class="lbl">Input</span>{inputs}</div>
{_flow("collected on the schedule")}
{_layer("perceive", "Perceive", "Collectors (no AI)", perceive)}
{_flow("stored, then read by the agents")}
<div class="row">
{_layer("plan", "Plan", "Scheduler", plan_body)}
{_layer("think", "Think", "AI agents (Claude)", think)}
{_layer("remember", "Remember", "Memory", remember)}
</div>
{_flow("act through tools, report what changed")}
<div class="row2">
{_layer("act", "Act", "Tools", act)}
{_layer("output", "Output", "What you see", output)}
</div>
<div class="legend">{legend}</div>
</div>
<footer class="observe"><h2>Observe</h2>{observe}</footer>
</div></body></html>"""
