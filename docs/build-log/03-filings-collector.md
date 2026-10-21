# Step 3: Filings Collector (agent 2)

**Goal:** every corporate announcement for every watchlist company, from both exchanges, stored unchanged with the minute it became public. Order wins, results, concall transcripts and credit ratings all arrive here first, before the news.

## What we learned before writing code

Both exchanges sit behind Akamai bot protection. Tested from a Mac (21 Oct 2026):

| Attempt | Result |
| --- | --- |
| BSE announcements API with a normal HTTP client | 403 Access Denied |
| Same, after loading BSE's website for cookies | 403 Access Denied |
| Same, with `curl_cffi` presenting Chrome's TLS fingerprint | 200, JSON |
| NSE announcements API with `curl_cffi` | 200, JSON with direct PDF links |
| NSE announcements RSS feed | 200 (no tricks needed) |

So the collector uses `curl_cffi` for both exchanges, waits a second between requests, and refreshes cookies once on a 403. The parsers were written against real responses for L&T, which are kept as test fixtures.

## What was added

| Piece | Why |
| --- | --- |
| `documents` table | Every collected item, never edited: title, subject, type, `published_at` (exchange dissemination time, IST), `first_seen_at`, attachment path and SHA-256, extracted text, and the raw JSON record |
| `document_companies` table | Links a document to the companies it is about (news in step 4 can mention several) |
| `sources/exchange_http.py` | Browser-like access to BSE and NSE |
| `sources/announcements.py` | Turns BSE and NSE records into one shape; classifies each filing by keyword rules |
| `agents/filings.py` | Fetches per company and exchange, skips what's stored, downloads attachments, extracts PDF text |
| `sna filings fetch / backfill / list / show / attachments` | Daily use, history, and checking what came in |

## Filing types

Keyword rules, checked in order: `concall_transcript`, `concall_audio`, `newspaper_publication`, `investor_presentation`, `results`, `concall_schedule`, `order_win`, `credit_rating`, `board_meeting`, `shareholding`, `insider_trading`, `other`. The first four are flagged as concall material for the Concall Analyst (agent 11). The rules are deliberately simple; the Event Extractor (agent 7) will read the text properly.

## Decisions

- **Both exchanges, kept separate.** Most companies file the same announcement on BSE and NSE. Both copies are stored (with their own timestamps); the Triage agent (step 6) will merge duplicates.
- **Point in time:** `published_at` is the exchange's dissemination time (BSE `DissemDT`, NSE `exchdisstime`), not the company's submission time.
- **Resume from the latest stored filing** minus one day of overlap; the unique (source, source_id) key makes re-runs safe.
- **Backfills download PDFs only for important filings** (results, concall material, orders, ratings, concall schedules) to save disk; `sna filings attachments --pdf all` fills in the rest later.
- **One failing exchange doesn't stop the other**; errors are listed at the end and the command exits non-zero.
- **Scanned PDFs** have no text layer; they are kept with `text_status = empty` for OCR later.

## How to check it

`make filings` fetches the last 7 days the first time; `show` takes an id from `list` (17 was the L&T order win).

```bash
make migrate
make filings
uv run sna filings list
uv run sna filings show 17
uv run sna filings backfill --since 2023-10-01
make test
```

## First live run (Mac, 21 Oct 2026)

`make filings` stored 25 filings for the last 7 days and downloaded 25 attachments: today's L&T order win (BSE 09:45:02, NSE 09:46:54), and Karur Vysya Bank's results, investor presentation, call recording and transcript on both exchanges. It also showed what to fix:

| Problem | Fix |
| --- | --- |
| NSE's copy of the L&T order win failed to parse. NSE lists it at 3.23 MB (BSE's copy is 3,384,935 bytes), but an earlier download came in at 2,523,136 bytes: the download was cut short | Downloads are checked against Content-Length and, for PDFs, the `%%EOF` end marker; incomplete files are retried up to 3 times |
| "Link of Recording" classified as `concall_schedule` | Any "recording" now means `concall_audio` |
| "Newspaper Publication" of results classified as `results` | New `newspaper_publication` type, checked before `results` |
| `<BR><BR>` and doubled quotes (`Investors''`) in titles | Titles, subjects and categories are cleaned |
| pypdf printed warnings for minor PDF defects | pypdf logging is limited to errors |

For filings stored before the fix: `sna filings reclassify` re-derives types and titles from the raw records, and `sna filings attachments --retry-failed` re-downloads files that failed to parse.

## Tweet draft

> Agent #2: Filings Collector. Each run pulls BSE + NSE announcements for my stocks, saves the PDF, extracts the text and records the exact minute it went public. Today's L&T order win was on the exchange at 09:45:02, long before any headline. Lesson: both exchanges block bots; a Chrome-like TLS fingerprint gets through. #BuildInPublic
