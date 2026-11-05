"""Traces: what each AI call was sent and what it answered (llm_traces), for looking into what
an agent did, and for turning real calls into eval cases.

The LLM wrapper (llm.py) records a trace after every call, failed calls included. The
instructions (system prompt), the same on every call of a task, are stored once
(llm_prompts) by their digest. Traces older than `llm_trace_days` are pruned each morning
with the digest; 0 days turns them off.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from stock_news_analyzer.models import LlmCall, LlmPrompt, LlmTrace

FILING = re.compile(r'<filing id="(\d+)"')
PROMPT_CHARS = 200_000  # of a prompt kept: the agents' longest (a call transcript) fit


def jsonable(value):
    """An answer (a pydantic model, SDK content blocks, plain data) as JSON-safe data."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return jsonable(dump(mode="json"))
        except Exception:  # noqa: BLE001  (fall back to the object's fields)
            pass
    if hasattr(value, "__dict__"):
        return {k: jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)


def subjects(prompt: str) -> list[str]:
    """What a call was about, where its prompt says so: the filings it read."""
    return [f"document:{i}" for i in dict.fromkeys(FILING.findall(prompt))]


def record(
    session: Session,
    call: LlmCall,
    system,
    prompt,
    answer,
    stop_reason: str | None,
    served: str | None,
    latency_ms: int,
) -> LlmTrace:
    """Store one call's trace (its instructions once per distinct text)."""
    system_text = system if isinstance(system, str) else json.dumps(jsonable(system))
    sha = hashlib.sha256(system_text.encode()).hexdigest() if system_text else None
    if sha and session.get(LlmPrompt, sha) is None:
        session.add(LlmPrompt(sha=sha, text=system_text))
        session.flush()
    text = prompt if isinstance(prompt, str) else json.dumps(jsonable(prompt), indent=1)
    trace = LlmTrace(
        call_id=call.id,
        system_sha=sha,
        prompt=text[:PROMPT_CHARS],
        response=jsonable(answer),
        stop_reason=stop_reason,
        served_model=served,
        latency_ms=latency_ms,
        subjects=subjects(text),
    )
    session.add(trace)
    session.commit()
    return trace


def prune(session: Session, days: int, now: datetime | None = None) -> int:
    """Delete traces of calls older than `days` (all when 0), and instructions no trace uses.
    Returns the traces deleted."""
    now = now or datetime.now(UTC)
    old = select(LlmCall.id).where(LlmCall.at < now - timedelta(days=days))
    gone = session.execute(delete(LlmTrace).where(LlmTrace.call_id.in_(old))).rowcount or 0
    used = select(LlmTrace.system_sha).where(LlmTrace.system_sha.isnot(None))
    session.execute(delete(LlmPrompt).where(LlmPrompt.sha.not_in(used)))
    session.commit()
    return gone


def listing(
    session: Session,
    tasks: list[str] | None = None,
    days: int = 7,
    failed_only: bool = False,
    text: str | None = None,
    limit: int = 300,
    now: datetime | None = None,
) -> list[dict]:
    """Traced calls, newest first, with their cost and outcome."""
    now = now or datetime.now(UTC)
    query = (
        select(LlmCall, LlmTrace)
        .join(LlmTrace, LlmTrace.call_id == LlmCall.id)
        .where(LlmCall.at >= now - timedelta(days=days))
        .order_by(LlmCall.at.desc(), LlmCall.id.desc())
        .limit(limit)
    )
    if tasks:
        query = query.where(LlmCall.task.in_(tasks))
    if failed_only:
        query = query.where(LlmCall.ok.is_(False))
    if text:
        query = query.where(LlmTrace.prompt.ilike(f"%{text}%"))
    return [
        {
            "call_id": call.id,
            "at": call.at,
            "task": call.task,
            "model": trace.served_model or call.model,
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "cost_usd": float(call.cost_usd or 0),
            "latency_s": (trace.latency_ms or 0) / 1000,
            "ok": call.ok,
            "error": call.error,
            "stop_reason": trace.stop_reason,
            "subjects": trace.subjects or [],
        }
        for call, trace in session.execute(query).all()
    ]


def tasks(session: Session) -> list[str]:
    """The tasks that have traces, most traced first."""
    rows = session.execute(
        select(LlmCall.task, func.count())
        .join(LlmTrace, LlmTrace.call_id == LlmCall.id)
        .group_by(LlmCall.task)
        .order_by(func.count().desc())
    ).all()
    return [t for t, _ in rows]


def detail(session: Session, call_id: int) -> dict | None:
    """One traced call in full: instructions, prompt, answer."""
    row = session.execute(
        select(LlmCall, LlmTrace)
        .join(LlmTrace, LlmTrace.call_id == LlmCall.id)
        .where(LlmCall.id == call_id)
    ).first()
    if row is None:
        return None
    call, trace = row
    system = session.get(LlmPrompt, trace.system_sha) if trace.system_sha else None
    return {
        "call_id": call.id,
        "at": call.at,
        "task": call.task,
        "model": call.model,
        "served_model": trace.served_model,
        "ok": call.ok,
        "error": call.error,
        "stop_reason": trace.stop_reason,
        "latency_s": (trace.latency_ms or 0) / 1000,
        "tokens": (
            call.input_tokens,
            call.output_tokens,
            call.cache_read_tokens,
            call.cache_write_tokens,
        ),
        "cost_usd": float(call.cost_usd or 0),
        "system": system.text if system else "",
        "prompt": trace.prompt,
        "response": trace.response,
        "subjects": trace.subjects or [],
    }


def documents(subject_list: list[str]) -> list[int]:
    return [int(s.split(":")[1]) for s in subject_list if s.startswith("document:")]
