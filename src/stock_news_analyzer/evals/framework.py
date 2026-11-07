"""The eval framework: one way to measure any AI agent (docs/evals.md).

An eval is a **dataset** of cases (`eval_cases`: the agent's input, frozen, and the expected
answer), a **target** (the agent's own entry point, called on one case) and **graders** (code
that scores the answer against the expected one). Each agent's eval is a `Spec` in
`evals/<name>.py`, registered in `evals/__init__.py`; the runner, the record of runs, the
commands (`sna eval <name> ...`) and the Agent evals page are shared.

A spec says:
- how to `sample` cases from your database (and whether their answers come with them, like
  XBRL figures, or need drafting and checking);
- how to `draft` an answer for you to check (a stronger model than the one under test);
- how to `call` the agent on one case, and `grade` its answer;
- how to `describe` an answer in a line or two, for tables and the dashboard.

Runs write `.claude/hillclimb/<name>/<variant>/` (results.jsonl, traces/, errors.jsonl,
summary.md) and a row in `eval_runs` with each case's runs in `eval_results`.
"""

import hashlib
import json
import math
import random
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.models import EvalCase, EvalResult, EvalRun

ROOT = Path(__file__).resolve().parents[3]
STATUSES = ("new", "draft", "verified", "excluded")


@dataclass
class NewCase:
    """A case as a spec samples it, before it is stored."""

    key: str
    title: str
    input: dict
    tags: list[str] = field(default_factory=list)
    source: str = "sample"
    reference: dict | None = None  # when the answer comes with the case (an exact source)
    drafted_by: str | None = None


@dataclass
class Answer:
    """What the agent said on one case, and what it was sent."""

    output: dict
    prompt: str
    model: str
    stop_reason: str | None = None
    usage: dict | None = None
    cost_usd: float = 0.0


class Spec:
    """One agent's eval. Subclasses fill in the parts below."""

    name: str = ""  # the dataset and command name, e.g. 'events'
    agent: str = ""  # the agent's job on the Agent map, e.g. 'events'
    title: str = ""
    system: str = ""  # the agent's instructions, for traces
    prompt_version: str | None = None
    metrics: list[dict] = []  # [{id, label, kind}], the headline first
    needs_checking = True  # answers are drafted, then checked by you
    code: tuple = ()  # the agent's modules: a result made with other code isn't resumed
    default_n = 40

    def default_model(self) -> str:
        raise NotImplementedError

    def sample(self, session: Session, n: int, seed: int, taken: set[str]) -> list[NewCase]:
        raise NotImplementedError

    def draft(self, llm, case: EvalCase, model: str) -> dict:
        raise NotImplementedError

    def call(self, llm, case: EvalCase, model: str, system: str | None = None) -> Answer:
        """Call the agent on one case. `system`, when given, replaces the agent's instructions
        (an experiment); otherwise the agent's own entry point is used as is."""
        raise NotImplementedError

    def grade(self, case: EvalCase, output: dict) -> dict[str, float]:
        raise NotImplementedError

    def describe(self, answer: dict | None) -> list[str]:
        """An answer (expected or found) as short lines."""
        return [json.dumps(answer)] if answer else []

    def row_meta(self, case: EvalCase, output: dict) -> dict:
        """Extra facts kept with each graded run, for `stats`; none by default."""
        return {}

    def stats(self, rows: list[dict]) -> dict[str, float | None]:
        """Extra numbers over all graded runs (e.g. recall), labelled; none by default."""
        return {}

    # --- for labelling in the dashboard (the Eval cases page) ---------------------------

    editable = True  # answers can be edited on the page (False: they come with the case)
    # The answer as a table: [{"name", "label", "kind": select|number|text, "options"}]
    editor_columns: list[dict] = []

    def editor_rows(self, reference: dict | None) -> list[dict]:
        """An answer as the page's table rows."""
        return []

    def from_editor(self, rows: list[dict]) -> dict:
        """The page's table rows back as an answer."""
        return {}

    def empty(self) -> dict | None:
        """The answer meaning "nothing to find" (e.g. no event), if there is one."""
        return None

    def show(self, case: EvalCase) -> dict:
        """What the agent read, for the page: {"heading", "facts": [str], "text"}."""
        return {"heading": case.title or case.key, "facts": [], "text": json.dumps(case.input)}

    def case_for(self, session: Session, ref: int) -> "NewCase | None":
        """One item (e.g. a filing by id) as a case, to add it to the eval by hand."""
        return None

    def oracle(self, case: EvalCase) -> dict:
        """An output the grader must score as fully right (to test the grader)."""
        return dict(case.reference or {})

    def null(self, case: EvalCase) -> dict:
        """An empty output (to test the grader)."""
        return {}

    @property
    def flow(self) -> Path:
        return ROOT / ".claude" / "hillclimb" / self.name

    @property
    def folder(self) -> Path:
        return ROOT / "evals" / self.name / "cases"


