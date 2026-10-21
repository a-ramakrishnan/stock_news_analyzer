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

- **Daily return** = close ÷ NSE's previous close − 1. NSE adjusts the previous close on split and bonus ex-dates, so those don't look like crashes.
- **Excess return** = stock return − benchmark return (Nifty 50, and the sector index).
- **Unusual day:** excess return vs Nifty 50 more than 2× the standard deviation of the previous 60 trading days (needs at least 20 days of history).
- **day0** for a filing or article: the same trading day if published before 15:30 IST, otherwise the next trading day. Weekends and holidays roll forward.
- **Labels** compound daily returns from day0 over 1, 5 and 20 trading days. A label stays incomplete until all 20 days have happened, and is recomputed on each `labels update` until then.

Example from the real data: on 19 Oct L&T rose 0.96% while the Nifty 50 fell 1.11%, so it beat the market by 2.07% (and Nifty Infrastructure by about 2%).

## How to check it

```bash
git pull
make migrate
make watchlist
uv run sna prices backfill --since 2023-10-01
uv run sna prices indices
uv run sna prices moves LT --days 10
uv run sna prices moves --unusual --days 250
uv run sna labels update
uv run sna labels list LT --type order_win
```

`make watchlist` stores the sector indices. The backfill makes about 1,500 requests (roughly 25–40 minutes); it can be stopped and re-run safely.

## Tweet draft

> Agent #5: Price & Label. No charts. Prices are only a ruler: how much did each filing and headline move the stock vs the Nifty, 1, 5 and 20 days later? On 19 Oct L&T beat the Nifty by 2.07%. Fun lesson: NSE answers a holiday's URL with yesterday's file. Never trust the filename. #BuildInPublic
