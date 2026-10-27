# Step 19: Bullion Analyst

**Goal:** explain each day's move in Indian gold and silver: how much came from the global price, how much from the rupee, and what was behind it.

## What was added

| Piece | Why |
| --- | --- |
| `market_series`, `bullion_moves` tables (migration 0021) | Daily global gold, silver and USD/INR closes; each day's move per metal with its split, z-score, driver and note |
| `sources/markets.py` | Daily closes from stooq's CSV download, or Yahoo Finance's chart API when stooq fails; no keys needed |
| `agents/bullion.py` (agent 13) | The split, unusual days, bullion news from Google News, notes by Sonnet |
| `bullion` job, 07:35 daily | After the New York close, before the digest |
| `sna bullion probe/run/list/explain`, `make bullion` | Check sources, run, see the days, explain one day |
| Digest and Today page | A "Bullion" section; the last 30 days per metal |

## The split

Indian gold and silver prices are mostly the global price × USD/INR, plus import duty and a local premium. With log returns the parts add up exactly:

> rupee move = global price move + USD/INR move + other

- **The Indian price** is the close of an NSE ETF holding the metal: GOLDBEES for gold, SILVERBEES for silver. The Price & Label agent already stores the whole NSE bhavcopy, ETFs included, so there is history from October 2023 and no new source to keep alive. Its `prev_close` is used for the return, so any split in the ETF's units is handled.
- **The global price** (US$ per troy ounce) and **USD/INR** come from stooq's daily CSV, or Yahoo's chart API (COMEX futures for the metals) if stooq refuses. `sna bullion probe` shows which one answers.
- **Other** is the rest: a duty change, the local premium or discount, and timing. The Indian close is at 15:30 IST, the global close in New York hours later, so a move late in the Indian evening shows up in "other" one day and back the next.
- **The driver, in code:** the part with at least 60% of the move and the same sign: global price, rupee or local. Otherwise mixed.

## Unusual days and notes

A day is unusual when its rupee move is beyond 2σ of the previous 60 days, the same rule as for stocks. For unusual days in the last 90 days (at most 10 a run), Sonnet gets:

- the split
- the previous five days
- bullion news from two days before to the next morning, from Google News searches like "gold price" India, gold prices Fed, gold ETF inflows and gold import duty

The day's news is searched first, so older days have their own news too. Sonnet answers with the driver, a note of two or three sentences, and the ids of the articles it used. Ids it wasn't given are dropped. A later run recomputes the split but keeps the note.

## Choices

- **ETFs rather than IBJA or MCX.** IBJA's rates and MCX's prices aren't offered as a free download, and scraping their pages would break. The ETFs trade on NSE, are already stored, and track the metal's Indian price closely. The cost is a small tracking difference, which lands in "other".
- **Notes only on unusual days.** A note on every day for two metals would cost about $0.40 a month and mostly say "it followed the global price". The split already says that in code.
- **Bullion news apart from company news.** It is stored as its own document type (`bullion_news`), linked to no company, so it stays out of the company pages and the Move Explainer.

## On the Mac

```
git checkout main
git pull
uv run sna db upgrade
uv run sna watchlist add gold
uv run sna watchlist add silver
uv run sna bullion probe
uv run sna bullion run
uv run sna bullion list gold --days 60
uv run sna bullion list gold --days 800 --unusual
```

## Next

Email delivery of the digest comes later. Of the agents, the Theme & Peer Analyst (14) and Analyst Q&A (17) are left.