# ------------------------------------------------------------------ cases


def cases(session: Session, spec: Spec, status: str | None = None) -> list[EvalCase]:
    query = select(EvalCase).where(EvalCase.dataset == spec.name).order_by(EvalCase.key)
    if status:
        query = query.where(EvalCase.status == status)
    return list(session.scalars(query))


def set_answer(
    case: EvalCase,
    reference: dict | None,
    status: str,
    by: str,
    note: str | None = None,
) -> None:
    """Change a case's answer or status, keeping what it was in its history."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    case.history = [
        *(case.history or []),
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "by": by,
            "status": case.status,
            "reference": case.reference,
            "note": case.note,
        },
    ]
    case.reference, case.status = reference, status
    if note is not None:
        case.note = note


def sample(session: Session, spec: Spec, n: int | None = None, seed: int = 7) -> list[EvalCase]:
    """New cases from your database, added to the dataset (none already in it)."""
    taken = {c.key for c in cases(session, spec)}
    added = []
    for new in spec.sample(session, n or spec.default_n, seed, taken):
        if new.key in taken:
            continue
        case = EvalCase(
            dataset=spec.name,
            key=new.key,
            source=new.source,
            title=new.title,
            tags=new.tags,
            input=new.input,
            reference=new.reference,
            status="verified"
            if new.reference is not None and not spec.needs_checking
            else "draft"
            if new.reference is not None
            else "new",
            drafted_by=new.drafted_by,
            history=[],
        )
        session.add(case)
        added.append(case)
        taken.add(new.key)
    session.flush()
    return added


def add_case(session: Session, spec: Spec, new: NewCase) -> EvalCase | None:
    """Add one case by hand (from the dashboard); None if it is already in the eval."""
    exists = session.scalar(
        select(EvalCase).where(EvalCase.dataset == spec.name, EvalCase.key == new.key)
    )
    if exists is not None:
        return None
    case = EvalCase(
        dataset=spec.name,
        key=new.key,
        source=new.source,
        title=new.title,
        tags=new.tags,
        input=new.input,
        reference=new.reference,
        status="new" if new.reference is None else "draft",
        drafted_by=new.drafted_by,
        history=[],
    )
    session.add(case)
    session.flush()
    return case


def draft(session: Session, spec: Spec, llm, model: str, say=print) -> int:
    """Draft answers for cases that have none, saving each as it comes. An API error stops
    the run there; running it again continues."""
    from stock_news_analyzer.llm import LLMError

    done = 0
    for case in cases(session, spec, "new"):
        try:
            reference = spec.draft(llm, case, model)
        except LLMError as exc:
            say(f"Stopped at {case.key}: {exc}")
            say(f"{done} drafted this time; run draft again to continue from {case.key}.")
            break
        set_answer(case, reference, "draft", model)
        case.drafted_by = model
        session.commit()
        done += 1
        say(f"{case.key}: {'; '.join(spec.describe(reference)) or 'nothing'}")
    return done


def overview(spec: Spec, items: list[EvalCase]) -> str:
    """The cases as a Markdown table, for reviewing them."""
    lines = [
        "| Case | Title | Tags | Expected | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in items:
        expected = "; ".join(spec.describe(c.reference)) if c.reference is not None else ""
        lines.append(
            f"| {c.key} | {c.title or ''} | {', '.join(c.tags or [])} | "
            f"{expected or ('*not drafted*' if c.status == 'new' else 'none')} | {c.status} |"
        )
    count = {s: sum(c.status == s for c in items) for s in STATUSES}
    lines += [
        "",
        f"{len(items)} cases: " + ", ".join(f"{v} {k}" for k, v in count.items() if v) + ".",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ YAML files (for git)


class _Literal(str):
    pass


yaml.add_representer(
    _Literal, lambda dumper, s: dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")
)


def _readable(value):
    if isinstance(value, str) and "\n" in value:
        return _Literal(value.rstrip() + "\n")
    if isinstance(value, dict):
        return {k: _readable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_readable(v) for v in value]
    return value


def export(session: Session, spec: Spec, folder: Path | None = None) -> int:
    """Write every case to `evals/<name>/cases/<key>.yaml`, to keep the dataset in git."""
    folder = folder or spec.folder
    folder.mkdir(parents=True, exist_ok=True)
    items = cases(session, spec)
    for c in items:
        data = {
            "key": c.key,
            "title": c.title,
            "source": c.source,
            "tags": c.tags,
            "status": c.status,
            "drafted_by": c.drafted_by,
            "note": c.note,
            "reference": c.reference,
            "input": c.input,
        }
        (folder / f"{c.key}.yaml").write_text(
            yaml.dump(_readable(data), sort_keys=False, allow_unicode=True, width=100)
        )
    return len(items)


def import_files(session: Session, spec: Spec, folder: Path | None = None) -> int:
    """Read `evals/<name>/cases/*.yaml` into the dataset: new cases are added, and a case
    whose answer or status in the file differs from the database's is updated (its earlier
    answer kept in its history). Returns the cases added or changed."""
    folder = folder or spec.folder
    have = {c.key: c for c in cases(session, spec)}
    changed = 0
    for path in sorted(folder.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        data = spec.from_file(data) if hasattr(spec, "from_file") else data
        key = str(data["key"])
        case = have.get(key)
        if case is None:
            session.add(
                EvalCase(
                    dataset=spec.name,
                    key=key,
                    source=data.get("source") or "file",
                    title=data.get("title"),
                    tags=data.get("tags") or [],
                    input=data["input"],
                    reference=data.get("reference"),
                    status=data.get("status") or "new",
                    drafted_by=data.get("drafted_by"),
                    note=data.get("note"),
                    history=[],
                )
            )
            changed += 1
        elif (case.reference, case.status, case.note) != (
            data.get("reference"),
            data.get("status") or case.status,
            data.get("note"),
        ):
            set_answer(
                case,
                data.get("reference"),
                data.get("status") or case.status,
                "file",
                data.get("note"),
            )
            changed += 1
    session.flush()
    return changed


# ------------------------------------------------------------------ running


class HarnessChanged(RuntimeError):
    pass


def harness_files(spec: Spec) -> list[Path]:
    import inspect

    return [Path(__file__), Path(inspect.getfile(type(spec)))]


def harness_digest(spec: Spec) -> str:
    h = hashlib.sha256()
    for p in harness_files(spec):
        h.update(p.read_bytes())
    return h.hexdigest()


def attempt_version(spec: Spec, case: EvalCase, model: str, system: str | None) -> str:
    """What an attempt depends on: the agent's code, the model, the instructions, and the
    case's input and answer. A result kept with another version is run again, not resumed."""
    import inspect

    h = hashlib.sha256()
    for m in spec.code:
        h.update(Path(inspect.getfile(m)).read_bytes())
    h.update(f"{model}\n{system or ''}\n".encode())
    h.update(json.dumps([case.input, case.reference], sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def check_harness(spec: Spec, approve: bool, flow: Path | None = None) -> None:
    """Refuse to run when the runner or the spec's grader changed since you approved them."""
    flow = flow or spec.flow
    stamp = flow / "harness.sha256"
    now = harness_digest(spec)
    if approve:
        flow.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now + "\n")
        return
    if not stamp.exists() or stamp.read_text().strip() != now:
        raise HarnessChanged(
            "the eval's runner or grader is new or changed: read it, then run once with "
            "--approve-harness"
        )


def write_state(spec: Spec, flow: Path | None = None) -> None:
    flow = flow or spec.flow
    flow.mkdir(parents=True, exist_ok=True)
    state = {
        "flow": spec.name,
        "metrics": spec.metrics,
        "perf_fields": ["latency_s", "usage", "cost_usd"],
        "harness_paths": [str(p.relative_to(ROOT)) for p in harness_files(spec)],
    }
    (flow / "_state.json").write_text(json.dumps(state, indent=1) + "\n")


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _append(path: Path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


class _Failed(Exception):
    def __init__(self, kind: str, text: str, tries: int):
        super().__init__(text)
        self.kind, self.text, self.tries = kind, text, tries


def _kind(text: str) -> str:
    if "Timeout" in text:
        return "timeout"
    if "declined" in text:
        return "refusal"
    if "schema" in text or "cut off" in text:
        return "bad_answer"
    if "credit balance" in text:
        return "no_credit"
    return "api_error"


def run(
    session_factory,
    llm_factory,
    spec: Spec,
    items: list[EvalCase],
    *,
    variant: str = "baseline",
    model: str,
    reps: int = 3,
    workers: int = 4,
    mode: str = "agent",
    approve_harness: bool = False,
    flow: Path | None = None,
    system: str | None = None,
    system_file: str | None = None,
    note: str | None = None,
    say=print,
) -> dict:
    """Run the agent on every case `reps` times, grade, write results and keep the run;
    returns the summary. `mode` 'oracle' or 'null' feeds the grader the expected answer or
    nothing instead of calling the agent (free; tests the grader)."""
    from stock_news_analyzer.llm import LLMError

    flow = flow or spec.flow
    if mode == "agent":
        check_harness(spec, approve_harness, flow)
    write_state(spec, flow)
    out = flow / variant
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results, errors = out / "results.jsonl", out / "errors.jsonl"
    version = {c.key: attempt_version(spec, c, model, system) for c in items}
    kept, stale = [], []
    for r in _rows(results):
        current = r.get("version") == version.get(r["prompt_id"], r.get("version"))
        (kept if current else stale).append(r)
    if stale:  # made with other code, instructions, model or answer: set aside, run again
        with (out / "results.stale.jsonl").open("a") as f:
            f.writelines(json.dumps(r, default=str) + "\n" for r in stale)
        results.write_text("".join(json.dumps(r, default=str) + "\n" for r in kept))
        say(
            f"{len(stale)} earlier attempts were made with other code, instructions, model or "
            "answers; they are run again (the old ones are in results.stale.jsonl)"
        )
    wanted = [(c, r) for c in items for r in range(reps)]
    done = {(r["prompt_id"], r["rep"]) for r in kept}
    todo = [(c, r) for c, r in wanted if (c.key, r) not in done]
    say(f"{len(todo)} attempts to run ({len(wanted) - len(todo)} already done) on {model}")

    def one(case: EvalCase, rep: int):
        if mode in ("oracle", "null"):
            output = spec.oracle(case) if mode == "oracle" else spec.null(case)
            return case, rep, Answer(output, "", model, "end_turn"), 0.0, 1
        tries, delay = 0, 2.0
        while True:
            tries += 1
            start = time.monotonic()
            try:
                with session_factory() as session:
                    answer = spec.call(llm_factory(session), case, model, system)
                    session.commit()
                return case, rep, answer, time.monotonic() - start, tries
            except LLMError as exc:
                text = str(exc)
                if tries < 4 and re.search(r"RateLimit|Overloaded|529|429|InternalServer", text):
                    time.sleep(delay + random.random() * delay)
                    delay *= 2
                    continue
                raise _Failed(_kind(text), text, tries) from exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, c, r): (c, r) for c, r in todo}
        for fut in as_completed(futures):
            case, rep = futures[fut]
            try:
                case, rep, answer, latency, tries = fut.result()
            except _Failed as exc:
                _append(
                    errors,
                    {
                        "prompt_id": case.key,
                        "rep": rep,
                        "class": exc.kind,
                        "error": exc.text[:500],
                        "tries": exc.tries,
                    },
                )
                continue
            if mode == "agent" and not str(answer.model).startswith(model):
                _append(
                    errors,
                    {
                        "prompt_id": case.key,
                        "rep": rep,
                        "class": "model_mismatch",
                        "error": f"asked for {model}, served by {answer.model}",
                    },
                )
                continue
            scores = spec.grade(case, answer.output)
            trace = [
                {"role": "system", "content": system or spec.system},
                {"role": "user", "content": answer.prompt},
                {"role": "assistant", "content": json.dumps(answer.output, indent=1, default=str)},
            ]
            (out / "traces" / f"{case.key}_rep{rep}.json").write_text(json.dumps(trace, indent=1))
            row = {
                "prompt_id": case.key,
                "rep": rep,
                "version": version[case.key],
                "prompt": case.title,
                "tags": case.tags or [],
                "status": "ok",
                "stop_reason": answer.stop_reason,
                "grade": scores,
                "model": answer.model,
                "latency_s": round(latency, 2),
                "tries": tries,
                "meta": {
                    "status": case.status,
                    "mode": mode,
                    "expected": spec.describe(case.reference),
                    "found": spec.describe(answer.output),
                    **spec.row_meta(case, answer.output),
                },
            }
            if answer.usage is not None:
                row["usage"] = answer.usage
                row["cost_usd"] = answer.cost_usd
            _append(results, row)
    keys = {c.key for c in items}
    summary = summarize(spec, results, errors, keys)
    (out / "summary.md").write_text(summary["markdown"])
    config = run_config(spec, model, system, system_file)
    if variant != "baseline":
        (out / "change.md").write_text(
            f"{note or 'A variant'}\n\nModel: {model}. Instructions: {config['instructions']}"
            + (f" (from {system_file})" if system_file else "")
            + ".\n"
        )
    if mode == "agent" and session_factory is not None:
        with session_factory() as session:
            run_row = record(session, spec, variant, model, items, results, errors, summary, keys)
            run_row.config, run_row.note = config, note
            session.commit()
    return summary


