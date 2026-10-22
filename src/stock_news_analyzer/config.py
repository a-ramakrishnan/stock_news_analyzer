"""Settings, read from environment variables and an optional `.env` file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Phase 2 (LLM agents). The key comes from console.anthropic.com; keep it in .env only.
    anthropic_api_key: str | None = None
    # High-volume work (news triage) and judgement work (explanations, extraction, calls).
    llm_model_triage: str = "claude-haiku-5-5"
    llm_model_analysis: str = "claude-sonnet-5-5"
    # LLM calls stop for the rest of the month (India time) once this much has been spent.
    llm_monthly_budget_usd: float = 20.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
