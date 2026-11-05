"""The Event Extractor's eval (agents/events.py): does it find the events a filing announces, of
the right types and amounts, with quotes that are really in the filing?

Cases are filings frozen from your database (`sample`): ones the agent found events in, spread
over the event types (those you rejected first), and routine ones it found none in. Their
expected events are drafted by a stronger model and checked by you. The agent's raw answer is
graded by code, before the QA Checker corrects or rejects anything:

- `correct` (the headline): event or no event as expected, the same event types, and every
  expected amount right (within 1%).
- `detect`: an event found when there is one, none when there isn't.
- `types`: F1 of the event types found against those expected (1 when both are none).
- `amounts`: share of expected events whose amount (or its absence) is right.
- `quotes`: share of the events found whose quote is in the filing and holds its amount.

Over all runs: recall (filings with events in which it found one), precision (filings it found
events in that have them) and specificity (routine filings it left alone).
"""

import random
from collections import Counter
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import events as extractor
from stock_news_analyzer.agents import results as rs
from stock_news_analyzer.agents.concalls import _norm, quote_in
from stock_news_analyzer.evals.framework import Answer, NewCase, Spec
from stock_news_analyzer.models import Company, Document, EvalCase, Event, EventFiling

TEXT_CHARS = 30_000  # of a filing's text frozen in a case (the agent reads less)
AMOUNT_TOLERANCE = Decimal("0.01")
DRAFT_MODEL = "claude-opus-5-5"


def filing(data: dict) -> tuple[Document, Company]:
    """A case's filing and company as the agent receives them (not added to any session)."""
    doc = Document(
        id=int(data["document_id"]),
        title=data["title"],
        subject=data.get("subject"),
        text=data.get("text"),
        text_status=data.get("text_status") or "pending",
        published_at=datetime.fromisoformat(str(data["published_at"])),
        doc_type=data.get("doc_type") or "",
    )
    company = Company(isin=data["isin"], name=data["company"], nse_symbol=data.get("symbol"))
    return doc, company


def _input(doc: Document, company: Company) -> dict:
    return {
        "document_id": doc.id,
        "company": company.name,
        "symbol": company.nse_symbol,
        "isin": company.isin,
        "published_at": doc.published_at.isoformat(),
        "doc_type": doc.doc_type,
        "title": doc.title,
        "subject": doc.subject,
        "text_status": doc.text_status,
        "text": (doc.text or "")[:TEXT_CHARS],
    }


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


