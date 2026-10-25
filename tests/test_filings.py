import json
from datetime import date

import pytest
from conftest import FIXTURES

from stock_news_analyzer.agents import filings as fl
from stock_news_analyzer.agents import watchlist as wl
from stock_news_analyzer.models import Document
from stock_news_analyzer.sources.exchange_http import ExchangeError
from stock_news_analyzer.sources.securities import parse_bse_scrips, parse_nse_equity_list

pytestmark = pytest.mark.db


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF with a text layer."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


class FakeClient:
    """Stands in for ExchangeClient: serves the fixture responses and records calls."""

    def __init__(self, fail_nse=False, complete=True):
        self.complete = complete
        self.bse = json.loads((FIXTURES / "bse_announcements_LT.json").read_text())
        self.nse = json.loads((FIXTURES / "nse_announcements_LT.json").read_text())
        self.fail_nse = fail_nse
        self.calls = []
        self.downloads = []

    def bse_announcements(self, scrip_code, start, end, page=1):
        self.calls.append(("bse", scrip_code, start, end, page))
        return self.bse if scrip_code == "500510" else {"Table": [], "Table1": [{"ROWCNT": 0}]}

    def nse_announcements(self, symbol, start, end):
        self.calls.append(("nse", symbol, start, end))
        if self.fail_nse:
            raise ExchangeError("NSE returned HTTP 403")
        return self.nse if symbol == "LT" else []

    def download(self, exchange, urls):
        self.downloads.append(urls[0])
        if "AttachLive" in urls[0] and "transcript" in urls[0]:
            # Older BSE files live under AttachHis: the first URL fails, the second works.
            return urls[1], make_pdf("Transcript of the Q2 earnings call"), True
        if urls[0].endswith(".pdf"):
            return urls[0], make_pdf("Order worth Rs 1240 crore"), self.complete
        raise ExchangeError("not found")


@pytest.fixture
def watchlist(session):
    wl.load_master(
        session,
        parse_nse_equity_list((FIXTURES / "EQUITY_L.csv").read_text(encoding="utf-8")),
        bse=parse_bse_scrips((FIXTURES / "bse_scrips.json").read_text()),
    )
    wl.add_equity(session, wl.resolve(session, "LT"), owned=True)
    wl.add_equity(session, wl.resolve(session, "KARURVYSYA"), owned=True)
    return session


def test_date_chunks_cover_range_newest_first():
    chunks = list(fl.date_chunks(date(2026, 1, 1), date(2026, 3, 15), days=30))
    assert chunks[0] == (date(2026, 2, 14), date(2026, 3, 15))
    assert chunks[-1][0] == date(2026, 1, 1)
    assert sum((hi - lo).days + 1 for lo, hi in chunks) == 74


def test_extract_text_from_pdf():
    text, status = fl.extract_text(make_pdf("Hello filings"))
    assert (text, status) == ("Hello filings", "ok")
    assert fl.extract_text(b"not a pdf") == ("", "failed")


def test_collect_stores_filings_with_attachments_and_text(watchlist, tmp_path):
    client = FakeClient()
    collector = fl.FilingsCollector(watchlist, client, tmp_path)
    companies = fl.watchlist_companies(watchlist)
    result = collector.collect(companies, start=date(2026, 10, 1), end=date(2026, 10, 21))

    assert (result.new, result.already_had, result.attachments) == (4, 0, 4)
    assert not result.errors
    docs = {d.source_id: d for d in watchlist.query(Document)}
    order = docs["aa2ff20b-8cd0-4341-bc00-987cf8b20788"]
    assert order.doc_type == "order_win"
    assert order.text == "Order worth Rs 1240 crore" and order.text_status == "ok"
    assert (tmp_path / order.attachment_path).is_file()
    assert order.attachment_path.startswith("filings/INE018A01030/bse/2026-10/")
    assert len(order.attachment_sha256) == 64
    assert order.raw["HEADLINE"].startswith("L&T Wins Orders")

    transcript = docs["0b6e1c1e-0000-4000-8000-000000000002"]
    assert "/AttachHis/" in transcript.attachment_url  # fell back to the archive folder
    assert transcript.doc_type == "concall_transcript"

    listed = fl.recent_documents(watchlist, doc_type="order_win")
    assert {(d.source, c.nse_symbol) for d, c in listed} == {("bse", "LT"), ("nse", "LT")}