def run_config(spec: Spec, model: str, system: str | None, system_file: str | None) -> dict:
    """What a run used: the model, and the agent's own instructions or which others."""
    if system is None or system == spec.system:
        return {"model": model, "instructions": "the agent's own"}
    digest = hashlib.sha256(system.encode()).hexdigest()[:12]
    return {
        "model": model,
        "instructions": f"changed ({digest})",
        "file": system_file,
        "system": system,
    }


def _current(results: Path, errors: Path, keys: set[str] | None):
    """The graded attempts on the run's cases (an excluded case's earlier ones left out), and
    the failed attempts not graded since."""
    rows = [r for r in _rows(results) if keys is None or r["prompt_id"] in keys]
    graded = {(r["prompt_id"], r["rep"]) for r in rows}
    errs = [
        e
        for e in _rows(errors)
        if (keys is None or e["prompt_id"] in keys) and (e["prompt_id"], e["rep"]) not in graded
    ]
    return rows, errs


def summarize(spec: Spec, results: Path, errors: Path, keys: set[str] | None = None) -> dict:
    rows, errs = _current(results, errors, keys)
    n = len(rows)
    ids = [m["id"] for m in spec.metrics]
    mean = {k: (sum(r["grade"].get(k, 0) for r in rows) / n if n else 0.0) for k in ids}
    head = ids[0]
    p = mean[head]
    margin = 1.96 * math.sqrt(p * (1 - p) / n) if n else 0.0
    extra = spec.stats(rows)
    by_case: dict[str, list] = {}
    for r in rows:
        by_case.setdefault(r["prompt_id"], []).append(r)
    passed = sum(all(r["grade"][head] == 1 for r in rs) for rs in by_case.values())
    cost = sum(r.get("cost_usd", 0) for r in rows)
    lat = sorted(r["latency_s"] for r in rows)
    labels = {m["id"]: m["label"] for m in spec.metrics}

    def pct(v):
        return "-" if v is None else f"{v:.0%}"

    lines = [
        f"# {spec.title} eval: {n} graded attempts, {len(errs)} failed",
        "",
        f"**{labels[head]}: {p:.0%}** (±{margin:.0%}, 95%); {passed} of {len(by_case)} cases "
        "right in every run",
        "",
        "| Metric | Mean |",
        "| --- | --- |",
        *[f"| {labels[k]} | {mean[k]:.0%} |" for k in ids],
        *[f"| {k} | {pct(v)} |" for k, v in extra.items()],
        "",
        f"Cost ${cost:.4f}; latency median {lat[len(lat) // 2] if lat else 0:.1f} s.",
        "",
        "## Cases not fully right",
        "",
    ]
    for key, rs in sorted(by_case.items()):
        bad = [r for r in rs if r["grade"][head] < 1]
        if bad:
            g = bad[0]["grade"]
            lines.append(
                f"- {key} ({', '.join(rs[0]['tags'][:1])}): wrong in {len(bad)} of {len(rs)}; "
                f"expected {'; '.join(bad[0]['meta']['expected']) or 'nothing'}; found "
                f"{'; '.join(bad[0]['meta']['found']) or 'nothing'}; "
                + ", ".join(f"{k} {v:g}" for k, v in g.items())
            )
    if errs:
        lines += ["", "## Failed attempts", ""]
        lines += [
            f"- {e['prompt_id']} rep {e['rep']}: {e['class']} {e.get('error', '')[:120]}"
            for e in errs
        ]
    return {
        "n": n,
        "errors": len(errs),
        "passed": passed,
        "failed": len(by_case) - passed,
        "mean": mean,
        "margin": margin,
        "stats": extra,
        "cost_usd": cost,
        "markdown": "\n".join(lines) + "\n",
    }


