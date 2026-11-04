"""The Agent map: the whole system laid out as an agent's anatomy (perceive, plan, think,
remember, act, guardrails, observe), to show and teach how an agentic system works.

Two modes: "live" shows each part's state now (from `queries.agent_status`) and today's runs
as a narrated feed, with moving dots along the path of each job that is running; "replay"
plays back the last days' runs (`queries.agent_events`) on the map, with play, speed and a
time slider. `render` returns a complete HTML page, shown in an iframe by the dashboard (the
iframe keeps its own styles and script, which `st.html` would drop).
"""

import html
import json
from datetime import datetime
from pathlib import Path
from string import Template

CSS = Path(__file__).with_name("agent_map.css")
SCRIPT = Path(__file__).with_name("agent_map.js")

# What each layer is, in any agentic system: the map teaches as well as shows.
CONCEPT = {
    "perceive": "Turns the outside world into data the agents can use: fetch, clean, store. "
    "No reasoning yet.",
    "plan": "Decides what runs when, and in what order. Here a fixed schedule; in other "
    "systems an LLM breaks a goal into steps.",
    "think": "Each agent makes one kind of judgement with an LLM, from what memory holds, "
    "and writes its answer back.",
    "remember": "Short-term memory is what one decision sees; long-term memory is everything "
    "kept, which every agent reads and adds to.",
    "act": "Tools are how agents touch the world: an API, the database, files.",
    "output": "What people see: the morning digest, the dashboard, the flags to look into.",
    "guard": "Limits on what agents may do, checked at every step, not only at the start.",
    "observe": "A record of every run and AI call, to debug the loop and track its cost.",
}
# Where each job's information comes from, for the moving dots and the narration.
SOURCE = {
    "filings": ("in-exchanges", "the BSE and NSE announcement pages"),
    "news": ("in-news", "news feeds and Google News"),
    "prices": ("in-exchanges", "NSE's daily price files"),
    "deals": ("in-exchanges", "NSE's bulk and block deals"),
    "xbrl": ("in-exchanges", "NSE's XBRL results files"),
    "holdings": ("in-exchanges", "NSE's shareholding patterns"),
    "bullion": ("in-yahoo", "gold and silver prices"),
    "securities": ("in-exchanges", "the NSE and BSE company lists"),
}

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
    if job in status.get("missed", {}):
        return "missed", f"missed its {status['missed'][job]:%a %d %b %H:%M} run"
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
        f'<div class="chip {state}" id="job-{job}" data-job="{job}" title="{tip}">'
        '<div class="head"><span class="dot"></span>'
        f"<b>{html.escape(name)}</b>"
        + (f'<span class="model">{html.escape(model)}</span>' if model else "")
        + f'</div><div class="note">{html.escape(note)}</div>'
        f'<div class="when">{html.escape(line)}{" · " + nxt if nxt else ""}</div>{ai}</div>'
    )


def _layer(kind: str, label: str, title: str, body: str, extra: str = "") -> str:
    return (
        f'<section class="layer {kind}" id="layer-{kind}" style="--c:{LAYER[kind]}">'
        f'<div class="band">{html.escape(label)}</div><div class="inner">'
        f'<h2>{html.escape(title)}</h2><p class="concept">{html.escape(CONCEPT[kind])}</p>'
        f"{body}{extra}</div></section>"
    )


def _count(n: int, word: str) -> str:
    """'1 call', '2 calls', '1,204 articles'."""
    return f"{n:,} {word}{'s' * (n != 1)}"


def _flow(text: str, arrow: str = "↓") -> str:
    return f'<div class="flow"><span>{arrow}</span>{html.escape(text)}</div>'


