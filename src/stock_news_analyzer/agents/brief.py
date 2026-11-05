"""The view on a stock's research brief, written by the model from the facts only (step 31.2).

The facts (agents/research.py) are turned into numbered lines, each with its evidence badge:
"F12 [Filed] Results Q2 FY27: revenue ₹25,109 cr, +1% on the year". One call to the analysis
model (Sonnet) writes the view in the briefing grammar: the verdict, a two-line summary, three
stances, Observed → Read pairs citing the fact lines, "Why it matters" and "Key risk" for the
stock and each peer, decision cards and the decisions to make now.

Then every number in the view is checked against the facts: a number counts if it is one of
the facts' numbers as written or rounded (65 for 65.2, 1.2 for 1.17). The model is told not
to calculate new ones. If any is not found, the model is asked once more with the list; what
still fails is dropped (a stance, an observation, a decision) and recorded, so no figure on
the page is made up. Each view is saved with its facts (`research_briefs`).
"""

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import research as rs
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.llm import LLM, month_spend
from stock_news_analyzer.models import ResearchBrief
from stock_news_analyzer.sources.announcements import IST

MAX_TOKENS = 6000
SMALL_COUNTS = 12  # whole numbers up to this ("three quarters", "2 of 5") need no fact


class Stance(BaseModel):
    label: Literal["Favor", "Watch", "Avoid", "Check"]
    text: str = Field(description="One short clause, under 90 characters.")


class Observation(BaseModel):
    observed: str = Field(description="What the facts show, with their numbers.")
    read: str = Field(description="What it means for an investor, in one or two sentences.")
    facts: list[str] = Field(description="The fact ids it rests on, e.g. ['F3', 'F12'].")


class Note(BaseModel):
    symbol: str
    why_it_matters: str = Field(description="One sentence.")
    key_risk: str = Field(description="One sentence.")


class Decision(BaseModel):
    tag: Literal["Review now", "Watch", "Hold steady", "Check"]
    title: str = Field(description="A few words.")
    why: str = Field(description="One or two sentences, citing what the facts show.")
    facts: list[str]


class View(BaseModel):
    verdict: str = Field(description="The conclusion in one line, under 110 characters.")
    summary: str = Field(description="Two sentences.")
    stances: list[Stance] = Field(description="Exactly three.")
    observations: list[Observation] = Field(description="Three to six, most important first.")
    subject: Note = Field(description="The stock itself.")
    peers: list[Note] = Field(description="One for each peer listed in the facts.")
    decisions: list[Decision] = Field(description="Three to five.")
    decide_now: list[str] = Field(description="Up to four short questions to settle now.")


SYSTEM = """You write the view in a research brief on one Indian listed company, for a private
investor who owns or follows it. You are given numbered facts, each with its evidence: Filed
(as filed with the exchange), Read by AI (read from a filing by a model, checked), Market
(prices), Stale (older than a half year), Not disclosed.

Rules:
- Use only the facts given. Do not add anything from memory: no figures, events, people,
  products or news that are not in the facts.
- Every number you write must be one of the facts' numbers, as written or rounded (65 for
  65.2). Do not calculate new numbers: no differences, ratios, sums or growth rates of your
  own. Name dates as the facts give them.
- Cite the fact ids an observation or a decision rests on.
- Weigh the evidence: say less about Read by AI and Stale facts, and say when something is
  not disclosed if it matters.
- Write conclusion first and plainly, in short sentences. British spelling.
- Do not tell the reader to buy, sell or hold. Decisions are about what to review, watch or
  check, and why. This is an input for their own decision, not advice.

The view:
- verdict: the conclusion in one line, like a headline ("Orders are running ahead of
  execution; margins are the question.").
- summary: two sentences.
- stances: three, labelled Favor, Watch, Avoid or Check, each one short clause.
- observations: three to six Observed → Read pairs, most important first: what the facts show
  (observed), then what it means (read).
- subject: why the stock matters and its key risk; peers: the same for each peer listed.
- decisions: three to five cards tagged Review now, Watch, Hold steady or Check.
- decide_now: up to four short questions the investor should settle now."""


# --- the facts as numbered lines ----------------------------------------------------------


def _pct(x, digits=1) -> str:
    return "–" if x is None else f"{x:+.{digits}%}"


def _cr(x) -> str:
    return "–" if x is None else f"₹{x:,.0f} cr"


