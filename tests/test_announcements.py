import json
from datetime import datetime

import pytest
from conftest import FIXTURES

from stock_news_analyzer.sources.announcements import (
    IST,
    bse_total_rows,
    classify,
    parse_bse,
    parse_nse,
)
from stock_news_analyzer.text import clean


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_bse_live_record():
    # The first row is BSE's live response for L&T on 21 Oct 2026.
    data = _load("bse_announcements_LT.json")
    rows = parse_bse(data)
    assert bse_total_rows(data) == 2
    order = rows[0]
    assert order.source == "bse"
    assert order.source_id == "aa2ff20b-8cd0-4341-bc00-987cf8b20788"
    assert order.exchange_code == "500510"
    assert order.title == "L&T Wins Orders (Large*) in New Delhi and Andhra Pradesh"
    assert order.published_at == datetime(2026, 10, 21, 9, 45, 2, 467000, tzinfo=IST)
    assert order.attachment_urls[0].endswith("/AttachLive/42761949-c90f-4c0c-8fad-6d79416f15d2.pdf")
    assert order.attachment_urls[1].endswith("/AttachHis/42761949-c90f-4c0c-8fad-6d79416f15d2.pdf")
    assert order.attachment_bytes == 3384935
    assert order.doc_type == "order_win"
    assert rows[1].doc_type == "concall_transcript"


def test_parse_nse_live_record():
    rows = parse_nse(_load("nse_announcements_LT.json"))
    order = rows[0]
    assert order.source == "nse"
    assert order.source_id == "106822983"
    assert order.isin == "INE018A01030"
    assert order.published_at == datetime(2026, 10, 21, 9, 46, 54, tzinfo=IST)  # dissemination
    assert order.attachment_urls == [
        "https://nsearchives.nseindia.com/corporate/PAM_21102026094637_PressRelease21102026.pdf"
    ]
    assert order.doc_type == "order_win"
    assert rows[1].doc_type == "credit_rating"


def test_parsers_skip_rows_without_id_or_time():
    assert parse_bse({"Table": [{"NEWSID": "x"}, {"DissemDT": "2026-10-21T09:45:02"}]}) == []
    assert parse_nse([{"seq_id": "1"}, {"exchdisstime": "21-Oct-2026 09:46:54"}]) == []
    assert parse_bse({}) == [] and bse_total_rows({}) == 0


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("Earnings Call Transcript", "concall_transcript"),
        ("Audio Recording of Earnings Call", "concall_audio"),
        ("Investor Presentation", "investor_presentation"),
        ("Financial Results for the quarter ended September 30, 2026", "results"),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "concall_schedule"),
        ("Credit Rating", "credit_rating"),
        ("Board Meeting Intimation", "board_meeting"),
        ("Change in Directors", "other"),
    ],
)
def test_classify(subject, expected):
    assert classify(subject, "", None) == expected


def test_audio_field_marks_concall_audio():
    assert classify("Company Update", "", None, {"AUDIO_VIDEO_FILE": "x.mp3"}) == "concall_audio"


def test_clean_removes_html_and_doubled_quotes():
    assert clean("Karur Vysya Bank Ltd has informed BSE about : <BR><BR>1. Result") == (
        "Karur Vysya Bank Ltd has informed BSE about : 1. Result"
    )
    assert clean("Schedule of Analyst / Institutional Investors'' Meet") == (
        "Schedule of Analyst / Institutional Investors' Meet"
    )
    assert clean("A &amp; B") == "A & B" and clean(None) == ""


@pytest.mark.parametrize(
    "subject, title, expected",
    [
        # Titles seen in the first live run (21 Oct 2026).
        (
            "Analysts/Institutional Investor Meet/Con. Call Updates",
            "Karur Vysya Bank Limited has informed the Exchange about Link of Recording",
            "concall_audio",
        ),
        (
            "Newspaper Publication",
            'Karur Vysya Bank Ltd has informed BSE regarding "Newspaper Publication of '
            'Financial Results"',
            "newspaper_publication",
        ),
        (
            "Copy of Newspaper Publication",
            "Karur Vysya Bank Limited has informed the Exchange about Copy of Newspaper",
            "newspaper_publication",
        ),
    ],
)
def test_classify_live_titles(subject, title, expected):
    assert classify(subject, title, None) == expected
