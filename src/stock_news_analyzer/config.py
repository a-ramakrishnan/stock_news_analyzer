"""Settings, read from environment variables and an optional `.env` file, with the values
saved on the dashboard's Settings page (the `settings` table) on top."""

import logging
import time
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres connection. The default matches docker-compose.yml when run from the laptop.
    database_url: str = "postgresql+psycopg://sna:sna@localhost:5433/sna"

    # Where raw files (filing PDFs, transcripts, audio) and generated reports are stored.
    data_dir: Path = Path("data")

    # All timestamps are stored and shown in Indian Standard Time.
    timezone: str = "Asia/Kolkata"

    log_level: str = "INFO"

    # A day is "unusual" when a stock's return minus the Nifty 50's exceeds this many standard
    # deviations of the previous 60 trading days. 2.0 flags about 5% of days.
    unusual_threshold: float = 2.0

    # Phase 2 (LLM agents). The key comes from console.anthropic.com.
    anthropic_api_key: str | None = None
    # High-volume work (news triage) and judgement work (explanations, extraction, calls).
    llm_model_triage: str = "claude-haiku-5-5"
    llm_model_analysis: str = "claude-sonnet-5-5"
    # LLM calls stop for the rest of the month (India time) once this much has been spent.
    llm_monthly_budget_usd: float = 20.0

    # Scheduled jobs turned off on the Settings page, comma-separated.
    paused_jobs: str = ""


# The settings the Settings page can change, and the type each is stored as (text).
EDITABLE = {
    "anthropic_api_key": str,
    "llm_model_triage": str,
    "llm_model_analysis": str,
    "llm_monthly_budget_usd": float,
    "unusual_threshold": float,
    "paused_jobs": str,
}
SAVED_TTL = 30.0  # seconds: how long saved values are kept before reading them again

_saved: dict = {"at": float("-inf"), "values": {}}


@lru_cache
def env_settings() -> Settings:
    """The settings from the environment and `.env` alone."""
    return Settings()


@lru_cache
def _engine(url: str):
    from sqlalchemy import create_engine

    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def saved_values(base: Settings) -> dict:
    """The values saved on the Settings page, read at most every SAVED_TTL seconds. Empty
    when the database or the table isn't there yet."""
    now = time.monotonic()
    if now - _saved["at"] < SAVED_TTL:
        return _saved["values"]
    from sqlalchemy import text

    values = {}
    try:
        with _engine(base.database_url).connect() as conn:
            for key, value in conn.execute(text("SELECT key, value FROM settings")):
                if key in EDITABLE and value is not None:
                    values[key] = EDITABLE[key](value)
    except Exception as exc:  # no database yet, or migrations not run: .env alone
        log.debug("saved settings not read: %s", exc)
    _saved.update(at=now, values=values)
    return values


def get_settings() -> Settings:
    """The settings in use: `.env` and the environment, with values saved on the Settings
    page taking their place."""
    base = env_settings()
    values = saved_values(base)
    return base.model_copy(update=values) if values else base


def clear_cache() -> None:
    """Read `.env` and the saved values again on the next call."""
    env_settings.cache_clear()
    _saved.update(at=float("-inf"), values={})


get_settings.cache_clear = clear_cache  # the name callers (and tests) already use