def fact_lines(f: rs.Facts, today: date) -> list[tuple[str, str]]:
    """The facts as numbered lines: (id, '[badge] text')."""
    lines: list[str] = []

    def add(badge: str, text: str) -> None:
        lines.append(f"[{badge}] {text}")

    v = f.valuation
    add(
        "Filed",
        f"Company: {f.name} ({f.symbol}), NSE, industry {f.industry or 'unknown'}; "
        f"brief of {today:%d %b %Y}",
    )
    if v.close is not None:
        add(rs.MARKET, f"Close ₹{v.close:,.2f} on {v.close_date:%d %b %Y}")
    if v.pe:
        add(rs.MARKET, f"Trailing P/E {v.pe:.1f} (trailing EPS ₹{v.eps_ttm:,.2f})")
    elif v.note:
        add(rs.NOT_DISCLOSED, f"No trailing P/E: {v.note}")
    if v.pe_median:
        add(
            rs.MARKET,
            f"P/E over the last {val_years()} years: median {v.pe_median:.1f}, "
            f"10th percentile {v.pe_low:.1f}, 90th percentile {v.pe_high:.1f}; today higher "
            f"than {v.pe_percentile:.0%} of days",
        )
    if v.eps_growth is not None:
        add(rs.FILED, f"Trailing EPS growth on a year before: {_pct(v.eps_growth)}")
    if v.sector_pe:
        add(
            rs.MARKET,
            f"{v.sector_index} P/E {v.sector_pe:.1f} (its median {v.sector_pe_median:.1f})",
        )
    if v.nifty_pe:
        add(rs.MARKET, f"Nifty 50 P/E {v.nifty_pe:.1f} (its median {v.nifty_pe_median:.1f})")
    if v.market_cap_cr:
        add(rs.MARKET, f"Market cap {_cr(v.market_cap_cr)}")
    for q in f.quarters:
        margin = f"{q['margin']:.1%}" if q["margin"] is not None else "–"
        add(
            q["badge"],
            f"Results {q['period']} (to {q['end']:%d %b %Y}, {q['basis']}): revenue "
            f"{_cr(q['revenue'])}, {_pct(q['revenue_growth'], 0)} on the year; profit "
            f"{_cr(q['pat'])}, {_pct(q['pat_growth'], 0)} on the year; margin {margin}",
        )
    for b in f.balance:
        if b.value is None:
            add(rs.NOT_DISCLOSED, f"{b.label} at {b.when:%d %b %Y}: not in the filing")
            continue
        value = _cr(b.value) if b.unit == "cr" else f"{b.value:.2f}×"
        add(b.badge, f"{b.label} at {b.when:%d %b %Y}: {value}")
    for p in f.peers:
        if p.is_subject:
            continue
        pe = f"P/E {p.pe:.1f}" if p.pe else "no P/E"
        add(
            p.badge,
            f"Peer {p.symbol} ({p.name}): {pe}, one-year price change "
            f"{_pct(p.return_1y, 0)}, latest revenue growth {_pct(p.revenue_growth, 0)}"
            f"{' (' + p.period + ')' if p.period else ''}, market cap {_cr(p.market_cap_cr)}",
        )
    ob = f.order_book
    if ob:
        parts = []
        if ob.get("order_book_cr"):
            parts.append(f"order book {_cr(ob['order_book_cr'])} ({ob.get('order_book_quarter')})")
        if ob.get("years_of_revenue"):
            parts.append(f"{ob['years_of_revenue']:.1f} years of revenue")
        if ob.get("book_to_bill"):
            parts.append(f"book-to-bill {ob['book_to_bill']:.2f}")
        if ob.get("announced_growth") is not None:
            parts.append(
                f"orders announced in the last four quarters {_pct(ob['announced_growth'], 0)} "
                "on the four before"
            )
        if ob.get("government_share") is not None:
            parts.append(
                f"government and PSU share of the year's orders {ob['government_share']:.0%}"
            )
        add(rs.AI, "Order book: " + "; ".join(parts))
    c = f.credibility
    if c:
        score = (
            f"credibility score {c['score']:.0%}" if c.get("score") is not None else "no score yet"
        )
        add(
            rs.AI,
            f"Management promises: {c['kept']} kept, {c['kept_late']} kept late, "
            f"{c['partly']} partly, {c['missed']} missed, {c['dropped']} dropped, "
            f"{c['overdue']} overdue, {c['to_come']} to come; {score}",
        )
    for p in f.promises[:5]:
        add(
            rs.AI,
            f"Promise: {p['metric']} {p['target']} by {p['due']}: {p['status']}"
            f"{' (' + p['note'] + ')' if p['note'] else ''}",
        )
    for m in f.management[:5]:
        add(rs.AI, f"Management change {m['when']:%d %b %Y}: {m['headline']}")
    for o in f.ownership[:2]:
        add(
            rs.FILED,
            f"Shareholding at {o['quarter']:%d %b %Y}: promoters {_share(o['promoter'])}, "
            f"FIIs {_share(o['fii'])}, DIIs {_share(o['dii'])}, mutual funds {_share(o['mf'])}, "
            f"retail {_share(o['retail'])}; pledged {_share(o['pledged'])} of promoters' shares",
        )
    h = f.lean
    if h is not None:
        add(
            rs.MARKET,
            f"Lean from recent events (event study): {h.lean}, score {_pct(h.score)}; "
            f"last 12 weeks {_pct(h.move_12w)} against the Nifty 50",
        )
        for r in h.reasons[:4]:
            usually = _pct(r.median) if r.median is not None else "no evidence"
            add(
                rs.MARKET,
                f"Event {r.case.at.astimezone(IST):%d %b %Y}, {r.case.kind}: "
                f"{r.case.detail}; such events usually {usually} over 20 days ({r.cases} cases); "
                f"the stock {_pct(r.since)} since",
            )
    for n in f.top_news[:6]:
        add(
            rs.AI,
            f"News {n['when']:%d %b %Y} ({n['sentiment']}, importance {n['importance']}): "
            f"{n['summary'] or n['title']}",
        )
    for cdate in f.coming:
        add(cdate.badge, f"Coming {cdate.day:%d %b %Y}: {cdate.what}")
    for flag in f.flags:
        add(rs.FILED, f"Open red flag {flag.flagged_on:%d %b %Y} ({flag.severity}): {flag.title}")
    return [(f"F{i}", text) for i, text in enumerate(lines, 1)]


