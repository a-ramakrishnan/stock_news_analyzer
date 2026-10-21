"""Orchestrator (agent 0).

Runs the collectors and the digest on a schedule (config/schedule.yaml, in India time), one job
at a time, and records every run in the `runs` table. No LLM: the order of work is fixed.
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
    "prices": job_prices,
    "securities": job_securities,
    "digest": job_digest,
}
# `sna run all`: collect, then measure, then report.
RUN_ALL = ("filings", "news", "prices", "digest")


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
            scheduler.add_job(run_job, job.trigger, args=[job.name], id=job.name, name=job.name)
    return scheduler
