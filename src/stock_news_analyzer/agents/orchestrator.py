"""Orchestrator (agent 0).

Runs the collectors, the LLM agents and the digest on a schedule (config/schedule.yaml, in India
time), one job at a time, and records every run in the `runs` table. The order of work is fixed
code, not an LLM decision.
"""

import logging
import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from stock_news_analyzer.config import get_settings
from stock_news_analyzer.db import get_session
from stock_news_analyzer.models import Run
from stock_news_analyzer.sources.announcements import IST

log = logging.getLogger(__name__)

SCHEDULE_FILE = Path("config/schedule.yaml")
FEEDS_FILE = Path("config/news_feeds.yaml")
# A run missed while the laptop slept still happens on wake if it is this late or less.
MISFIRE_GRACE = timedelta(hours=3)


class JobError(Exception):
    """A job finished but reported errors; `summary` still describes what it did."""

    def __init__(self, summary: str, errors: list[str]):
        self.summary = summary
        self.errors = errors
        super().__init__("; ".join(errors))


# --- jobs --------------------------------------------------------------------


NO_KEY = "skipped: no Anthropic API key (add one on the Settings page)"


def job_filings(session: Session) -> str:
    from stock_news_analyzer.agents.filings import FilingsCollector, watchlist_companies
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    collector = FilingsCollector(session, ExchangeClient(), get_settings().data_dir)
    result = collector.collect(watchlist_companies(session))
    summary = f"{result.new} new filings, {result.attachments} PDFs"
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_news(session: Session) -> str:
    from stock_news_analyzer.agents.news import NewsCollector
    from stock_news_analyzer.sources.news import NewsClient, load_feed_config

    result = NewsCollector(session, NewsClient(), load_feed_config(FEEDS_FILE)).collect()
    summary = f"{result.new} new articles ({result.matched} matched of {result.seen} read)"
    if result.errors:
        raise JobError(summary, [f"{r.key}: {r.error}" for r in result.errors])
    return summary


# The scheduled run triages at most this many articles; `sna triage run` has no limit.
TRIAGE_LIMIT = 500


