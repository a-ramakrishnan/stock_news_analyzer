"""Analyst Q&A (agent 17): plain-English questions answered from the database, with sources.

The model (Sonnet by default) gets the database's schema and three tools, all read-only:

- run_sql: a SELECT, run in a read-only transaction with a 5-second limit; at most 100 rows
- search_text: full-text search over filings and news, earnings-call points, events and
  promises, with snippets
- read_document: the start of one filing's or article's text

It decides what to look up, step by step (at most MAX_STEPS tool calls), and answers citing
what it used as [doc:ID], [event:ID], [point:ID] or [promise:ID]; the sources are listed with
the answer. Every question is kept; one given a name is a saved report that can be asked again.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_news_analyzer.llm import LLM, month_spend
from stock_news_analyzer.models import (
    Base,
    Company,
    Concall,
    ConcallPoint,
    Document,
    Event,
    Promise,
    Question,
)
from stock_news_analyzer.sources.announcements import IST

log = logging.getLogger(__name__)

MAX_STEPS = 10
MAX_ROWS = 100
CELL_CHARS = 300
STATEMENT_TIMEOUT_MS = 5000
SEARCH_LIMIT = 15
DOC_CHARS = 6000
MAX_TOKENS = 4000
# Must match the index in migration 0023 for searches to use it.
DOCUMENT_TSV = (
    "to_tsvector('english', coalesce(title, '') || ' ' || left(coalesce(text, ''), 20000))"
)
CITATION = re.compile(r"\[(doc|event|point|promise):(\d+)\]")

SYSTEM = """You are an equity analyst answering questions about Indian listed companies from
the user's own database. Today is {today}. Use the tools to look things up; never answer from
memory about these companies, and say so when the data doesn't cover the question.

Working rules:
- Start from the structured tables (run_sql) for numbers, lists and comparisons; use
  search_text for what was said or written, and read_document for detail.
- Amounts are in Rs crore unless a column says otherwise. Times are stored with time zones;
  convert to Asia/Kolkata for dates. Companies are keyed by isin; nse_symbol is the ticker.
- The watchlist (table watchlist) is the user's stocks; most agents only cover those.
- Events: show only qa_status in ('passed', 'flagged') or review = 'accepted'.
- Keep SQL simple and add LIMIT; at most {max_rows} rows come back.

Answer in a few short paragraphs or a small table. Cite every fact you take from a document,
event, call point or promise right after it, as [doc:ID], [event:ID], [point:ID] or
[promise:ID] with the id from the tool results. For figures from tables (results, orders,
prices), name the table and period. No investment advice: describe what the data shows.

