from datetime import datetime, timedelta

import pytest
from test_prices import _load_series, _trading_days, watchlist  # noqa: F401  (fixture)

from stock_news_analyzer.agents import prices as pr
from stock_news_analyzer.agents import weekly
from stock_news_analyzer.models import Document, DocumentCompany, Event, NewsTriage
from stock_news_analyzer.sources.announcements import IST

KVB = "INE036D01028"


def _at(day, hour):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour, tzinfo=IST)


def _news(s, key, when, sentiment="positive", importance=4, relevant=True):
    doc = Document(
        source="news:google",
        source_id=key,
        doc_type="news",
        title=key,
        published_at=when,
        url=f"https://example.com/{key}",
        raw={},
    )
    s.add(doc)
    s.flush()
    s.add(DocumentCompany(document_id=doc.id, isin=KVB))
    s.add(
        NewsTriage(
            document_id=doc.id,
            isin=KVB,
            relevant=relevant,
            topic="market",
            sentiment=sentiment,
            importance=importance,
            summary=key,
            model="test",
        )
    )
    return doc


@pytest.mark.db
def test_weeks_line_up_moves_with_the_news(watchlist):  # noqa: F811
    days = _trading_days(40)  # from Mon 1 Jun 2026; KVB beats the Nifty by 5% on day 30
    _load_series(watchlist, days, big_day=30)
    pr.compute_moves(watchlist)
    s = watchlist
    big = days[30]
    assert big.weekday() == 0  # a Monday: the 5% is the week's main move
    _news(s, "upgrade", _at(big, 10))  # positive, that morning
    _news(s, "off-topic", _at(big, 11), sentiment="negative", relevant=False)
    friday = days[29]
    _news(s, "late-friday", _at(friday, 18), sentiment="positive", importance=3)
    _news(s, "minor", _at(days[10], 10), sentiment="negative", importance=2)
    filing = Document(
        source="bse",
        source_id="f1",
        doc_type="results",
        title="Results",
        published_at=_at(big, 9),
        raw={},
    )
    s.add(filing)
    s.flush()
    s.add(DocumentCompany(document_id=filing.id, isin=KVB))
    s.add(
        Event(
            isin=KVB,
            document_id=filing.id,
            published_at=filing.published_at,
            event_type="guidance",
            headline="Guidance raised",
            sentiment="positive",
            importance=4,
            qa_status="passed",
            model="test",
            prompt_version="1",
        )
    )
    s.commit()

    ws = weekly.weeks(s, KVB, 8, today=days[-1])
    assert len(ws) == 8 and ws[0].start == days[-1] - timedelta(days=days[-1].weekday())
    week = next(w for w in ws if w.start == big)
    assert week.excess == pytest.approx(0.05, abs=0.02)  # the jump dominates
    titles = [i.title for i in week.items]
    # Friday's after-close news counts in Monday's week; off-topic news doesn't count at all.
    assert "upgrade" in titles and "late-friday" in titles and "off-topic" not in titles
    assert "Results" in titles and "Guidance raised" in titles
    assert week.tone == 4 + 3 + 4 and week.verdict == "In line with the news"
    assert week.of("news")[0].url == "https://example.com/upgrade"
    previous = next(w for w in ws if w.start == big - timedelta(days=7))
    assert "late-friday" not in [i.title for i in previous.items]

    # Weeks whose moves stay under the usual size are quiet; minor news doesn't count.
    usual = weekly.usual_move(ws)
    assert usual >= weekly.MIN_MOVE
    for w in ws:
        if w.excess is not None and abs(w.excess) < usual:
            assert w.verdict == "Quiet"
    early = weekly.weeks(s, KVB, 8, today=days[12])
    minor = next(w for w in early if any(i.title == "minor" for i in w.items))
    assert minor.tone == 0  # importance 2 is below the line


def test_verdicts():
    def week(excess, tone):
        w = weekly.Week(start=None, end=None)
        w.excess, w.tone = excess, tone
        return w

    ws = [week(0.04, 5), week(-0.04, 5), week(0.04, 0), week(0.001, 9), week(None, 3)]
    weekly._judge(ws)
    assert [w.verdict for w in ws] == [
        "In line with the news",
        "Against the news",
        "Moved without news",
        "Quiet",
        "Quiet",
    ]