def job_triage(session: Session) -> str:
    from stock_news_analyzer.agents.triage import triage_news
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    result = triage_news(session, LLM(session), limit=TRIAGE_LIMIT)
    summary = (
        f"{result.triaged} articles triaged ({result.same_story} same event as an earlier "
        f"report), {result.duplicates} near-identical headlines, "
        f"{result.calls} LLM calls, ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


# The scheduled run explains unusual days of the last two weeks, at most this many.
EXPLAIN_LIMIT = 30
EXPLAIN_DAYS = 14


def job_explain(session: Session) -> str:
    from stock_news_analyzer.agents.explain import explain_moves
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    today = datetime.now(IST).date()
    # Up to yesterday: the morning's news often says why a stock moved the day before.
    result = explain_moves(
        session,
        LLM(session),
        since=today - timedelta(days=EXPLAIN_DAYS),
        until=today - timedelta(days=1),
        limit=EXPLAIN_LIMIT,
    )
    summary = f"{result.explained} unusual days explained, ${result.cost_usd:.4f}"
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


# The scheduled runs read transcripts and results filed in the last few months; `sna concalls
# run` and `sna results run` go further back.
CONCALL_DAYS = 120


def job_concalls(session: Session) -> str:
    from stock_news_analyzer.agents.concalls import analyse_calls
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    since = datetime.now(IST).date() - timedelta(days=CONCALL_DAYS)
    result = analyse_calls(session, LLM(session), since=since)
    summary = (
        f"{result.analysed} earnings calls analysed, {result.no_text} without text, "
        f"{result.duplicates} copies, ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_promises(session: Session) -> str:
    from stock_news_analyzer.agents.promises import check_promises
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    result = check_promises(session, LLM(session))
    summary = (
        f"{result.checked} promises checked for {result.companies} companies, "
        f"{result.settled} settled, ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_orders(session: Session) -> str:
    from stock_news_analyzer.agents import orders
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    result = orders.run(session, LLM(session))
    summary = (
        f"{result.orders} orders from {result.filings} filings ({result.duplicates} copies), "
        f"{result.snapshots} order books, ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_xbrl(session: Session) -> str:
    from stock_news_analyzer.agents import xbrl_results
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    result = xbrl_results.import_results(session, ExchangeClient())
    summary = (
        f"{result.periods} result periods from XBRL ({result.corrected} corrected a PDF "
        f"reading), {result.skipped} already from XBRL"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_holdings(session: Session) -> str:
    from stock_news_analyzer.agents import holdings
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    result = holdings.import_holdings(session, ExchangeClient())
    summary = f"{result.filings} shareholding patterns, {result.skipped} already stored"
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_results(session: Session) -> str:
    from stock_news_analyzer.agents import results
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    since = datetime.now(IST).date() - timedelta(days=CONCALL_DAYS)
    result = results.run(session, LLM(session), since=since)
    summary = (
        f"{result.periods} result periods from {result.filings} filings "
        f"({result.duplicates} copies), ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_events(session: Session) -> str:
    from stock_news_analyzer.agents import events
    from stock_news_analyzer.agents.filings import FilingsCollector
    from stock_news_analyzer.llm import LLM
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    if not get_settings().anthropic_api_key:
        return NO_KEY
    collector = FilingsCollector(session, ExchangeClient(), get_settings().data_dir)
    result = events.run(session, LLM(session), fetch=collector.fetch_attachment)
    summary = (
        f"{result.events} events from {result.filings} filings; QA {result.passed} passed, "
        f"{result.flagged} flagged, {result.rejected} failed; ${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_flags(session: Session) -> str:
    from stock_news_analyzer.agents import redflags

    result = redflags.scan(session)
    counts = ", ".join(f"{n} {s}" for s, n in sorted(result.by_severity.items())) or "none"
    return f"{result.raised} red flags raised ({counts})"


def job_bullion(session: Session) -> str:
    from stock_news_analyzer.agents import bullion
    from stock_news_analyzer.llm import LLM
    from stock_news_analyzer.sources.news import NewsClient

    if not bullion.watched_metals(session):
        return "skipped: no bullion on the watchlist"
    llm = LLM(session) if get_settings().anthropic_api_key else None
    result = bullion.run(session, llm, NewsClient().fetch)
    summary = (
        f"{result.days} days split, {result.unusual} unusual; {result.notes} notes, "
        f"${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_themes(session: Session) -> str:
    from stock_news_analyzer.agents import themes
    from stock_news_analyzer.llm import LLM

    if not get_settings().anthropic_api_key:
        return NO_KEY
    result = themes.run(session, LLM(session))
    summary = (
        f"{result.items} items tagged ({result.tags} tags), {result.signals} read-across; "
        f"${result.cost_usd:.4f}"
    )
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_prices(session: Session) -> str:
    from stock_news_analyzer.agents.prices import (
        PriceCollector,
        compute_moves,
        refresh_corporate_actions,
        update_labels,
    )
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    client = ExchangeClient()
    collector = PriceCollector(session, client, get_settings().data_dir)
    result = collector.collect(collector.resume_date())
    today = datetime.now(IST).date()
    errors = result.errors + refresh_corporate_actions(
        session, client, today - timedelta(days=365), today
    )
    errors += compute_moves(session)
    written, complete = update_labels(session)
    summary = f"{result.days} trading days loaded; {written} labels updated ({complete} complete)"
    if errors:
        raise JobError(summary, errors)
    return summary


def job_deals(session: Session) -> str:
    from stock_news_analyzer.agents import deals as dl
    from stock_news_analyzer.sources.exchange_http import ExchangeClient

    result = dl.collect(session, ExchangeClient(), dl.resume_date(session))
    summary = f"{result.new} new bulk/block deals ({result.seen} read)"
    if result.errors:
        raise JobError(summary, result.errors)
    return summary


def job_securities(session: Session) -> str:
    from stock_news_analyzer.agents.watchlist import refresh_master

    result, warnings = refresh_master(session, get_settings().data_dir)
    summary = f"{result.total} companies ({result.nse} NSE, {result.bse} BSE)"
    if warnings:
        raise JobError(summary, warnings)
    return summary


def job_digest(session: Session) -> str:
    from stock_news_analyzer.agents.digest import build_digest, last_digest_time, save_digest

    until = datetime.now(UTC)
    since = last_digest_time(session) or until - timedelta(days=1)
    digest = build_digest(session, since, until)
    path = save_digest(digest, get_settings().data_dir)
    return (
        f"{path}: {digest.filings} filings, {digest.news} articles, {digest.unusual} unusual days"
    )


JOBS: dict[str, Callable[[Session], str]] = {
    "filings": job_filings,
    "news": job_news,
    "triage": job_triage,
    "deals": job_deals,
    "prices": job_prices,
    "xbrl": job_xbrl,
    "holdings": job_holdings,
    "results": job_results,
    "events": job_events,
    "flags": job_flags,
    "bullion": job_bullion,
    "themes": job_themes,
    "explain": job_explain,
    "concalls": job_concalls,
    "promises": job_promises,
    "orders": job_orders,
    "securities": job_securities,
    "digest": job_digest,
}
# `sna run all`: collect, then judge, then measure, then report.
RUN_ALL = (
    "filings",
    "news",
    "triage",
    "deals",
    "prices",
    "xbrl",
    "holdings",
    "results",
    "events",
    "explain",
    "concalls",
    "promises",
    "orders",
    "themes",
    "flags",
    "bullion",
    "digest",
)


# --- running and recording ---------------------------------------------------


def run_job(name: str, jobs: dict[str, Callable[[Session], str]] | None = None) -> Run:
    """Run one job in its own session and record it in `runs`. Never raises."""
    jobs = jobs or JOBS
    with get_session() as session:
        run = Run(job=name, started_at=datetime.now(UTC), status="running")
        session.add(run)
        session.commit()
        log.info("%s: started", name)
        try:
            run.summary = jobs[name](session)
            run.status = "ok"
        except JobError as exc:
            session.rollback()
            run.summary, run.error, run.status = exc.summary, "; ".join(exc.errors), "error"
        except Exception as exc:  # a crash in one job must not stop the scheduler
            session.rollback()
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"
            log.error("%s crashed:\n%s", name, traceback.format_exc())
        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()
        session.refresh(run)
        log.info("%s: %s %s", name, run.status, run.error or run.summary or "")
        session.expunge(run)
        return run


def running(session: Session, name: str, within: timedelta = timedelta(hours=3)) -> Run | None:
    """A run of this job started in the last few hours and not finished: started by the
    scheduler or by hand elsewhere. Older ones were cut off (a restart) and don't count."""
    from sqlalchemy import select

    return session.scalars(
        select(Run)
        .where(
            Run.job == name,
            Run.status == "running",
            Run.started_at >= datetime.now(UTC) - within,
        )
        .order_by(Run.started_at.desc())
    ).first()


def scheduled_run(name: str) -> Run | None:
    """A run started by the schedule: skipped while the job is paused on the Settings page
    (a run by hand, `sna run <job>`, always runs)."""
    from stock_news_analyzer.settings_store import paused_jobs

    if name in paused_jobs(get_settings()):
        log.info("%s: paused on the Settings page, not run", name)
        return None
    return run_job(name)


# --- schedule ----------------------------------------------------------------


@dataclass
class ScheduledJob:
    name: str
    cron: str
    enabled: bool
    trigger: CronTrigger


WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")


def cron_trigger(expr: str) -> CronTrigger:
    """A standard 5-field cron expression in India time.

    APScheduler counts weekdays from 0 = Monday, standard cron from 0 = Sunday, so weekday
    numbers are turned into names first ("1-5" -> "mon-fri"; without this it means Tue-Sat).
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 fields (minute hour day month weekday), got {len(fields)}")
    minute, hour, day, month, weekday = fields
    weekday = re.sub(r"(?<![/\d])([0-7])(?!\d)", lambda m: WEEKDAYS[int(m.group(1))], weekday)
    return CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=weekday, timezone=IST
    )


def load_schedule(path: Path = SCHEDULE_FILE) -> list[ScheduledJob]:
    data = yaml.safe_load(path.read_text()) or {}
    out = []
    for name, spec in (data.get("jobs") or {}).items():
        if name not in JOBS:
            raise ValueError(f"{path}: unknown job '{name}' (known: {', '.join(JOBS)})")
        spec = spec or {}
        cron = str(spec.get("cron", "")).strip()
        try:
            trigger = cron_trigger(cron)
        except ValueError as exc:
            raise ValueError(f"{path}: job '{name}' has an invalid cron '{cron}': {exc}") from exc
        out.append(ScheduledJob(name, cron, bool(spec.get("enabled", True)), trigger))
    return out


def job_notes(path: Path = SCHEDULE_FILE) -> dict[str, str]:
    """{job: its comment in the schedule file}, e.g. 'filings': 'new BSE + NSE announcements'."""
    notes = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        found = re.match(r"^\s{2}(\w+):\s*#\s*(.+)$", line)
        if found:
            notes[found.group(1)] = found.group(2).strip()
    return notes


def next_runs(schedule: list[ScheduledJob], now: datetime | None = None) -> dict[str, datetime]:
    now = now or datetime.now(IST)
    return {j.name: j.trigger.get_next_fire_time(None, now) for j in schedule if j.enabled}


def build_scheduler(schedule: list[ScheduledJob]) -> BlockingScheduler:
    """One job at a time (a single worker), missed runs coalesced into one."""
    scheduler = BlockingScheduler(
        timezone=IST,
        executors={"default": ThreadPoolExecutor(max_workers=1)},
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": int(MISFIRE_GRACE.total_seconds()),
        },
    )
    for job in schedule:
        if job.enabled:
            scheduler.add_job(
                scheduled_run, job.trigger, args=[job.name], id=job.name, name=job.name
            )
    return scheduler
