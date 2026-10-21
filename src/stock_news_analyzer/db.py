"""Database connection and health checks."""

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from stock_news_analyzer.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)


def get_session(engine: Engine | None = None) -> Session:
    return Session(engine or get_engine())


def upgrade_database(database_url: str | None = None) -> None:
    """Apply all migrations up to the latest version."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    url = database_url or get_settings().database_url
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@dataclass
class DatabaseHealth:
    server_version: str
    pgvector_version: str | None


def check_database(engine: Engine) -> DatabaseHealth:
    """Connect, report the Postgres version and whether the pgvector extension is enabled."""
    with engine.connect() as conn:
        server_version = conn.execute(text("SHOW server_version")).scalar_one()
        pgvector_version = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
    return DatabaseHealth(server_version=server_version, pgvector_version=pgvector_version)
