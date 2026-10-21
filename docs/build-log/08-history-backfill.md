# Step 8: History since October 2023

**Goal:** before Phase 2, fill the database with three years of history so the move explainer, the event study and the earnings-call comparison have something to learn from.

## What was added

| Piece | Why |
| --- | --- |
| `sna news backfill --since 2023-10-01` | Older articles. News feeds only carry the last few days, so history comes from Google News searches limited to a date range (`after:` / `before:`), one month per search per company |
| Automatic window splitting | Google returns at most 100 articles per search; a month that hits the limit is searched again in halves, down to single days, so busy months are not cut short |
| `make backfill` | Prices, filings, news and labels since `SINCE` (default 2023-10-01) in one command |

Prices (step 5) and filings (step 3) already had backfill commands; `make backfill` runs them in order and then recomputes the labels, so every filing and article gets its 1/5/20-day reaction.

## What to expect

| Part | Roughly |
| --- | --- |
| Prices | Already loaded on your Mac, so stored days are skipped: seconds |
| Filings | Three years for 3 companies on BSE and NSE, with PDFs for results, concall transcripts, presentations, order wins and ratings: the slowest part, tens of minutes |
| News | About 36 months × 3 companies ≈ 110 searches plus splits, 1 second apart: a few minutes |
| Labels | Under a minute |

Everything is safe to stop with Ctrl+C and re-run: stored items are skipped.

Google News coverage of older months is thinner than of recent ones and links go through Google's redirect, as for the daily search.

## How to check it

```bash
git pull
make scheduler-stop
make backfill
make scheduler
make ui
```

Then on the dashboard: **System** shows the stored counts, **What moves the stock** now has three years of filings behind each average, and the **Stock** page's 3Y range shows filings along the whole line.

## Tweet draft

> Before adding AI, give it a memory. One command now loads 3 years of NSE prices, every BSE/NSE filing (with results, concall and order-win PDFs) and the news archive for my watchlist. Fun detail: Google News caps a search at 100 results, so busy months get split in half until nothing is cut off. #BuildInPublic