def render(
    status: dict,
    palette: dict[str, str],
    dark: bool = False,
    events: list[dict] | None = None,
    mode: str = "live",
) -> str:
    """The Agent map as a complete HTML page in the theme's colours. `events`: the runs to
    narrate (today's in "live", the last days' in "replay")."""
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
        f'<span class="src" id="{key}">{html.escape(t)}</span>'
        for key, t in (
            ("in-exchanges", "NSE and BSE websites"),
            ("in-news", "News feeds, Google News"),
            ("in-yahoo", "Yahoo Finance (gold, silver, USD)"),
            ("in-schedule", "The schedule, 07:00–23:00"),
            ("in-you", "Your questions on Ask"),
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
        '<div class="mem" id="mem-short"><h3>Short-term</h3><p>Each run\'s working set: the '
        "filings, news, prices and earlier calls put in front of the model for one decision; "
        "Ask's lookups for one question.</p></div>"
        '<div class="mem" id="mem-long"><h3>Long-term (Postgres)</h3><p>'
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
    tools = [
        ("tool-anthropic", "Anthropic API", f"{calls_today} calls today · ${cost_today:.2f}"),
        ("tool-download", "Exchange downloads", "browser-like, at a polite rate"),
        ("tool-database", "Database", "agents write; Ask reads only"),
        ("tool-files", "data folder", "filing PDFs, digests"),
    ]
    act = (
        '<div class="tools">'
        + "".join(
            f'<div class="tool" id="{key}"><b>{name}</b><span>{html.escape(what)}</span></div>'
            for key, name, what in tools
        )
        + "</div>"
    )
    flags_state = "error" if status["open_flags"] else "ok"
    output = (
        '<div class="chips">'
        + "".join(_chip(status, job, name, note) for job, name, note in OUTPUTS)
        + '<div class="chip ok" id="out-dashboard"><div class="head"><span class="dot"></span>'
        '<b>Dashboard</b></div><div class="note">these pages</div></div>'
        f'<div class="chip {flags_state}" id="out-flags"><div class="head">'
        '<span class="dot"></span><b>Red flags</b></div>'
        f'<div class="note">{status["open_flags"]} open, for you to look into</div></div>'
        "</div>"
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
        f'<div class="g" id="g-{i}"><b>{html.escape(n)}</b><span>{html.escape(v)}</span>{x}</div>'
        for i, (n, v, x) in enumerate(guards)
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
                (f"background:{p['medium']}", "missed a run"),
                (f"border:1.5px solid {p['muted']}", "turned off"),
                (f"background:{p['muted']}", "not run yet"),
            )
        )
        + "<span>Hover over a box for its last result.</span>"
    )
    jobs = {job: {"name": n, "kind": "collector", "note": note} for job, n, note in COLLECTORS}
    for job, n, model, _tasks in THINKERS:
        jobs[job] = {"name": n, "kind": "ask" if job == "ask" else "ai", "model": model}
    jobs.update({job: {"name": n, "kind": "rules"} for job, n, _note in RULES})
    jobs.update({job: {"name": n, "kind": "output"} for job, n, _note in OUTPUTS})
    for job, (where, what) in SOURCE.items():
        jobs[job].update(source=where, from_=what)
    data = {
        "mode": mode,
        "now": int(status["now"].timestamp() * 1000),
        "today": int(
            status["now"].replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000
        ),
        "events": events or [],
        "jobs": jobs,
        "running": running,
        "colors": {"run": p["accent_text"], "up": p["up"], "down": p["down"]},
    }
    controls = (
        '<div class="controls" id="controls">'
        '<button id="play" type="button">▶ Play</button>'
        '<span class="seg"><button type="button" data-span="today">Today</button>'
        '<button type="button" data-span="week" class="on">Last 7 days</button></span>'
        '<label>Speed <select id="speed"><option value="600">10 min / s</option>'
        '<option value="3600" selected>1 hour / s</option><option value="21600">6 hours / s'
        "</option></select></label>"
        '<label><input type="checkbox" id="skip" checked> skip quiet hours</label>'
        '<input type="range" id="scrub" min="0" max="1000" value="0">'
        '<b id="clock"></b><span id="tally" class="muted"></span></div>'
        if mode == "replay"
        else ""
    )
    feed_title = (
        "What happened, step by step" if mode == "replay" else "Today's action, newest first"
    )
    feed = (
        f'<section class="feed"><h2>{feed_title}</h2>'
        '<p class="concept">Each line is one step of the loop: where information came from, '
        'which part handled it, and where it went.</p><ol id="feed"></ol></section>'
    )
    payload = json.dumps(data).replace("</", "<\\/")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
{css}
</style></head><body class="{mode}">
{controls}
<div class="map" id="map">
<aside class="guard" id="layer-guard"><h2>Guardrails</h2>
<p class="concept">{html.escape(CONCEPT["guard"])}</p>{guard}</aside>
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
<footer class="observe" id="observe"><h2>Observe</h2>{observe}
<p class="concept">{html.escape(CONCEPT["observe"])}</p></footer>
</div>
{feed}
<script id="data" type="application/json">{payload}</script>
<script>
{SCRIPT.read_text()}
</script></body></html>"""