def _share(x) -> str:
    return "–" if x is None else f"{x:.1%}"


def val_years() -> int:
    from stock_news_analyzer.agents import valuation

    return valuation.YEARS


# --- checking the numbers ---------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])[-−+]?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?")


def numbers(text: str) -> list[tuple[str, float]]:
    """(as written, value) of every number in a text; Q2, FY27 and F12 are labels, not numbers."""
    out = []
    for m in NUMBER.finditer(text or ""):
        raw = m.group(0)
        try:
            out.append((raw, float(raw.replace(",", "").replace("−", "-"))))
        except ValueError:
            continue
    return out


def allowed(lines: list[tuple[str, str]]) -> list[float]:
    return [abs(v) for _, text in lines for _, v in numbers(text)]


def unknown_numbers(text: str, known: list[float]) -> list[str]:
    """The numbers in `text` that aren't among the facts' (as written or rounded). Small whole
    numbers count as counts ("3 of 5 quarters") unless they are a percentage, a multiple or
    an amount."""
    bad = []
    text = text or ""
    for m in NUMBER.finditer(text):
        raw = m.group(0)
        try:
            x = abs(float(raw.replace(",", "").replace("−", "-")))
        except ValueError:
            continue
        after = text[m.end() : m.end() + 2].strip()
        before = text[max(m.start() - 1, 0) : m.start()]
        quantity = after[:1] in ("%", "×", "x") or before == "₹" or after.startswith("cr")
        if x == int(x) and x <= SMALL_COUNTS and not quantity:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tolerance = 0.5 * 10**-decimals + 1e-9
        if not any(abs(x - a) <= tolerance for a in known):
            bad.append(raw)
    return bad


def _texts(view: View) -> list[tuple[str, str]]:
    """(where, text) of every piece of the view, for checking and dropping."""
    out = [("verdict", view.verdict), ("summary", view.summary)]
    out += [(f"stance {i}", s.text) for i, s in enumerate(view.stances)]
    for i, o in enumerate(view.observations):
        out += [(f"observation {i}", o.observed), (f"observation {i}", o.read)]
    out += [("subject", view.subject.why_it_matters), ("subject", view.subject.key_risk)]
    for i, p in enumerate(view.peers):
        out += [(f"peer {i}", p.why_it_matters), (f"peer {i}", p.key_risk)]
    for i, d in enumerate(view.decisions):
        out += [(f"decision {i}", d.title), (f"decision {i}", d.why)]
    out += [(f"decide {i}", q) for i, q in enumerate(view.decide_now)]
    return out


def check(view: View, known: list[float]) -> dict[str, list[str]]:
    """{where: numbers not among the facts}."""
    found: dict[str, list[str]] = {}
    for where, text in _texts(view):
        bad = unknown_numbers(text, known)
        if bad:
            found.setdefault(where, []).extend(bad)
    return found


