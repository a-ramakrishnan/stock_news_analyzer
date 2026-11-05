"""The Results reader's eval (agents/results.py): does it read a quarter's figures from the
results PDF the way the company filed them in XBRL?

Cases are results filings for quarters that also have the exchange's XBRL file, so the answer
comes with the case: the XBRL figures, exact and filed by the company (no drafting, no
checking). The reader gets the PDF's text, as it does when there is no XBRL, and its answer
for that quarter is converted to Rs crore and filtered as the reader stores it (a figure is
kept only if it is in the text). Graded by code:

- `correct` (the headline): the same basis (consolidated or standalone), and revenue and
  profit within 0.1% (or Rs 0.02 crore) of the XBRL figures.
- `basis`, `revenue`, `pat`, `eps`: each right or not.
- `fields`: share of the XBRL figures (revenue, other income, finance costs, depreciation,
  profit before and after tax, EPS) it got right.
- `found`: it found the quarter's column at all.
"""

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_news_analyzer.agents import results as reader
from stock_news_analyzer.agents.concalls import _month_end, quarter_before
from stock_news_analyzer.evals.framework import Answer, NewCase, Spec
from stock_news_analyzer.models import Company, Document, DocumentCompany, EvalCase
from stock_news_analyzer.models import QuarterlyResult as Row
from stock_news_analyzer.sources.announcements import IST

TEXT_CHARS = 250_000  # of a results filing's text frozen in a case
FIELDS = ("revenue", "other_income", "finance_costs", "depreciation", "pbt", "pat", "eps")
LABELS = {
    "revenue": "revenue",
    "pat": "PAT",
    "eps": "EPS",
    "pbt": "PBT",
    "other_income": "other income",
    "finance_costs": "finance costs",
    "depreciation": "depreciation",
}
REL, ABS = Decimal("0.001"), Decimal("0.02")
PER_COMPANY = 2
FILED_WITHIN = 75  # days after a quarter's end that its results filing is looked for


def _close(expected, found) -> bool:
    if expected is None:
        return True
    if found is None:
        return False
    e, f = Decimal(str(expected)), Decimal(str(found))
    return abs(e - f) <= max(REL * abs(e), ABS)


def _filing(data: dict) -> tuple[Document, Company]:
    doc = Document(
        id=int(data["document_id"]),
        title=data["title"],
        subject=data.get("subject"),
        text=data.get("text"),
        text_status=data.get("text_status") or "ok",
        published_at=datetime.fromisoformat(str(data["published_at"])),
        doc_type="results",
    )
    company = Company(isin=data["isin"], name=data["company"], nse_symbol=data.get("symbol"))
    return doc, company


def _f(v) -> float | None:
    return None if v is None else float(v)