def record(
    session, spec: Spec, variant, model, items, results: Path, errors: Path, summary, keys=None
):
    """Keep the run in the database for the Agent evals page: the scores over the variant's
    graded attempts on the run's cases, and each case's attempts."""
    rows, open_errors = _current(results, errors, keys)
    run_row = EvalRun(
        flow=spec.name,
        variant=variant,
        model=model,
        prompt_version=spec.prompt_version,
        cases=len(items),
        cases_verified=sum(c.status == "verified" for c in items),
        attempts=len(rows),
        errors=len(open_errors),
        scores={
            **summary["mean"],
            "margin": summary["margin"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "stats": summary["stats"],
        },
        cost_usd=Decimal(str(round(summary["cost_usd"], 5))),
        harness=harness_digest(spec),
    )
    session.add(run_row)
    session.flush()
    for r in rows:
        session.add(
            EvalResult(
                run_id=run_row.id,
                case_id=r["prompt_id"],
                rep=r["rep"],
                title=r.get("prompt"),
                tags=r.get("tags", []),
                grade=r["grade"],
                detail={"expected": r["meta"]["expected"], "found": r["meta"]["found"]},
                latency_s=r.get("latency_s"),
                cost_usd=Decimal(str(r.get("cost_usd", 0))),
            )
        )
    for e in open_errors:
        session.add(
            EvalResult(
                run_id=run_row.id,
                case_id=e["prompt_id"],
                rep=e["rep"],
                error=f"{e['class']}: {e.get('error', '')}"[:500],
            )
        )
    return run_row


def runnable(items: list[EvalCase], unverified: bool) -> tuple[list[EvalCase], list[str]]:
    """The cases a run uses (not excluded; checked, unless `unverified`), and those held back
    for want of a check."""
    live = [c for c in items if c.status != "excluded"]
    waiting = [c.key for c in live if c.status != "verified"]
    if unverified:
        return [c for c in live if c.reference is not None], waiting
    return [c for c in live if c.status == "verified"], waiting


def factory(engine) -> Callable[[], Session]:
    return lambda: Session(engine)


# ------------------------------------------------------------------ experiments compared


def _by_case(session: Session, run_id: int) -> dict[str, dict]:
    """A run's cases: the mean of each metric over its graded runs, a detail (from a wrong
    run when there is one), cost and latency of its attempts, failed calls."""
    out: dict[str, dict] = {}
    for r in session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)):
        c = out.setdefault(
            r.case_id,
            {
                "title": r.title,
                "grades": [],
                "detail": None,
                "cost": [],
                "latency": [],
                "errors": 0,
            },
        )
        if r.error:
            c["errors"] += 1
            continue
        c["title"] = c["title"] or r.title
        c["grades"].append(r.grade or {})
        c["cost"].append(float(r.cost_usd or 0))
        if r.latency_s is not None:
            c["latency"].append(r.latency_s)
        if c["detail"] is None or (r.grade or {}).get("correct", 1) < 1:
            c["detail"] = r.detail
    for c in out.values():
        keys = {k for g in c["grades"] for k in g}
        c["mean"] = {k: sum(g.get(k, 0) for g in c["grades"]) / len(c["grades"]) for k in keys}
    return out


