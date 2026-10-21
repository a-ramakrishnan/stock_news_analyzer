"""Database connection and health checks."""

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text

from stock_news_analyzer.config import get_settings


def get_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)


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