Database tables (name: what it holds; columns):
{schema}"""

TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "Run one read-only PostgreSQL SELECT (or WITH ... SELECT) against the database "
            f"and get up to {MAX_ROWS} rows back as tab-separated text. Use LIMIT."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The SQL query."}},
            "required": ["query"],
        },
    },
    {
        "name": "search_text",
        "description": (
            "Full-text search over filings and news articles (doc), earnings-call points "
            "(point), events (event) and management promises (promise). Returns ids, dates, "
            "companies and snippets, best matches first. Words are matched by stem; use a few "
            "key words, OR between alternatives, and a minus sign to exclude."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search words."},
                "symbol": {"type": "string", "description": "Only this NSE symbol."},
                "since": {"type": "string", "description": "Only from this date, YYYY-MM-DD."},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["doc", "point", "event", "promise"]},
                    "description": "Which kinds to search (default: all).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_document",
        "description": f"The title, date, type and first {DOC_CHARS} characters of a document.",
        "input_schema": {
            "type": "object",
            "properties": {"doc_id": {"type": "integer"}},
            "required": ["doc_id"],
        },
    },
]


@dataclass
class Answer:
    question: str
    text: str
    sources: list[str] = field(default_factory=list)
    steps: int = 0
    model: str = ""
    cost_usd: Decimal = Decimal(0)
    question_id: int | None = None
    trace: list[str] = field(default_factory=list)


def schema() -> str:
    """Every table: its first docstring line and its columns, from the models."""
    lines = []
    for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__tablename__):
        cls = mapper.class_
        doc = (cls.__doc__ or "").strip().split("\n\n")[0].replace("\n", " ")
        cols = ", ".join(f"{c.name} {c.type}" for c in cls.__table__.columns)
        lines.append(f"- {cls.__tablename__}: {doc} Columns: {cols}")
    return "\n".join(lines)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (date, Decimal)):
        return str(value)
    return str(value).replace("\t", " ").replace("\n", " ")[:CELL_CHARS]


class SqlRefused(Exception):
    pass


def check_sql(query: str) -> str:
    """The query if it is a single SELECT (or WITH); raises SqlRefused otherwise."""
    q = query.strip().rstrip(";").strip()
    if ";" in q:
        raise SqlRefused("one statement at a time")
    if not re.match(r"(?is)^(select|with)\b", q):
        raise SqlRefused("only SELECT queries are allowed")
    return q


def run_sql(session: Session, query: str) -> str:
    """Run a SELECT in a read-only transaction with a time limit; rows as tab-separated text.
    Any write is refused by PostgreSQL itself, whatever the query says."""
    q = check_sql(query)
    with session.get_bind().connect() as conn:
        tx = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            result = conn.execute(text(q))
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS + 1)
        finally:
            tx.rollback()
    lines = ["\t".join(columns)]
    lines += ["\t".join(_cell(v) for v in row) for row in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines.append(f"(more than {MAX_ROWS} rows; add a LIMIT or narrow the query)")
    if not rows:
        lines.append("(no rows)")
    return "\n".join(lines)


def search_text(
    session: Session,
    query: str,
    symbol: str | None = None,
    since: str | None = None,
    kinds: list[str] | None = None,
) -> str:
    """Full-text search; one line per hit: kind:id, date, symbol, snippet."""
    kinds = kinds or ["doc", "point", "event", "promise"]
    params: dict = {"q": query, "limit": SEARCH_LIMIT}
    isin = None
    if symbol:
        isin = session.scalar(select(Company.isin).where(Company.nse_symbol == symbol.upper()))
        if isin is None:
            return f"unknown symbol {symbol}"
        params["isin"] = isin
    if since:
        params["since"] = datetime.combine(date.fromisoformat(since), datetime.min.time(), IST)
    hits = []
    tsq = "websearch_to_tsquery('english', :q)"
    if "doc" in kinds:
        where = [f"{DOCUMENT_TSV} @@ {tsq}"]
        if isin:
            where.append("d.id IN (SELECT document_id FROM document_companies WHERE isin = :isin)")
        if since:
            where.append("d.published_at >= :since")
        rows = session.execute(
            text(
                f"SELECT d.id, d.published_at, d.doc_type, d.title, "
                f"ts_rank({DOCUMENT_TSV}, {tsq}) AS rank, "
                f"ts_headline('english', left(coalesce(d.text, ''), 20000), {tsq}, "
                f"'MaxWords=35, MinWords=15') AS snippet "
                f"FROM documents d WHERE {' AND '.join(where)} "
                f"ORDER BY rank DESC, d.published_at DESC LIMIT :limit"
            ),
            params,
        ).all()
        for r in rows:
            symbols = ",".join(
                s
                for s in session.scalars(
                    text(
                        "SELECT c.nse_symbol FROM document_companies dc JOIN companies c "
                        "ON c.isin = dc.isin WHERE dc.document_id = :d"
                    ),
                    {"d": r.id},
                )
                if s
            )
            hits.append(
                (
                    r.rank,
                    f"doc:{r.id} {_cell(r.published_at)} {symbols or '-'} {r.doc_type}: "
                    f"{_cell(r.title)} | {_cell(r.snippet)}",
                )
            )
    small = {
        "point": (
            "SELECT p.id, c.published_at AS at, co.nse_symbol, p.category || ': ' || p.text "
            "AS body FROM concall_points p JOIN concalls c ON c.id = p.concall_id "
            "JOIN companies co ON co.isin = c.isin",
            "c.isin",
            "c.published_at",
            "p.text",
        ),
        "event": (
            "SELECT e.id, e.published_at AS at, co.nse_symbol, e.event_type || ': ' || "
            "e.headline AS body FROM events e JOIN companies co ON co.isin = e.isin",
            "e.isin",
            "e.published_at",
            "e.headline || ' ' || coalesce(e.quote, '')",
        ),
        "promise": (
            "SELECT p.id, p.updated_at AS at, co.nse_symbol, p.status || ': ' || p.statement "
            "AS body FROM promises p JOIN companies co ON co.isin = p.isin",
            "p.isin",
            "p.updated_at",
            "p.statement || ' ' || p.metric",
        ),
    }
    for kind, (base, isin_col, at_col, body) in small.items():
        if kind not in kinds:
            continue
        where = [f"to_tsvector('english', {body}) @@ {tsq}"]
        if kind == "event":
            where.append("(e.qa_status IN ('passed', 'flagged') OR e.review = 'accepted')")
        if isin:
            where.append(f"{isin_col} = :isin")
        if since:
            where.append(f"{at_col} >= :since")
        rows = session.execute(
            text(
                f"{base} WHERE {' AND '.join(where)} "
                f"ORDER BY ts_rank(to_tsvector('english', {body}), {tsq}) DESC LIMIT :limit"
            ),
            params,
        ).all()
        for i, r in enumerate(rows):
            hits.append(
                (1.0 / (i + 2), f"{kind}:{r.id} {_cell(r.at)} {r.nse_symbol}: {_cell(r.body)}")
            )
    if not hits:
        return "(no matches)"
    hits.sort(key=lambda h: -h[0])
    return "\n".join(line for _, line in hits[: 2 * SEARCH_LIMIT])


def read_document(session: Session, doc_id: int) -> str:
    doc = session.get(Document, int(doc_id))
    if doc is None:
        return f"no document {doc_id}"
    body = doc.text or ""
    if doc.doc_type == "concall_transcript" and len(body) < 500:
        call = session.scalars(select(Concall).where(Concall.document_id == doc.id)).first()
        body = (call.linked_text if call and call.linked_text else body) or ""
    return (
        f"doc:{doc.id} {doc.doc_type}, {_cell(doc.published_at)}, {doc.source}: {doc.title}\n"
        f"{doc.url or doc.attachment_url or ''}\n\n{body[:DOC_CHARS]}"
    )


def _run_tool(session: Session, name: str, args: dict) -> str:
    try:
        if name == "run_sql":
            return run_sql(session, args["query"])
        if name == "search_text":
            return search_text(
                session, args["query"], args.get("symbol"), args.get("since"), args.get("kinds")
            )
        if name == "read_document":
            return read_document(session, args["doc_id"])
        return f"unknown tool {name}"
    except SqlRefused as exc:
        return f"refused: {exc}"
    except Exception as exc:  # a bad query is the model's to fix on its next step
        session.rollback()
        return f"error: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}"


def _describe(name: str, args: dict) -> str:
    if name == "run_sql":
        return "SQL: " + " ".join(args.get("query", "").split())[:200]
    if name == "search_text":
        extra = " ".join(f"{k}={v}" for k, v in args.items() if k != "query" and v)
        return f"search: {args.get('query')} {extra}".strip()
    return f"read: doc {args.get('doc_id')}"


def sources(session: Session, answer_text: str) -> list[str]:
    """The citations in an answer that point to stored rows, in order of first use."""
    out = []
    models = {"doc": Document, "event": Event, "point": ConcallPoint, "promise": Promise}
    for kind, ident in CITATION.findall(answer_text):
        ref = f"{kind}:{ident}"
        if ref not in out and session.get(models[kind], int(ident)) is not None:
            out.append(ref)
    return out


def describe_source(session: Session, ref: str) -> str:
    """'doc:123' -> '[doc:123] 12 Oct 2026 order_win: L&T wins ... <url>'; call points and
    promises name the company, quarter and call date."""
    kind, ident = ref.split(":")
    if kind == "doc":
        d = session.get(Document, int(ident))
        return (
            f"[{ref}] {d.published_at.astimezone(IST):%d %b %Y} {d.doc_type}: {d.title[:100]} "
            + (d.url or d.attachment_url or "")
        )
    if kind == "event":
        e = session.get(Event, int(ident))
        return (
            f"[{ref}] {e.published_at.astimezone(IST):%d %b %Y} {e.event_type}: {e.headline[:100]}"
        )
    if kind == "point":
        p = session.get(ConcallPoint, int(ident))
        return f"[{ref}] {_call(session, p.concall_id)}, {p.category}: {p.text[:100]}"
    p = session.get(Promise, int(ident))
    return f"[{ref}] {_call(session, p.concall_id)}, promise ({p.status}): {p.statement[:100]}"


def _call(session: Session, concall_id: int) -> str:
    """'KARURVYSYA Q2 FY27 call (15 Oct 2026)'."""
    call = session.get(Concall, concall_id)
    symbol = session.scalar(select(Company.nse_symbol).where(Company.isin == call.isin))
    day = call.call_date or call.published_at.astimezone(IST).date()
    return " ".join(x for x in (symbol, call.quarter, f"call ({day:%d %b %Y})") if x)


def ask(
    session: Session,
    llm: LLM,
    question: str,
    model: str | None = None,
    name: str | None = None,
    progress: Callable[[str], None] | None = None,
    today: date | None = None,
) -> Answer:
    """Answer a question with the tools; store it (as a saved report if `name` is given)."""
    say = progress or (lambda _line: None)
    model = model or llm.settings.llm_model_analysis
    system = SYSTEM.format(
        today=(today or datetime.now(IST).date()).isoformat(), max_rows=MAX_ROWS, schema=schema()
    )
    spend_before = month_spend(session)
    messages: list[dict] = [{"role": "user", "content": question}]
    answer = Answer(question=question, text="", model=model)
    # One tool use a turn at most needs MAX_STEPS turns, then one told to stop, then the answer.
    for _ in range(MAX_STEPS + 2):
        response = llm.message("ask", model, system, messages, TOOLS, max_tokens=MAX_TOKENS)
        # The blocks go back as they came (the SDK accepts its own objects).
        messages.append({"role": "assistant", "content": response.content})
        uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not uses:
            answer.text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            break
        results = []
        for use in uses:
            answer.steps += 1
            line = _describe(use.name, use.input)
            answer.trace.append(line)
            say(line)
            output = (
                _run_tool(session, use.name, use.input)
                if answer.steps <= MAX_STEPS
                else "step limit reached: answer now with what you have"
            )
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": output})
        messages.append({"role": "user", "content": results})
    if not answer.text:
        answer.text = "(no answer: the step limit was reached)"
    answer.sources = sources(session, answer.text)
    answer.cost_usd = month_spend(session) - spend_before
    row = Question(
        name=name,
        question=question,
        answer=answer.text,
        sources=answer.sources,
        steps=answer.steps,
        model=model,
        cost_usd=answer.cost_usd,
    )
    session.add(row)
    session.commit()
    answer.question_id = row.id
    return answer


def saved(session: Session, name: str) -> Question | None:
    """The latest question saved under `name`."""
    return session.scalars(
        select(Question).where(Question.name == name).order_by(Question.asked_at.desc())
    ).first()


def history(session: Session, limit: int = 20) -> list[Question]:
    return list(session.scalars(select(Question).order_by(Question.asked_at.desc()).limit(limit)))


def answer_json(answer: Answer) -> str:
    return json.dumps({"answer": answer.text, "sources": answer.sources}, ensure_ascii=False)
