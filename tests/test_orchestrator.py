from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FIXTURES
from test_filings import FakeClient as FakeExchange
from test_news import CONFIG as NEWS_CONFIG
from test_news import FakeClient as FakeFeeds
from test_prices import FakeNSE

from stock_news_analyzer.agents import digest as dg
from stock_news_analyzer.agents import filings as fl
from stock_news_analyzer.agents import news as nw
from stock_news_analyzer.agents import orchestrator as orch
from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.config import get_settings
from stock_news_analyzer.models import Run
from stock_news_analyzer.sources.announcements import IST
from stock_news_analyzer.sources.securities import parse_bse_scrips, parse_nse_equity_list

REPO = Path(__file__).parent.parent


# --- schedule ----------------------------------------------------------------


def test_repo_schedule_is_valid():
    jobs = orch.load_schedule(REPO / "config" / "schedule.yaml")
    assert {j.name for j in jobs} == set(orch.JOBS)
    upcoming = orch.next_runs(jobs, now=datetime(2026, 10, 21, 18, 5, tzinfo=IST))  # a Wednesday
    assert upcoming["prices"] == datetime(2026, 10, 21, 19, 30, tzinfo=IST)
    assert upcoming["filings"] == datetime(2026, 10, 21, 18, 30, tzinfo=IST)
    assert upcoming["digest"] == datetime(2026, 10, 22, 8, 0, tzinfo=IST)
    assert upcoming["securities"] == datetime(2026, 10, 25, 9, 0, tzinfo=IST)  # Sunday


@pytest.mark.parametrize(
    "expr, after, expected",
    [
        # Friday evening -> next weekday run is Monday, not Saturday.
        ("30 19 * * 1-5", datetime(2026, 10, 23, 20, 0), datetime(2026, 10, 26, 19, 30)),
        ("0 9 * * 0", datetime(2026, 10, 21, 10, 0), datetime(2026, 10, 25, 9, 0)),  # Sunday
        ("0 9 * * 7", datetime(2026, 10, 21, 10, 0), datetime(2026, 10, 25, 9, 0)),  # also Sun
        ("0 9 * * 1,3", datetime(2026, 10, 21, 10, 0), datetime(2026, 10, 26, 9, 0)),
        ("*/30 7-23 * * *", datetime(2026, 10, 21, 23, 45), datetime(2026, 10, 22, 7, 0)),
    ],
)
def test_cron_uses_standard_weekday_numbers(expr, after, expected):
    trigger = orch.cron_trigger(expr)
    assert trigger.get_next_fire_time(None, after.replace(tzinfo=IST)) == expected.replace(
        tzinfo=IST
    )


def test_schedule_rejects_unknown_jobs_and_bad_cron(tmp_path):
    bad = tmp_path / "s.yaml"
    bad.write_text("jobs:\n  tweets:\n    cron: '0 8 * * *'\n")
    with pytest.raises(ValueError, match="unknown job 'tweets'"):
        orch.load_schedule(bad)
    bad.write_text("jobs:\n  news:\n    cron: 'every hour'\n")
    with pytest.raises(ValueError, match="invalid cron"):
        orch.load_schedule(bad)


def test_paused_jobs_are_not_scheduled(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(
        "jobs:\n  news:\n    cron: '15 * * * *'\n  digest:\n    cron: '0 8 * * *'\n"
        "    enabled: false\n"
    )
    jobs = orch.load_schedule(f)
    assert set(orch.next_runs(jobs)) == {"news"}
    scheduler = orch.build_scheduler(jobs)
    assert [j.id for j in scheduler.get_jobs()] == ["news"]


# --- running and recording ---------------------------------------------------


@pytest.mark.db
def test_run_job_records_ok_error_and_crash(session, test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)

    def boom(_session):
        raise RuntimeError("NSE is down")

    def partial(_session):
        raise orch.JobError("3 new filings", ["LT NSE: HTTP 403"])

    jobs = {"good": lambda _s: "10 new articles", "partial": partial, "boom": boom}
    assert orch.run_job("good", jobs).status == "ok"
    p = orch.run_job("partial", jobs)
    assert (p.status, p.summary, p.error) == ("error", "3 new filings", "LT NSE: HTTP 403")
    b = orch.run_job("boom", jobs)  # a crash is recorded, not raised
    assert b.status == "error" and b.error == "RuntimeError: NSE is down"
    runs = session.query(Run).order_by(Run.id).all()
    assert [r.job for r in runs] == ["good", "partial", "boom"]
    assert all(r.finished_at is not None for r in runs)


@pytest.mark.db
def test_cli_run_rejects_unknown_job(test_database_url, monkeypatch):
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    result = CliRunner().invoke(app, ["run", "tweets"])
    assert result.exit_code == 2 and "unknown job 'tweets'" in result.stdout


# --- digest ------------------------------------------------------------------


@pytest.fixture
def loaded(session, tmp_path):
    """Watchlist, three days of real prices, BSE + NSE filings and news for 16-21 Oct 2026."""
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        bse=parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    wl.load_file(session, REPO / "config" / "watchlist.yaml")
    pr.PriceCollector(session, FakeNSE(), tmp_path).collect(date(2026, 10, 16), date(2026, 10, 21))
    pr.compute_moves(session)
    fl.FilingsCollector(session, FakeExchange(), tmp_path, pdf_policy="none").collect(
        fl.watchlist_companies(session), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    nw.NewsCollector(session, FakeFeeds(failing=("broken",)), NEWS_CONFIG).collect(google=False)
    pr.update_labels(session)
    return session


@pytest.mark.db
def test_digest_covers_each_company(loaded):
    since = datetime(2026, 10, 15, tzinfo=IST)
    until = datetime(2026, 10, 22, 8, 0, tzinfo=IST)
    d = dg.build_digest(loaded, since, until)
    md = d.markdown

    assert md.startswith("# Daily digest, 22 Oct 2026 08:00 IST")
    assert "| Nifty 50 | 21 Oct | 22,811.35 | -0.34% |" in md
    assert "| Nifty Bank |" in md and "| Nifty Infrastructure |" in md
    assert "## LT: Larsen & Toubro Limited (owned)" in md
    assert "Last close (21 Oct): -0.71%; vs Nifty 50 -0.37%" in md

    # The same order win was filed on BSE (09:45) and NSE (09:46): listed once, BSE first.
    lt = md.split("## LT:")[1].split("## MSUMI")[0]
    assert lt.count("`order_win`") == 1 and "21 Oct 09:45 BSE `order_win`" in lt
    assert "[L&T bags 'large' orders" in lt  # news headline with its link
    assert "| 21 Oct 09:45 | order_win | -0.37% |" in lt  # what the filing did (1 day)
    assert "## Data collection" in md and "| filings | never |" in md
    assert d.filings == 1 and d.news >= 2  # the 2 and 5 Oct filings are outside the window


@pytest.mark.db
def test_digest_window_follows_the_last_digest(loaded, test_database_url, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()  # the fixture already read settings with the defaults
    assert dg.last_digest_time(loaded) is None
    run = orch.run_job("digest")
    assert run.status == "ok" and run.summary.endswith("unusual days")
    saved = list((tmp_path / "digests").glob("*.md"))
    assert len(saved) == 1 and saved[0].read_text().startswith("# Daily digest")
    assert dg.last_digest_time(loaded) == run.started_at
    later = dg.build_digest(loaded, run.started_at, run.started_at + timedelta(hours=1))
    assert "No new filings." in later.markdown  # nothing new since the previous digest
    assert later.until.tzinfo is UTC or later.until.utcoffset() is not None
