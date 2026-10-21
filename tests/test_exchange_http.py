from types import SimpleNamespace

import pytest

from stock_news_analyzer.sources.exchange_http import ExchangeClient, ExchangeError, is_complete

PDF = b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF\n"


def test_is_complete():
    assert is_complete(PDF, {"content-length": str(len(PDF))})
    assert is_complete(b"not a pdf", {})
    assert not is_complete(PDF[:50], {"content-length": str(len(PDF))})  # cut short
    assert not is_complete(PDF[:-7], {})  # PDF without its end marker


def _client(responses):
    """An ExchangeClient whose HTTP calls return `responses` in order."""
    client = ExchangeClient(delay=0)
    client._session = lambda exchange: object()
    calls = []

    def fake_get(session, url, **kwargs):
        calls.append(url)
        body, status, ctype = responses.pop(0)
        return SimpleNamespace(content=body, status_code=status, headers={"content-type": ctype})

    client._get = fake_get
    return client, calls


def test_download_retries_a_truncated_file():
    client, calls = _client([(PDF[:-7], 200, "application/pdf"), (PDF, 200, "application/pdf")])
    url, content, complete = client.download("nse", ["https://x/a.pdf"])
    assert content == PDF and complete and len(calls) == 2


def test_download_falls_back_to_next_url_on_404():
    client, calls = _client([(b"<html>", 404, "text/html"), (PDF, 200, "application/pdf")])
    url, _, _ = client.download("bse", ["https://x/AttachLive/a.pdf", "https://x/AttachHis/a.pdf"])
    assert url.endswith("/AttachHis/a.pdf")


def test_download_keeps_a_file_that_is_broken_at_the_source():
    # NSE served the same 2,523,136-byte truncated PDF on every attempt (21 Oct 2026).
    client, calls = _client([(PDF[:-7], 200, "application/pdf")] * 3)
    url, content, complete = client.download("nse", ["https://x/a.pdf"])
    assert content == PDF[:-7] and not complete and len(calls) == 2


def test_download_gives_up_when_truncation_keeps_changing():
    client, _ = _client(
        [
            (PDF[:-7], 200, "application/pdf"),
            (PDF[:-9], 200, "application/pdf"),
            (PDF[:-11], 200, "application/pdf"),
        ]
    )
    with pytest.raises(ExchangeError, match="incomplete download"):
        client.download("nse", ["https://x/a.pdf"])