def drop(view: View, problems: dict[str, list[str]], fallback: str) -> tuple[View, list[dict]]:
    """Remove the parts with unchecked numbers; the verdict and summary fall back to facts."""
    dropped = []
    v = view.model_copy(deep=True)

    def gone(prefix: str) -> set[int]:
        return {int(w.split()[-1]) for w in problems if w.startswith(prefix)}

    if "verdict" in problems:
        dropped.append({"part": "verdict", "text": v.verdict, "numbers": problems["verdict"]})
        v.verdict = fallback
    if "summary" in problems:
        dropped.append({"part": "summary", "text": v.summary, "numbers": problems["summary"]})
        v.summary = ""
    for name, attr in (
        ("stance", "stances"),
        ("observation", "observations"),
        ("peer", "peers"),
        ("decision", "decisions"),
        ("decide", "decide_now"),
    ):
        bad = gone(name + " ")
        items = getattr(v, attr)
        for i in sorted(bad):
            item = items[i]
            dropped.append(
                {
                    "part": name,
                    "text": item if isinstance(item, str) else item.model_dump_json(),
                    "numbers": problems[f"{name} {i}"],
                }
            )
        setattr(v, attr, [x for i, x in enumerate(items) if i not in bad])
    if "subject" in problems:
        dropped.append(
            {"part": "subject", "text": v.subject.model_dump_json(), "numbers": problems["subject"]}
        )
        v.subject = Note(symbol=v.subject.symbol, why_it_matters="", key_risk="")
    return v, dropped


# --- writing the view ---------------------------------------------------------------------------


def prompt(f: rs.Facts, lines: list[tuple[str, str]]) -> str:
    peers = ", ".join(p.symbol for p in f.peers if not p.is_subject) or "none"
    body = "\n".join(f"{i} {text}" for i, text in lines)
    return (
        f"Company: {f.name} ({f.symbol}). Peers to cover: {peers}.\n\n"
        f"Facts ({len(lines)}):\n{body}\n\nWrite the view."
    )


def write(
    session: Session,
    llm: LLM,
    isin: str,
    model: str | None = None,
    today: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> ResearchBrief:
    """Gather the facts, ask the model for the view, check its numbers, save it."""
    say = progress or (lambda _line: None)
    model = model or get_settings().llm_model_analysis
    today = today or datetime.now(IST).date()
    spend_before = month_spend(session)
    say(
        "Gathering the facts: valuation, results, balance sheet, peers, order book, promises, "
        "ownership, news..."
    )
    f = rs.facts(session, isin, today)
    lines = fact_lines(f, today)
    known = allowed(lines)
    fallback = _fallback_verdict(f)
    say(f"Asking {model} for the view on {len(lines)} facts...")
    view = llm.structured(
        "brief", model, SYSTEM, prompt(f, lines), View, effort="medium", max_tokens=MAX_TOKENS
    )
    say("Checking every number against the facts...")
    problems = check(view, known)
    if problems:
        listed = ", ".join(sorted({n for ns in problems.values() for n in ns}))
        say(f"{len(problems)} parts used numbers not in the facts ({listed}); asking once more...")
        retry = (
            prompt(f, lines)
            + f"\n\nYour last answer used numbers that are not among the facts: {listed}. "
            "Write the view again using only the facts' numbers, as written or rounded."
        )
        view = llm.structured(
            "brief", model, SYSTEM, retry, View, effort="medium", max_tokens=MAX_TOKENS
        )
        problems = check(view, known)
    view, dropped = drop(view, problems, fallback) if problems else (view, [])
    brief = ResearchBrief(
        isin=isin,
        model=model,
        cost_usd=month_spend(session) - spend_before,
        facts=[list(line) for line in lines],
        view=view.model_dump(),
        dropped=dropped,
    )
    session.add(brief)
    session.commit()
    say(f"Saved: ${brief.cost_usd:.3f}" + (f", {len(dropped)} parts dropped" if dropped else ""))
    return brief


def _fallback_verdict(f: rs.Facts) -> str:
    v = f.valuation
    if v.pe and v.pe_median:
        side = "below" if v.pe < v.pe_median else "above"
        return f"P/E {v.pe:.0f}, {side} its {val_years()}-year median of {v.pe_median:.0f}."
    return f"{f.name}: the facts so far."


def latest(session: Session, isin: str) -> ResearchBrief | None:
    return session.scalars(
        select(ResearchBrief)
        .where(ResearchBrief.isin == isin)
        .order_by(ResearchBrief.created_at.desc(), ResearchBrief.id.desc())
        .limit(1)
    ).first()


def versions(session: Session, isin: str) -> list[ResearchBrief]:
    return list(
        session.scalars(
            select(ResearchBrief)
            .where(ResearchBrief.isin == isin)
            .order_by(ResearchBrief.created_at.desc(), ResearchBrief.id.desc())
        )
    )


def estimate(lines: list[tuple[str, str]], model: str) -> Decimal:
    """A rough cost of one view in dollars: the facts in, the view out."""
    from stock_news_analyzer.llm import PRICES

    inp, out = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    tokens_in = Decimal(sum(len(t) for _, t in lines) / 4 + 1200)
    return (tokens_in * inp + Decimal(2500) * out) / Decimal(1_000_000)