class ResultsSpec(Spec):
    name = "results"
    agent = "results"
    title = "Results reader"
    system = reader.SYSTEM
    prompt_version = None
    metrics = [
        {"id": "correct", "label": "Correct", "kind": "binary"},
        {"id": "basis", "label": "Basis", "kind": "binary"},
        {"id": "revenue", "label": "Revenue", "kind": "binary"},
        {"id": "pat", "label": "Profit", "kind": "binary"},
        {"id": "eps", "label": "EPS", "kind": "binary"},
        {"id": "fields", "label": "All figures", "kind": "continuous"},
        {"id": "found", "label": "Quarter found", "kind": "binary"},
    ]
    needs_checking = False  # the answers are the company's own XBRL figures
    default_n = 30

    def default_model(self) -> str:
        from stock_news_analyzer.config import get_settings

        return get_settings().llm_model_triage

    def sample(self, session: Session, n: int, seed: int, taken: set[str]) -> list[NewCase]:
        """Quarters with XBRL figures and a results PDF with text, at most two a company,
        spread over companies."""
        rng = random.Random(seed)
        rows = session.execute(
            select(Row, Company)
            .join(Company, Company.isin == Row.isin)
            .where(Row.model == reader.XBRL, Row.months == 3, Row.primary.is_(True))
        ).all()
        rng.shuffle(rows)
        per_company: dict[str, int] = {}
        out: list[NewCase] = []
        for row, company in rows:
            if len(out) >= n or per_company.get(company.isin, 0) >= PER_COMPANY:
                continue
            doc = self._pdf(session, company.isin, row.period_end)
            if doc is None:
                continue
            key = f"{company.nse_symbol or company.isin}-{row.period_end:%Y%m}"
            if key in taken:
                continue
            per_company[company.isin] = per_company.get(company.isin, 0) + 1
            out.append(
                NewCase(
                    key=key,
                    title=f"{company.nse_symbol or company.isin}: {row.period} ({row.basis})",
                    input={
                        "document_id": doc.id,
                        "company": company.name,
                        "symbol": company.nse_symbol,
                        "isin": company.isin,
                        "published_at": doc.published_at.isoformat(),
                        "title": doc.title,
                        "subject": doc.subject,
                        "text_status": doc.text_status,
                        "text": (doc.text or "")[:TEXT_CHARS],
                    },
                    tags=[row.basis, row.period],
                    reference={
                        "period_end": row.period_end.isoformat(),
                        "months": 3,
                        "basis": row.basis,
                        **{f: _f(getattr(row, f"{f}_cr" if f != "eps" else "eps")) for f in FIELDS},
                    },
                    drafted_by="xbrl",
                )
            )
        return out

    def _pdf(self, session: Session, isin: str, end: date) -> Document | None:
        """The best results filing with text for the quarter ending `end`."""
        start = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=IST)
        docs = session.scalars(
            select(Document)
            .join(DocumentCompany, DocumentCompany.document_id == Document.id)
            .where(
                DocumentCompany.isin == isin,
                Document.doc_type == "results",
                Document.text_status.in_(("ok", "partial")),
                Document.published_at >= start,
                Document.published_at < start + timedelta(days=FILED_WITHIN),
            )
        ).all()
        docs = [d for d in docs if len(reader.statement_text(d)) >= reader.MIN_CHARS]
        return sorted(docs, key=reader._rank)[0] if docs else None

    def call(self, llm, case: EvalCase, model: str, system: str | None = None) -> Answer:
        doc, company = _filing(case.input)
        text = reader.statement_text(doc)
        quarter = quarter_before(doc.published_at.astimezone(IST).date())
        prompt = reader._prompt(company, quarter, doc, text)
        if system is None:  # the agent's own entry point
            answer, _ = reader._ask(llm, (model,), prompt)
        else:  # the same call with other instructions (an experiment)
            answer = llm.structured(
                "results",
                model,
                system,
                prompt,
                reader.ResultsAnswer,
                max_tokens=reader.MAX_TOKENS,
            )
        c = llm.last_call
        return Answer(
            output=self._quarter(answer, case.reference or {}, text),
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

    def _quarter(self, answer, reference: dict, text: str) -> dict:
        """The answer's column for the case's quarter, in Rs crore, each figure kept only if
        it is written in the text (as the reader stores it)."""
        out = {"is_results": answer.is_results, "basis": answer.basis, "unit": answer.unit}
        target = date.fromisoformat(reference["period_end"]) if reference else None
        in_text = reader.numbers_in(text)
        factor = reader.UNITS[answer.unit]
        for c in answer.columns if answer.is_results else []:
            try:
                end = date.fromisoformat(c.period_end)
            except ValueError:
                continue
            if _month_end(end.year, end.month) != target or c.months != 3:
                continue
            out["period_end"] = target.isoformat()
            for f in FIELDS:
                v = reader.number(getattr(c, f))
                if v is None or abs(v) not in in_text:
                    out[f] = None
                else:
                    out[f] = float(round(v if f == "eps" else v * factor, 2 if f == "eps" else 4))
            break
        return out

    def grade(self, case: EvalCase, output: dict) -> dict[str, float]:
        ref = case.reference or {}
        found = float("period_end" in output)
        basis = float(output.get("basis") == ref.get("basis"))
        each = {f: _close(ref.get(f), output.get(f)) for f in FIELDS if ref.get(f) is not None}
        fields = sum(each.values()) / len(each) if each else 1.0
        revenue, pat = each.get("revenue", True), each.get("pat", True)
        return {
            "correct": float(bool(found and basis and revenue and pat)),
            "basis": basis,
            "revenue": float(bool(found and revenue)),
            "pat": float(bool(found and pat)),
            "eps": float(bool(found and each.get("eps", True))),
            "fields": round(fields if found else 0.0, 4),
            "found": found,
        }

    def describe(self, answer: dict | None) -> list[str]:
        if not answer:
            return []
        if "period_end" not in answer:
            return ["quarter not found" if answer.get("is_results") else "no results read"]
        figures = ", ".join(
            f"{LABELS[f]} {answer[f]:,.2f}"
            for f in ("revenue", "pat", "eps")
            if answer.get(f) is not None
        )
        return [f"{answer.get('basis')} {answer['period_end']}: {figures}"]

    editable = False  # the company's XBRL figures are the answer

    def show(self, case: EvalCase) -> dict:
        d = case.input
        doc, _ = _filing(d)
        return {
            "heading": d.get("title") or case.key,
            "facts": [
                f"{d.get('company')} ({d.get('symbol') or d.get('isin')})",
                f"filed {str(d.get('published_at'))[:10]}",
                f"document {d.get('document_id')}",
            ],
            "text": reader.excerpt(reader.statement_text(doc)),
        }

    def oracle(self, case: EvalCase) -> dict:
        return dict(case.reference or {})

    def null(self, case: EvalCase) -> dict:
        return {"is_results": False}


SPEC = ResultsSpec()