def test_collect_is_idempotent_and_resumes_from_latest(watchlist, tmp_path):
    client = FakeClient()
    collector = fl.FilingsCollector(watchlist, client, tmp_path)
    companies = fl.watchlist_companies(watchlist, "LT")
    collector.collect(companies, start=date(2026, 10, 1), end=date(2026, 10, 21))

    client.calls.clear()
    result = collector.collect(companies, end=date(2026, 10, 21))
    assert (result.new, result.already_had) == (0, 4)
    # Resumes from the latest stored filing (21 Oct) minus one day of overlap.
    assert {c[2] for c in client.calls} == {date(2026, 10, 20)}


def test_important_policy_skips_routine_attachments(watchlist, tmp_path):
    client = FakeClient()
    client.bse["Table"][0]["NEWSSUB"] = "Change in Directors"
    client.bse["Table"][0]["HEADLINE"] = "Appointment of director"
    collector = fl.FilingsCollector(watchlist, client, tmp_path, pdf_policy="important")
    collector.collect(fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1))
    routine = watchlist.query(Document).filter_by(doc_type="other").one()
    assert routine.attachment_path is None and routine.text_status == "pending"

    # Older important files are reached even when newer routine ones fill the limit.
    transcript = watchlist.query(Document).filter_by(doc_type="concall_transcript").one()
    transcript.attachment_path, transcript.text, transcript.text_status = None, None, "pending"
    watchlist.commit()
    assert collector.fetch_missing_attachments(limit=1) == 1
    watchlist.refresh(transcript)
    assert transcript.text_status == "ok" and routine.attachment_path is None

    # A re-download also tries BSE's archive folder: older files move from AttachLive.
    transcript.attachment_path, transcript.text_status = None, "failed"
    transcript.attachment_url = transcript.attachment_url.replace("/AttachHis/", "/AttachLive/")
    watchlist.commit()
    client.downloads.clear()
    assert collector.fetch_missing_attachments(limit=1) == 1
    assert "AttachLive" in client.downloads[0]  # tried first, then AttachHis served it
    watchlist.refresh(transcript)
    assert "AttachHis" in transcript.attachment_url and transcript.text_status == "ok"

    # A later run with the 'all' policy fills it in.
    fetched = fl.FilingsCollector(watchlist, client, tmp_path).fetch_missing_attachments()
    watchlist.refresh(routine)
    assert fetched == 1 and routine.text_status == "ok"


def test_one_failing_source_does_not_stop_the_other(watchlist, tmp_path):
    client = FakeClient(fail_nse=True)
    collector = fl.FilingsCollector(watchlist, client, tmp_path, pdf_policy="none")
    result = collector.collect(fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1))
    assert result.new == 2  # the BSE filings
    assert result.attachments == 0
    assert result.errors == ["LT NSE: NSE returned HTTP 403"]


def test_bse_pagination_follows_row_count(watchlist, tmp_path):
    client = FakeClient()
    first, second = client.bse["Table"]
    pages = {
        1: {"Table": [first], "Table1": [{"ROWCNT": 2}]},
        2: {"Table": [second], "Table1": [{"ROWCNT": 2}]},
    }
    client.bse_announcements = lambda code, start, end, page=1: pages[page]
    collector = fl.FilingsCollector(watchlist, client, tmp_path, pdf_policy="none")
    result = collector.collect(
        fl.watchlist_companies(watchlist, "LT"),
        start=date(2026, 10, 1),
        end=date(2026, 10, 21),
        sources=("bse",),
    )
    assert result.new == 2


