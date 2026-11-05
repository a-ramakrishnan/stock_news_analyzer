"""The eval of the Event Extractor (agents/events.py): does it find the events a filing announces,
of the right types and amounts, with quotes that are really in the filing?

Cases are YAML files in `evals/events/cases/`, one per filing, frozen from your database by
`sample`: the filing as the agent reads it (title, subject, text) and the expected events. The
expected events are drafted by a stronger model (`draft`) and checked by you (`verified: true`):
the eval's score is only as good as those answers.

`run` calls the agent's real entry point (`events._ask`, one filing per call) on each case and
grades the raw answer by code, before the QA Checker corrects or rejects anything:

- `correct` (the headline): event or no event as expected, the same event types, and every
  expected amount right (within 1%).
- `detect`: an event found when there is one, none when there isn't.
- `types`: F1 of the event types found against those expected (1 when both are none).
- `amounts`: share of expected events whose amount (or its absence) is right.
- `quotes`: share of the events found whose quote is in the filing and holds its amount.

Results go to `.claude/hillclimb/events/<variant>/` (results.jsonl, traces/, errors.jsonl,
summary.md), one row per case and repetition, written as each finishes; a rerun resumes.
"""

import hashlib
import json
import math
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import events as agent
from stock_news_analyzer.agents import results as rs
from stock_news_analyzer.agents.concalls import _norm, quote_in
from stock_news_analyzer.models import Company, Document, Event, EventFiling

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "evals" / "events" / "cases"
FLOW = ROOT / ".claude" / "hillclimb" / "events"
DRAFT_MODEL = "claude-opus-5-5"
TEXT_CHARS = 30_000  # of a filing's text frozen in a case (the agent reads less)
AMOUNT_TOLERANCE = Decimal("0.01")
METRICS = [
    {"id": "correct", "label": "Correct", "kind": "binary"},
    {"id": "detect", "label": "Detect", "kind": "binary"},
    {"id": "types", "label": "Types F1", "kind": "continuous"},
    {"id": "amounts", "label": "Amounts", "kind": "continuous"},
    {"id": "quotes", "label": "Quotes found", "kind": "continuous"},
]
HARNESS = [Path(__file__)]  # the runner and grader; a change needs your approval


# ------------------------------------------------------------------ cases


@dataclass
class Case:
    path: Path
    data: dict

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def expected(self) -> list[dict]:
        return list((self.data.get("expected") or {}).get("events") or [])

    @property
    def verified(self) -> bool:
        return bool((self.data.get("expected") or {}).get("verified"))

    def filing(self) -> tuple[Document, Company]:
        """The filing and company as the agent receives them (not added to any session)."""
        d = self.data
        doc = Document(
            id=int(d["document_id"]),
            title=d["title"],
            subject=d.get("subject"),
            text=d.get("text"),
            text_status=d.get("text_status") or "pending",
            published_at=datetime.fromisoformat(str(d["published_at"])),
            doc_type=d.get("doc_type") or "",
        )
        company = Company(isin=d["isin"], name=d["company"], nse_symbol=d.get("symbol"))
        return doc, company


class _Literal(str):
    pass


yaml.add_representer(
    _Literal, lambda dumper, s: dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")
)


def _dump(data: dict) -> str:
    out = dict(data)
    if out.get("text"):
        out["text"] = _Literal(out["text"].rstrip() + "\n")
    return yaml.dump(out, sort_keys=False, allow_unicode=True, width=100)


def load_cases(folder: Path = CASES) -> list[Case]:
    return [Case(p, yaml.safe_load(p.read_text())) for p in sorted(folder.glob("*.yaml"))]


def save(case: Case) -> None:
    case.path.write_text(_dump(case.data))


def _case_data(doc: Document, company: Company, stratum: str) -> dict:
    return {
        "id": f"doc{doc.id}",
        "document_id": doc.id,
        "company": company.name,
        "symbol": company.nse_symbol,
        "isin": company.isin,
        "published_at": doc.published_at.isoformat(),
        "doc_type": doc.doc_type,
        "stratum": stratum,
        "title": doc.title,
        "subject": doc.subject,
        "text_status": doc.text_status,
        "text": (doc.text or "")[:TEXT_CHARS],
        "expected": {"verified": False, "drafted_by": None, "events": [], "note": ""},
    }