class EventsSpec(Spec):
    name = "events"
    agent = "events"
    title = "Event Extractor"
    system = extractor.SYSTEM
    prompt_version = extractor.PROMPT_VERSION
    metrics = [
        {"id": "correct", "label": "Correct", "kind": "binary"},
        {"id": "detect", "label": "Detect", "kind": "binary"},
        {"id": "types", "label": "Types F1", "kind": "continuous"},
        {"id": "amounts", "label": "Amounts", "kind": "continuous"},
        {"id": "quotes", "label": "Quotes found", "kind": "continuous"},
    ]
    default_n = 40

    def default_model(self) -> str:
        from stock_news_analyzer.config import get_settings

        return get_settings().llm_model_triage

    def sample(self, session: Session, n: int, seed: int, taken: set[str]) -> list[NewCase]:
        """About 60% filings the agent found events in, spread over the event types (those
        whose events you rejected first), and 40% it found none in. The first tag records
        what the agent said then, not the answer."""
        with_events = round(n * 0.625)
        without = n - with_events
        rng = random.Random(seed)
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
            key = f"doc{item[1].id}"
            if key in seen:
                return False
            seen.add(key)
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
        return [
            NewCase(
                key=f"doc{doc.id}",
                title=f"{company.nse_symbol or company.isin}: {doc.title}",
                input=_input(doc, company),
                tags=[stratum, doc.doc_type or "?"],
                source="rejected" if stratum.startswith("rejected:") else "sample",
            )
            for stratum, doc, company in picked
        ]

    def case_for(self, session: Session, document_id: int) -> NewCase | None:
        """One filing as a case (to add it to the eval from the dashboard)."""
        from stock_news_analyzer.models import DocumentCompany

        row = session.execute(
            select(Document, Company)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .join(Company, Company.isin == DocumentCompany.isin)
            .where(Document.id == document_id)
        ).first()
        if row is None:
            return None
        doc, company = row
        return NewCase(
            key=f"doc{doc.id}",
            title=f"{company.nse_symbol or company.isin}: {doc.title}",
            input=_input(doc, company),
            tags=["added", doc.doc_type or "?"],
            source="manual",
        )

    def draft(self, llm, case: EvalCase, model: str) -> dict:
        doc, company = filing(case.input)
        answer = llm.structured(
            "eval-draft",
            model,
            extractor.SYSTEM,
            extractor._prompt([(doc, company)]),
            extractor.EventsAnswer,
            effort="high",
            max_tokens=extractor.MAX_TOKENS,
        )
        found = answer.filings[0].events if answer.filings else []
        return {
            "events": [
                {
                    "event_type": e.event_type,
                    "value_cr": e.value_cr,
                    "value_as_written": e.value_as_written,
                    "headline": e.headline,
                }
                for e in found
            ]
        }

    def call(self, llm, case: EvalCase, model: str, system: str | None = None) -> Answer:
        doc, company = filing(case.input)
        prompt = extractor._prompt([(doc, company)])
        if system is None:  # the agent's own entry point
            answer = extractor._ask(llm, model, [(doc, company)])
        else:  # the same call with other instructions (an experiment)
            answer = llm.structured(
                "events",
                model,
                system,
                prompt,
                extractor.EventsAnswer,
                max_tokens=extractor.MAX_TOKENS,
            )
        found = next((f.events for f in answer.filings if f.id == doc.id), [])
        c = llm.last_call
        return Answer(
            output={"events": [e.model_dump() for e in found]},
            prompt=prompt,
            model=llm.last_model,
            stop_reason=llm.last_stop_reason,
            usage={
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cache_read_input_tokens": c.cache_read_tokens,
                "cache_creation_input_tokens": c.cache_write_tokens,
            },
            cost_usd=float(c.cost_usd),
        )

    def grade(self, case: EvalCase, output: dict) -> dict[str, float]:
        doc, _ = filing(case.input)
        expected = (case.reference or {}).get("events") or []
        return grade(expected, output.get("events") or [], extractor.filing_text(doc))

    def describe(self, answer: dict | None) -> list[str]:
        out = []
        for e in (answer or {}).get("events") or []:
            value = f" Rs {e['value_cr']:g} cr" if e.get("value_cr") is not None else ""
            headline = f": {e['headline']}" if e.get("headline") else ""
            out.append(f"{e['event_type']}{value}{headline}")
        return out

    editor_columns = [
        {
            "name": "event_type",
            "label": "Type",
            "kind": "select",
            "options": list(extractor.EVENT_TYPES),
        },
        {"name": "value_cr", "label": "Rs crore", "kind": "number"},
        {"name": "value_as_written", "label": "As written", "kind": "text"},
        {"name": "headline", "label": "Headline", "kind": "text"},
    ]

    def editor_rows(self, reference: dict | None) -> list[dict]:
        return [
            {c["name"]: e.get(c["name"]) for c in self.editor_columns}
            for e in (reference or {}).get("events") or []
        ]

    def from_editor(self, rows: list[dict]) -> dict:
        events = []
        for r in rows:
            kind = r.get("event_type")
            if not kind or kind not in extractor.EVENT_TYPES:
                continue
            value = r.get("value_cr")
            value = None if value is None or value != value else float(value)  # NaN: none
            text = {k: (r.get(k) or None) for k in ("value_as_written", "headline")}
            events.append({"event_type": kind, "value_cr": value, **text})
        return {"events": events}

    def empty(self) -> dict:
        return {"events": []}

    def show(self, case: EvalCase) -> dict:
        d = case.input
        doc, _ = filing(d)
        return {
            "heading": d.get("title") or case.key,
            "facts": [
                f"{d.get('company')} ({d.get('symbol') or d.get('isin')})",
                f"filed {str(d.get('published_at'))[:10]}",
                d.get("doc_type") or "",
                f"document {d.get('document_id')}",
            ],
            # what the agent reads: the title, subject and the start of the text
            "text": extractor.filing_text(doc),
        }

    def oracle(self, case: EvalCase) -> dict:
        events = (case.reference or {}).get("events") or []
        return {"events": [{**e, "quote": None, "value_as_written": None} for e in events]}

    def null(self, case: EvalCase) -> dict:
        return {"events": []}

    def row_meta(self, case: EvalCase, output: dict) -> dict:
        return {
            "expected_n": len((case.reference or {}).get("events") or []),
            "found_n": len(output.get("events") or []),
        }

    def stats(self, rows: list[dict]) -> dict[str, float | None]:
        pos = [r for r in rows if r["meta"]["expected_n"]]
        neg = [r for r in rows if not r["meta"]["expected_n"]]
        flagged = [r for r in rows if r["meta"]["found_n"]]
        return {
            "Recall": sum(r["meta"]["found_n"] > 0 for r in pos) / len(pos) if pos else None,
            "Precision": (
                sum(r["meta"]["expected_n"] > 0 for r in flagged) / len(flagged)
                if flagged
                else None
            ),
            "Specificity": (
                sum(r["meta"]["found_n"] == 0 for r in neg) / len(neg) if neg else None
            ),
        }

    def from_file(self, data: dict) -> dict:
        """Case files written by the first version of this eval (step 33: the filing at the
        top level, `expected:` with `verified` and `events`) read as the framework's."""
        if "input" in data:
            return data
        exp = data.get("expected") or {}
        drafted = exp.get("drafted_by") or exp.get("verified")
        keys = (
            "document_id",
            "company",
            "symbol",
            "isin",
            "published_at",
            "doc_type",
            "title",
            "subject",
            "text_status",
            "text",
        )
        stratum = str(data.get("stratum") or "?")
        return {
            "key": str(data["id"]),
            "title": f"{data.get('symbol') or data.get('isin')}: {data.get('title')}",
            "source": "rejected" if stratum.startswith("rejected") else "sample",
            "tags": [stratum, data.get("doc_type") or "?"],
            "status": "verified" if exp.get("verified") else "draft" if drafted else "new",
            "drafted_by": exp.get("drafted_by"),
            "note": exp.get("note") or None,
            "reference": {"events": exp.get("events") or []} if drafted else None,
            "input": {k: data.get(k) for k in keys},
        }


SPEC = EventsSpec()
