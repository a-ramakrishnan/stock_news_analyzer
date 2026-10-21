# Step 5: Price & Label (agent 5)

**Goal:** measure what news actually did to a stock. Daily prices for every NSE stock, each watchlist stock's move against the Nifty 50 and its sector index, unusual days flagged, and every filing and article labelled with the stock's return over the next 1, 5 and 20 trading days. No charts, no indicators: prices are only a measuring stick.

## What we learned before writing code

Tested on NSE's live files from a Mac (21 Oct 2026):

| File | 16 Oct | 19 Oct | 20 Oct | 21 Oct |
| --- | --- | --- | --- | --- |
| Full bhavcopy (`sec_bhavdata_full`) | ok | ok | ok, **but contains 19 Oct's data** | ok |
| New-format bhavcopy (UDiFF) | ok | ok | 404 | ok |
| Index closes (`ind_close_all`) | ok | ok | 404 | ok |

20 October was a market holiday. Had dates been taken from file names, the 20th would have become a fake trading day with no movement. So the **trading date is always read from inside the file**, and a missing index file means "no trading that day".

The full bhavcopy is the price source: it reaches back years (the new format only started in mid-2024), includes delivery %, and its closes match the new format exactly (L&T: 3627.10, 3661.90, 3636.00).

## What was added

| Piece | Why |
| --- | --- |
| `prices_daily` | Every NSE symbol, series and day: OHLC, previous close, volume, turnover, trades, delivery %. ISIN linked for the ordinary-share series |
| `index_daily` | Every NSE index's close, with P/E, P/B and dividend yield |
| `stock_moves` | Per watchlist stock and day: return, Nifty 50 and sector returns, excess returns, z-score, unusual flag |
| `event_labels` | Per filing/article and company: day0 and the stock's return, return vs Nifty 50 and vs sector over 1, 5, 20 trading days |
| `sector_index` in `config/watchlist.yaml` | L&T → Nifty Infrastructure, KVB → Nifty Bank, MSUMI → Nifty Auto |
| Raw files | Kept gzipped under `data/prices/<year>/` |
| `sna prices fetch / backfill / moves / indices`, `sna labels update / list`, `make prices` | Daily use, history, and checking results |

## How the numbers are calculated

- **Daily return** = close ÷ (previous close × corporate-action factor − dividend) − 1. See "First live run" below for why the adjustment is needed.
- **Excess return** = stock return − benchmark return (Nifty 50, and the sector index).
- **Unusual day:** excess return vs Nifty 50 more than `UNUSUAL_THRESHOLD` (default 2.0) × the standard deviation of the previous 60 trading days (needs at least 20 days of history). 2.0 flags about 5% of days, roughly one per stock per month.
- **day0** for a filing or article: the same trading day if published before 15:30 IST, otherwise the next trading day. Weekends and holidays roll forward.
- **Labels** compound daily returns from day0 over 1, 5 and 20 trading days. A label stays incomplete until all 20 days have happened, and is recomputed on each `labels update` until then.

Example from the real data: on 19 Oct L&T rose 0.96% while the Nifty 50 fell 1.11%, so it beat the market by 2.07% (and Nifty Infrastructure by about 2%).

## First live run (Mac, 21 Oct 2026)

The 3-year backfill loaded 751 trading days (1.4 million price rows, 162–167 indices a day); all three sector index names matched NSE's. L&T's 19 Oct check held: +0.96% vs Nifty −1.11%, flagged unusual (z = +2.6).

It also exposed a wrong assumption: **NSE's full bhavcopy does not adjust the previous close on ex-dates.**

| Stock | Ex-date | Action | Stored prev close → close | Unadjusted | Adjusted |
| --- | --- | --- | --- | --- | --- |
| MSUMI | 18 Jul 2025 | Bonus 1:2 | 64.47 → 43.52 | −32.5% | +1.26% |
| KARURVYSYA | 26 Aug 2025 | Bonus 1:5 | 263.95 → 216.10 | −18.1% | −1.75% |

Each fake crash also inflated the "usual move" for the next 60 days, hiding real unusual days. Fix: a `corporate_actions` table (migration 0007) filled from NSE's corporate-actions API for watchlist stocks on every `prices fetch`/`backfill`; on an ex-date the previous close is multiplied by the price factor (bonus a:b → b/(a+b), split → new/old face value) and dividends are subtracted, so returns are total returns. NSE's record for KVB carries an older ISIN (`INE036D01010`), so actions are matched on NSE symbol. `sna prices actions` lists them.

## How to check it

```bash
git pull
make migrate
make watchlist
uv run sna prices backfill --since 2023-10-01
uv run sna prices actions
uv run sna prices indices
uv run sna prices moves LT --days 10
uv run sna prices moves --unusual --days 250
uv run sna labels update
uv run sna labels list LT --type order_win
```

`make watchlist` stores the sector indices. The backfill makes about 1,500 requests (roughly 25–40 minutes) and prints one line per day with the time left, e.g. `[123/780] 2024-04-15  loaded 2,612 prices, 130 indices  ~18 min left`. Stopping it with Ctrl+C and re-running skips days already stored (`--force` downloads them again). `sna filings fetch/backfill` now print a line per company, exchange and 30-day window too.

## Tweet draft

> Agent #5: Price & Label. No charts. Prices are only a ruler: how much did each filing and headline move the stock vs the Nifty, 1, 5 and 20 days later? On 19 Oct L&T beat the Nifty by 2.07%. Fun lesson: NSE answers a holiday's URL with yesterday's file. Never trust the filename. #BuildInPublic
