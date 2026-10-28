"""Saving settings from the dashboard's Settings page (the `settings` table).

A saved value takes the place of the same setting in `.env` (config.get_settings); removing
it goes back to `.env`, or to the default.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_news_analyzer.config import EDITABLE, Settings, clear_cache, env_settings
from stock_news_analyzer.models import SavedSetting


def saved(session: Session) -> dict[str, str]:
    return dict(session.execute(select(SavedSetting.key, SavedSetting.value)).all())


def save(session: Session, key: str, value) -> None:
    if key not in EDITABLE:
        raise KeyError(f"{key} can't be changed from the dashboard")
    text = str(EDITABLE[key](value))
    session.execute(
        insert(SavedSetting)
        .values(key=key, value=text)
        .on_conflict_do_update(index_elements=["key"], set_={"value": text})
    )
    session.commit()
    clear_cache()


def remove(session: Session, key: str) -> None:
    session.query(SavedSetting).filter_by(key=key).delete()
    session.commit()
    clear_cache()


def source(session: Session, key: str) -> str:
    """Where a setting's value comes from: 'Settings page', '.env' or 'default'."""
    if key in saved(session):
        return "Settings page"
    if key in env_settings().model_fields_set:
        return ".env"
    return "default"


def default(key: str):
    return Settings.model_fields[key].default


def paused_jobs(settings: Settings) -> set[str]:
    return {j.strip() for j in settings.paused_jobs.split(",") if j.strip()}


FLAG = "flag:"  # the dashboard's own state (e.g. setup finished), not settings


def get_flag(session: Session, name: str) -> bool:
    return saved(session).get(FLAG + name) == "1"


def set_flag(session: Session, name: str, on: bool) -> None:
    session.execute(
        insert(SavedSetting)
        .values(key=FLAG + name, value="1" if on else "")
        .on_conflict_do_update(index_elements=["key"], set_={"value": "1" if on else ""})
    )
    session.commit()
