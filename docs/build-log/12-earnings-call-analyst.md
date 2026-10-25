# Step 12: Earnings Call Analyst and the promise ledger

**Goal:** for every stock you own, read each earnings call and keep what matters. That means what management said and what analysts worried about, what changed since the last call, and every promise with a date, so the next call can be checked against it.

## What was added

| Piece | Why |
| --- | --- |
| `concalls`, `concall_points`, `promises` tables (migration 0012) | One row per transcript filing; key points with quotes; the promise ledger with due dates and status |
| `agents/concalls.py` | Finds transcript filings of owned stocks and reads each call once. Follows links in covering letters. Asks Sonnet for a structured reading, checks quotes, updates earlier promises |
| `concalls` job, 07:30 daily | New transcripts are read before the 08:00 digest |
| `sna concalls run/list/show/promises/reset` | Read, browse, check promises, read again |
| Digest | New **Earnings calls** section: summary, points to watch, changes, promises made |
| Stock page | New **Earnings calls** tab with the promise ledger and a list of transcripts that could not be read |

## What Sonnet is asked for

- **Summary:** three or four sentences on the quarter, and management's tone (positive, neutral, cautious, negative).
- **Key points:** 6-15 of them, each tagged guidance, demand, margins, capex, order book, risk, initiative or other, with a sentiment for shareholders and the speaker's own words.
- **Promises:** commitments with a target and a time. "Plant 2 by Q3 FY27" counts; "good growth ahead" does not. Each promise gets a due date: Q3 FY27 becomes 31 Dec 2026, FY28 becomes 31 Mar 2028.
- **Updates to earlier promises:** each still-open promise is shown with an id. The call marks it on track, kept, delayed, revised or dropped when management mentions it again.
- **What analysts pressed on,** and whether the answer was direct, partial or evasive.
- **Changes since the previous call:** new topics, dropped topics, tone changes, revised targets. The previous call's summary and points are in the prompt, not its whole transcript.
- **Points to watch:** three to five, most important first.

## Things real transcripts do

- **Filed twice.** The same transcript goes to BSE and NSE minutes apart. Copies within 7 days are grouped, the one with the most text is read, and the rest are recorded as duplicates.
- **A letter instead of a transcript.** Some companies file a one-page letter saying the transcript is on their website. When a filing has under 4,000 characters, the links in its text and in the PDF's link annotations are tried, transcript-named and `.pdf` links first, exchange links skipped. A readable transcript is saved under `data/concalls/`.
- **Scanned PDFs and AGMs.** A scan has no text to read, and an AGM is not an earnings call. Both are recorded with the reason and shown under "Transcripts not read" on the Stock page.
- **Invented quotes.** Every quote is checked against the transcript, ignoring case, spacing and punctuation. Quotes that aren't found are kept in the database but not shown, and `sna concalls show` flags them.
- **Very long calls.** Transcripts are cut at 240,000 characters (about 60,000 tokens). The call's note says so when that happens.

## Cost

About $0.10 a call with Sonnet: a 60-page transcript is roughly 25,000 tokens in, plus a few thousand out. A year of calls for 12 owned stocks is about 50 calls, about $5. `sna concalls run` prints the number of calls and a rough cost first, and asks before spending more than $2. The monthly budget still stops it at $20.

## How to check it

```bash
git pull
uv sync
make migrate
uv run sna filings list --type concall_transcript --limit 30
uv run sna filings attachments --pdf important
uv run sna concalls run
uv run sna concalls list --all
uv run sna concalls show LT
uv run sna concalls promises --open
make ui
```

`filings attachments --pdf important` downloads transcripts, results and other important PDFs that a backfill skipped; it now picks those types before its 200-file limit, which it previously applied first. `concalls run` reads the last 400 days by default. Once the results look right, `uv run sna concalls run --since 2023-10-01` reads the older calls. This month's budget may stop it partway; the next run continues where it stopped.

## Tweet draft

> Agent #11: the Concall Analyst. Each earnings call of a stock I own becomes one page: guidance, demand, margins, what analysts pushed on and whether management dodged, and what changed since last quarter. Every promise ("plant by Q3 FY27") goes in a ledger with a due date, and the next call marks it kept, delayed or quietly dropped. #BuildInPublic