def _excluded(session: Session, spec: Spec) -> set[str]:
    """The cases excluded since: a comparison leaves them out."""
    return {c.key for c in cases(session, spec) if c.status == "excluded"}


def compare(session: Session, spec: Spec, a_id: int, b_id: int) -> dict:
    """Run B against run A, case by case, on the cases both graded: which got better and which
    worse, the change in each metric, cost and latency, and a verdict on the headline metric
    from the paired differences (better or worse only when the 95% interval of the mean
    difference leaves out zero)."""
    a_run, b_run = session.get(EvalRun, a_id), session.get(EvalRun, b_id)
    a, b = _by_case(session, a_id), _by_case(session, b_id)
    excluded = _excluded(session, spec)
    common = sorted(
        k for k in a.keys() & b.keys() if a[k]["grades"] and b[k]["grades"] and k not in excluded
    )
    head = spec.metrics[0]["id"]
    diffs = [b[k]["mean"].get(head, 0) - a[k]["mean"].get(head, 0) for k in common]
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    low, high = mean - 1.96 * se, mean + 1.96 * se
    if n < 5:
        verdict = "too few cases to tell"
    elif low > 0:
        verdict = "better"
    elif high < 0:
        verdict = "worse"
    else:
        verdict = "no clear difference"

    def side(data: dict, keys: list[str]) -> dict:
        metric_ids = [m["id"] for m in spec.metrics]
        rows = [data[k] for k in keys]
        cost = [x for r in rows for x in r["cost"]]
        lat = sorted(x for r in rows for x in r["latency"])
        return {
            **{
                m: (sum(r["mean"].get(m, 0) for r in rows) / len(rows) if rows else None)
                for m in metric_ids
            },
            "cost_per_case": sum(cost) / len(cost) if cost else 0.0,
            "latency_median": lat[len(lat) // 2] if lat else None,
            "failed_calls": sum(r["errors"] for r in rows),
        }

    cases = [
        {
            "case": k,
            "title": b[k]["title"] or a[k]["title"],
            "a": a[k]["mean"].get(head, 0),
            "b": b[k]["mean"].get(head, 0),
            "a_detail": a[k]["detail"] or {},
            "b_detail": b[k]["detail"] or {},
        }
        for k in common
    ]
    return {
        "a": {
            "id": a_id,
            "variant": a_run.variant,
            "model": a_run.model,
            "config": a_run.config or {},
            "note": a_run.note,
            **side(a, common),
        },
        "b": {
            "id": b_id,
            "variant": b_run.variant,
            "model": b_run.model,
            "config": b_run.config or {},
            "note": b_run.note,
            **side(b, common),
        },
        "cases": len(common),
        "only_a": sorted(a.keys() - b.keys() - excluded),
        "excluded": sorted((a.keys() | b.keys()) & excluded),
        "only_b": sorted(b.keys() - a.keys() - excluded),
        "difference": mean,
        "interval": (low, high),
        "verdict": verdict,
        "improved": sorted((c for c in cases if c["b"] > c["a"]), key=lambda c: c["a"] - c["b"]),
        "regressed": sorted((c for c in cases if c["b"] < c["a"]), key=lambda c: c["b"] - c["a"]),
        "same": sum(c["a"] == c["b"] for c in cases),
    }


def latest_runs(session: Session, spec: Spec) -> dict[str, EvalRun]:
    """The latest run of each variant."""
    out: dict[str, EvalRun] = {}
    for r in session.scalars(
        select(EvalRun)
        .where(EvalRun.flow == spec.name)
        .order_by(EvalRun.finished_at.desc(), EvalRun.id.desc())
    ):
        out.setdefault(r.variant, r)
    return out


def comparison_markdown(spec: Spec, c: dict) -> str:
    """A comparison as text, for the terminal."""
    labels = {m["id"]: m["label"] for m in spec.metrics}
    a, b = c["a"], c["b"]
    lines = [
        f"# {b['variant']} against {a['variant']} ({spec.title}, {c['cases']} cases in both)",
        "",
        f"**Verdict: {c['verdict']}.** {labels[spec.metrics[0]['id']]} "
        f"{100 * c['difference']:+.1f} points (95%: {100 * c['interval'][0]:+.1f} to "
        f"{100 * c['interval'][1]:+.1f}); {len(c['improved'])} cases better, "
        f"{len(c['regressed'])} worse, {c['same']} the same.",
        "",
        f"| | {a['variant']} | {b['variant']} |",
        "| --- | --- | --- |",
        f"| Model | {a['model']} | {b['model']} |",
        f"| Instructions | {a['config'].get('instructions', 'not recorded')} | "
        f"{b['config'].get('instructions', 'not recorded')} |",
        *[f"| {labels[m]} | {a[m]:.0%} | {b[m]:.0%} |" for m in labels if a[m] is not None],
        f"| Cost a case | ${a['cost_per_case']:.5f} | ${b['cost_per_case']:.5f} |",
        f"| Median seconds | {a['latency_median'] or 0:.1f} | {b['latency_median'] or 0:.1f} |",
        f"| Failed calls | {a['failed_calls']} | {b['failed_calls']} |",
    ]
    for title, group in (("Worse", c["regressed"]), ("Better", c["improved"])):
        if group:
            lines += ["", f"## {title} in {b['variant']}", ""]
            lines += [f"- {x['case']} ({x['title']}): {x['a']:.0%} → {x['b']:.0%}" for x in group]
    if c.get("excluded"):
        lines += ["", f"Left out, excluded since: {', '.join(c['excluded'])}"]
    if b.get("note"):
        lines += ["", f"Why {b['variant']}: {b['note']}"]
    return "\n".join(lines) + "\n"