def test_cli_list_and_show(watchlist, tmp_path, test_database_url, monkeypatch):
    from typer.testing import CliRunner

    from stock_news_analyzer.cli import app

    fl.FilingsCollector(watchlist, FakeClient(), tmp_path).collect(
        fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    runner = CliRunner()

    result = runner.invoke(app, ["filings", "list", "LT", "--type", "order_win"])
    assert result.exit_code == 0, result.stdout
    assert "2026-10-21 09:45  BSE  LT" in result.stdout
    assert "L&T Wins Orders" in result.stdout

    doc_id = watchlist.query(Document).filter_by(source="bse", doc_type="order_win").one().id
    result = runner.invoke(app, ["filings", "show", str(doc_id)])
    assert result.exit_code == 0, result.stdout
    assert "published  2026-10-21 09:45:02 IST" in result.stdout
    assert "Order worth Rs 1240 crore" in result.stdout

    result = runner.invoke(app, ["filings", "list", "MSUMI"])
    assert result.exit_code == 1 and "not on the watchlist" in result.stdout


def test_reclassify_updates_stale_types_and_titles(watchlist, tmp_path):
    fl.FilingsCollector(watchlist, FakeClient(), tmp_path, pdf_policy="none").collect(
        fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    doc = watchlist.query(Document).filter_by(source="bse", doc_type="order_win").one()
    doc.doc_type, doc.title = "other", "old <BR> title"
    watchlist.commit()

    assert fl.reclassify(watchlist) == 1
    watchlist.refresh(doc)
    assert doc.doc_type == "order_win"
    assert doc.title == "L&T Wins Orders (Large*) in New Delhi and Andhra Pradesh"
    assert fl.reclassify(watchlist) == 0


def test_retry_failed_downloads_again(watchlist, tmp_path):
    client = FakeClient()
    collector = fl.FilingsCollector(watchlist, client, tmp_path)
    collector.collect(
        fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    doc = watchlist.query(Document).filter_by(source="nse", doc_type="order_win").one()
    doc.text, doc.text_status = "", "failed"
    watchlist.commit()

    assert collector.fetch_missing_attachments() == 0  # has a file already; not retried
    assert collector.fetch_missing_attachments(retry_failed=True) == 1
    watchlist.refresh(doc)
    assert doc.text_status == "ok" and doc.text == "Order worth Rs 1240 crore"


def test_file_broken_at_source_is_kept_as_partial(watchlist, tmp_path):
    client = FakeClient(complete=False)
    fl.FilingsCollector(watchlist, client, tmp_path).collect(
        fl.watchlist_companies(watchlist, "LT"), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    doc = watchlist.query(Document).filter_by(source="nse", doc_type="order_win").one()
    assert doc.text_status == "partial" and doc.text == "Order worth Rs 1240 crore"
    assert (tmp_path / doc.attachment_path).is_file()


def test_progress_reports_each_window(watchlist, tmp_path):
    lines = []
    fl.FilingsCollector(watchlist, FakeClient(), tmp_path, pdf_policy="none").collect(
        fl.watchlist_companies(watchlist, "LT"),
        start=date(2026, 9, 1),
        end=date(2026, 10, 21),
        progress=lines.append,
    )
    assert lines[0] == "LT BSE 2026-09-22..2026-10-21: 2 new, 0 already stored, 0 PDFs"
    assert len(lines) == 4  # two 30-day windows for each exchange


class _NulPage:
    def extract_text(self):
        return "IDFC FIRST Bank\x00 Limited\x00"


class _NulReader:
    def __init__(self, _stream):
        self.pages = [_NulPage()]


def test_extract_text_drops_nul_characters(monkeypatch):
    monkeypatch.setattr(fl, "PdfReader", _NulReader)
    assert fl.extract_text(b"%PDF") == ("IDFC FIRST Bank Limited", "ok")


@pytest.mark.db
def test_pdf_text_with_nul_characters_is_stored(watchlist, tmp_path, monkeypatch):
    # Some exchange PDFs put NUL characters in their text; PostgreSQL rejects those, which
    # used to stop the whole collection with a DataError.
    monkeypatch.setattr(fl, "PdfReader", _NulReader)
    collector = fl.FilingsCollector(watchlist, FakeClient(), tmp_path)
    result = collector.collect(
        fl.watchlist_companies(watchlist), start=date(2026, 10, 1), end=date(2026, 10, 21)
    )
    assert not result.errors
    texts = [d.text for d in watchlist.query(Document) if d.text_status == "ok"]
    assert texts and all(t == "IDFC FIRST Bank Limited" for t in texts)