def sample(
    session: Session, with_events: int = 25, without: int = 15, seed: int = 7, folder=CASES
) -> list[Path]:
    """Freeze filings the agent has read into cases: those it found events in, spread over
    the event types (filings whose events you rejected first), and routine ones it found none
    in. The stratum records what the agent said then, not the answer."""
    rng = random.Random(seed)
    folder.mkdir(parents=True, exist_ok=True)
    taken = {c.data["document_id"] for c in load_cases(folder)}
    rows = session.execute(
        select(Event.event_type, Event.review, Document, Company)
        .join(Document, Document.id == Event.document_id)
        .join(Company, Company.isin == Event.isin)
        .where(Event.duplicate_of.is_(None))
    ).all()
    by_type: dict[str, list] = {}
    rejected = []
    for event_type, review, doc, company in rows:
        if review == "rejected":
            rejected.append((f"rejected:{event_type}", doc, company))
        by_type.setdefault(event_type, []).append((f"found:{event_type}", doc, company))
    rng.shuffle(rejected)
    for items in by_type.values():
        rng.shuffle(items)
    picked: list[tuple[str, Document, Company]] = []
    seen = set(taken)

    def take(item) -> bool:
        if item[1].id in seen:
            return False
        seen.add(item[1].id)
        picked.append(item)
        return True

    for item in rejected[: max(2, with_events // 5)]:
        take(item)
    types = sorted(by_type, key=lambda t: len(by_type[t]))
    while len(picked) < with_events and any(by_type[t] for t in types):
        for t in types:
            while by_type[t]:
                if take(by_type[t].pop()):
                    break
            if len(picked) >= with_events:
                break
    quiet = session.execute(
        select(Document, Company)
        .join(EventFiling, EventFiling.document_id == Document.id)
        .join(Company, Company.isin == EventFiling.isin)
        .where(EventFiling.status == "no_event")
    ).all()
    rng.shuffle(quiet)
    for doc, company in quiet:
        if sum(1 for p in picked if p[0] == "found:none") >= without:
            break
        take(("found:none", doc, company))
    paths = []
    for stratum, doc, company in picked:
        path = folder / f"doc{doc.id}.yaml"
        path.write_text(_dump(_case_data(doc, company, stratum)))
        paths.append(path)
    return paths


def draft(llm, cases: list[Case], model: str = DRAFT_MODEL, say=print) -> int:
    """Draft the expected events of unverified cases that have no draft yet, with a stronger
    model than the one under test, for you to check. Each draft is saved as it comes; an API
    error stops the run there, to be continued by running it again."""
    from stock_news_analyzer.llm import LLMError

    done = 0
    for case in cases:
        exp = case.data.setdefault("expected", {})
        if case.verified or exp.get("drafted_by"):
            continue
        try:
            answer = llm.structured(
                "eval-draft",
                model,
                agent.SYSTEM,
                agent._prompt([case.filing()]),
                agent.EventsAnswer,
                effort="high",
                max_tokens=agent.MAX_TOKENS,
            )
        except LLMError as exc:
            say(f"Stopped at {case.id}: {exc}")
            say(f"{done} drafted this time; run draft again to continue from {case.id}.")
            return done
        found = answer.filings[0].events if answer.filings else []
        exp["events"] = [
            {
                "event_type": e.event_type,
                "value_cr": e.value_cr,
                "value_as_written": e.value_as_written,
                "headline": e.headline,
            }
            for e in found
        ]
        exp["drafted_by"] = model
        exp["verified"] = False
        save(case)
        done += 1
        say(f"{case.id}: {len(found)} events drafted")
    return done


def overview(cases: list[Case]) -> str:
    """The cases as a Markdown table, for reviewing them."""
    lines = [
        "| Case | Company | Filed | Type | Stratum | Expected events | Checked |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in cases:
        d = c.data
        exp = "; ".join(
            f"{e['event_type']}" + (f" Rs {e['value_cr']:g} cr" if e.get("value_cr") else "")
            for e in c.expected
        )
        if not exp and not c.verified and not (d.get("expected") or {}).get("drafted_by"):
            exp = "*not drafted*"
        lines.append(
            f"| {c.id} | {d.get('symbol') or d['isin']} | {str(d['published_at'])[:10]} | "
            f"{d.get('doc_type')} | {d.get('stratum')} | {exp or 'none'} | "
            f"{'yes' if c.verified else 'no'} |"
        )
    strata = Counter(
        "no event then"
        if c.data.get("stratum") == "found:none"
        else "rejected by you"
        if str(c.data.get("stratum")).startswith("rejected:")
        else "events then"
        for c in cases
    )
    with_events = sum(1 for c in cases if c.expected)
    lines += [
        "",
        f"{len(cases)} cases: {with_events} with expected events, {len(cases) - with_events} "
        f"without; {sum(c.verified for c in cases)} checked. What the agent said when it read "
        "them: " + ", ".join(f"{k} {v}" for k, v in sorted(strata.items())),
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ grading


def _amount_ok(expected, found) -> bool:
    if expected is None or found is None:
        return expected is None and found is None
    e, f = Decimal(str(expected)), Decimal(str(found))
    return abs(e - f) <= max(AMOUNT_TOLERANCE * abs(e), Decimal("0.01"))


def grade(expected: list[dict], found: list[dict], text: str) -> dict[str, float]:
    """Scores for one filing: the agent's events against the expected ones."""
    has_e, has_f = bool(expected), bool(found)
    detect = float(has_e == has_f)
    ce, cf = Counter(e["event_type"] for e in expected), Counter(e["event_type"] for e in found)
    tp = sum((ce & cf).values())
    if not expected and not found:
        types = 1.0
    else:
        p = tp / len(found) if found else 0.0
        r = tp / len(expected) if expected else 0.0
        types = 2 * p * r / (p + r) if p + r else 0.0
    # pair each expected event with an unused found event of its type, the closest amount first
    unused = list(found)
    right = 0
    for e in expected:
        same = [f for f in unused if f["event_type"] == e["event_type"]]
        best = next((f for f in same if _amount_ok(e.get("value_cr"), f.get("value_cr"))), None)
        best = best or (same[0] if same else None)
        if best is not None:
            unused.remove(best)
            right += _amount_ok(e.get("value_cr"), best.get("value_cr"))
    amounts = right / len(expected) if expected else float(not found)
    norm = _norm(text)
    good_quotes = 0
    for f in found:
        ok = bool(f.get("quote")) and quote_in(f["quote"], norm)
        if ok and f.get("value_as_written"):
            figure = rs.number(f["value_as_written"])
            ok = figure is not None and abs(figure) in rs.numbers_in(f["quote"])
        good_quotes += ok
    quotes = good_quotes / len(found) if found else 1.0
    correct = float(detect == 1 and types == 1 and amounts == 1)
    return {
        "correct": correct,
        "detect": detect,
        "types": round(types, 4),
        "amounts": round(amounts, 4),
        "quotes": round(quotes, 4),
    }


# ------------------------------------------------------------------ the runner


class HarnessChanged(RuntimeError):
    pass


def harness_digest() -> str:
    h = hashlib.sha256()
    for p in HARNESS:
        h.update(p.read_bytes())
    return h.hexdigest()


def check_harness(flow: Path, approve: bool) -> None:
    """Refuse to run when the runner or grader changed since you last approved them."""
    stamp = flow / "harness.sha256"
    now = harness_digest()
    if approve:
        flow.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now + "\n")
        return
    if not stamp.exists() or stamp.read_text().strip() != now:
        raise HarnessChanged(
            "the eval's runner or grader is new or changed: read it, then run once with "
            "--approve-harness"
        )


def write_state(flow: Path) -> None:
    flow.mkdir(parents=True, exist_ok=True)
    state = {
        "flow": "events",
        "metrics": METRICS,
        "perf_fields": ["latency_s", "usage", "cost_usd"],
        "harness_paths": [str(p.relative_to(ROOT)) for p in HARNESS],
    }
    (flow / "_state.json").write_text(json.dumps(state, indent=1) + "\n")


def _done(results: Path) -> set[tuple[str, int]]:
    if not results.exists():
        return set()
    rows = [json.loads(line) for line in results.read_text().splitlines() if line.strip()]
    return {(r["prompt_id"], r["rep"]) for r in rows}


def _events_of(answer, doc_id: int) -> list[dict]:
    for f in answer.filings:
        if f.id == doc_id:
            return [e.model_dump() for e in f.events]
    return []


def _attempt(session_factory, llm_factory, case: Case, model: str, mode: str):
    """One call of the agent on one case: (events found, trace, model served, call)."""
    doc, company = case.filing()
    prompt = agent._prompt([(doc, company)])
    if mode == "oracle":  # the expected answer, through the grader: should score 100%
        found = [{**e, "quote": None, "value_as_written": None} for e in case.expected]
        return found, prompt, model, None, "end_turn"
    if mode == "null":  # no events at all: scores only the cases without events
        return [], prompt, model, None, "end_turn"
    with session_factory() as session:
        llm = llm_factory(session)
        answer = agent._ask(llm, model, [(doc, company)])
        c = llm.last_call
        call = {
            "usage": {
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cache_read_input_tokens": c.cache_read_tokens,
                "cache_creation_input_tokens": c.cache_write_tokens,
            },
            "cost_usd": float(c.cost_usd),
        }
        session.commit()
        return _events_of(answer, doc.id), prompt, llm.last_model, call, llm.last_stop_reason


def run(
    session_factory,
    llm_factory,
    cases: list[Case],
    *,
    variant: str = "baseline",
    model: str,
    reps: int = 3,
    workers: int = 4,
    mode: str = "agent",
    flow: Path = FLOW,
    approve_harness: bool = False,
    say=print,
) -> dict:
    """Run the agent on every case `reps` times, grade, write results; returns the summary.
    The per-call wall-clock ceiling is the client's timeout (see `llm_factory`)."""
    from stock_news_analyzer.llm import LLMError

    if mode == "agent":
        check_harness(flow, approve_harness)
    write_state(flow)
    out = flow / variant
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results, errors = out / "results.jsonl", out / "errors.jsonl"
    done = _done(results)
    todo = [(c, r) for c in cases for r in range(reps) if (c.id, r) not in done]
    say(f"{len(todo)} attempts to run ({len(done)} already done) on {model}")

    def one(case: Case, rep: int):
        tries, delay = 0, 2.0
        while True:
            tries += 1
            start = time.monotonic()
            try:
                found, prompt, served, call, stop = _attempt(
                    session_factory, llm_factory, case, model, mode
                )
                return case, rep, found, prompt, served, call, stop, time.monotonic() - start, tries
            except LLMError as exc:
                text = str(exc)
                if tries < 4 and re.search(r"RateLimit|Overloaded|529|429|InternalServer", text):
                    time.sleep(delay + random.random() * delay)
                    delay *= 2
                    continue
                kind = (
                    "timeout"
                    if "Timeout" in text
                    else "refusal"
                    if "declined" in text
                    else "bad_answer"
                    if "schema" in text or "cut off" in text
                    else "api_error"
                )
                raise _Failed(kind, text, tries) from exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, c, r): (c, r) for c, r in todo}
        for fut in as_completed(futures):
            case, rep = futures[fut]
            try:
                case, rep, found, prompt, served, call, stop, latency, tries = fut.result()
            except _Failed as exc:
                _append(
                    errors,
                    {
                        "prompt_id": case.id,
                        "rep": rep,
                        "class": exc.kind,
                        "error": exc.text[:500],
                        "tries": exc.tries,
                    },
                )
                continue
            if mode == "agent" and not str(served).startswith(model):
                _append(
                    errors,
                    {
                        "prompt_id": case.id,
                        "rep": rep,
                        "class": "model_mismatch",
                        "error": f"asked for {model}, served by {served}",
                    },
                )
                continue
            doc, _ = case.filing()
            text = agent.filing_text(doc)
            scores = grade(case.expected, found, text)
            trace = [
                {"role": "system", "content": agent.SYSTEM},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": json.dumps({"events": found}, indent=1)},
            ]
            (out / "traces" / f"{case.id}_rep{rep}.json").write_text(json.dumps(trace, indent=1))
            row = {
                "prompt_id": case.id,
                "rep": rep,
                "prompt": f"{case.data.get('symbol')}: {case.data['title']}",
                "tags": [case.data.get("stratum", "?"), case.data.get("doc_type") or "?"],
                "status": "ok",
                "stop_reason": stop,
                "grade": scores,
                "model": served,
                "latency_s": round(latency, 2),
                "tries": tries,
                "meta": {
                    "expected": len(case.expected),
                    "found": len(found),
                    "verified": case.verified,
                    "mode": mode,
                    "expected_events": [_brief(e) for e in case.expected],
                    "found_events": [_brief(e) for e in found],
                },
            }
            if call is not None:
                row.update(call)
            _append(results, row)
    summary = summarize(results, errors)
    (out / "summary.md").write_text(summary["markdown"])
    if mode == "agent" and session_factory is not None:
        with session_factory() as session:
            record(session, variant, model, cases, results, errors, summary)
            session.commit()
    return summary


def record(session, variant, model, cases, results: Path, errors: Path, summary: dict):
    """Keep this run in the database (eval_runs, eval_results) for the Agent evals page:
    the scores over every graded run of the variant so far, and each case's runs."""
    from stock_news_analyzer.models import EvalResult, EvalRun

    rows = _rows(results)
    errs = _rows(errors)
    graded = {(r["prompt_id"], r["rep"]) for r in rows}
    open_errors = [e for e in errs if (e["prompt_id"], e["rep"]) not in graded]
    run = EvalRun(
        flow="events",
        variant=variant,
        model=model,
        prompt_version=agent.PROMPT_VERSION,
        cases=len(cases),
        cases_verified=sum(c.verified for c in cases),
        attempts=len(rows),
        errors=len(open_errors),
        scores={
            **summary["mean"],
            "margin": summary["margin"],
            "recall": summary["recall"],
            "precision": summary["precision"],
            "specificity": summary["specificity"],
            "passed": summary["passed"],
            "failed": summary["failed"],
        },
        cost_usd=Decimal(str(round(summary["cost_usd"], 5))),
        harness=harness_digest(),
    )
    session.add(run)
    session.flush()
    for r in rows:
        session.add(
            EvalResult(
                run_id=run.id,
                case_id=r["prompt_id"],
                rep=r["rep"],
                title=r.get("prompt"),
                tags=r.get("tags", []),
                grade=r["grade"],
                detail={k: r["meta"].get(k) for k in ("expected_events", "found_events")},
                latency_s=r.get("latency_s"),
                cost_usd=Decimal(str(r.get("cost_usd", 0))),
            )
        )
    for e in open_errors:
        session.add(
            EvalResult(
                run_id=run.id,
                case_id=e["prompt_id"],
                rep=e["rep"],
                error=f"{e['class']}: {e.get('error', '')}"[:500],
            )
        )
    return run


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _brief(e: dict) -> dict:
    return {k: e.get(k) for k in ("event_type", "value_cr", "headline") if e.get(k) is not None}


class _Failed(Exception):
    def __init__(self, kind: str, text: str, tries: int):
        super().__init__(text)
        self.kind, self.text, self.tries = kind, text, tries


def _append(path: Path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def summarize(results: Path, errors: Path) -> dict:
    rows, errs = _rows(results), _rows(errors)
    n = len(rows)
    mean = {m["id"]: (sum(r["grade"][m["id"]] for r in rows) / n if n else 0.0) for m in METRICS}
    p = mean["correct"]
    margin = 1.96 * math.sqrt(p * (1 - p) / n) if n else 0.0
    pos = [r for r in rows if r["meta"]["expected"]]
    neg = [r for r in rows if not r["meta"]["expected"]]
    flagged = [r for r in rows if r["meta"]["found"]]
    recall = sum(r["meta"]["found"] > 0 for r in pos) / len(pos) if pos else None
    specificity = sum(r["meta"]["found"] == 0 for r in neg) / len(neg) if neg else None
    precision = sum(r["meta"]["expected"] > 0 for r in flagged) / len(flagged) if flagged else None
    cost = sum(r.get("cost_usd", 0) for r in rows)
    lat = sorted(r["latency_s"] for r in rows)

    def pct(v):
        return "-" if v is None else f"{v:.0%}"

    lines = [
        f"# Event extraction eval: {n} graded attempts, {len(errs)} failed",
        "",
        f"**Correct: {p:.0%}** (±{margin:.0%}, 95%)",
        "",
        "| Metric | Mean |",
        "| --- | --- |",
        *[f"| {m['label']} | {mean[m['id']]:.0%} |" for m in METRICS],
        f"| Recall (filings with events) | {pct(recall)} |",
        f"| Precision (filings it found events in) | {pct(precision)} |",
        f"| Specificity (filings without) | {pct(specificity)} |",
        "",
        f"Cost ${cost:.4f}; latency median {lat[len(lat) // 2] if lat else 0:.1f} s.",
        "",
        "## Cases not fully correct",
        "",
    ]
    by_case: dict[str, list] = {}
    for r in rows:
        by_case.setdefault(r["prompt_id"], []).append(r)
    for cid, rs_ in sorted(by_case.items()):
        bad = [r for r in rs_ if r["grade"]["correct"] < 1]
        if bad:
            g = bad[0]["grade"]
            lines.append(
                f"- {cid} ({rs_[0]['tags'][0]}): wrong in {len(bad)} of {len(rs_)}; "
                f"expected {bad[0]['meta']['expected']}, found {bad[0]['meta']['found']}; "
                + ", ".join(f"{k} {v:g}" for k, v in g.items())
            )
    if errs:
        lines += ["", "## Failed attempts", ""]
        lines += [
            f"- {e['prompt_id']} rep {e['rep']}: {e['class']} {e.get('error', '')[:120]}"
            for e in errs
        ]
    passed = sum(all(r["grade"]["correct"] == 1 for r in rs_) for rs_ in by_case.values())
    return {
        "n": n,
        "errors": len(errs),
        "passed": passed,
        "failed": len(by_case) - passed,
        "mean": mean,
        "margin": margin,
        "recall": recall,
        "precision": precision,
        "specificity": specificity,
        "cost_usd": cost,
        "markdown": "\n".join(lines) + "\n",
    }
