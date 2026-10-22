# Step 10: Move Explainer (agent 7)

**Goal:** for every unusual day (a stock's move against the Nifty 50 beyond 2 standard deviations of its last 60 days), say why it probably happened, how sure we are, and what the evidence is. These explanations are the first layer of "why stocks move" that the rest of the system, and a future model, builds on.

## What was added

| Piece | Why |
| --- | --- |
| `move_explanations` table (migration 0010) | Per stock and day: cause, confidence, explanation, the document ids used, model |
| `agents/explain.py` | Gathers the evidence for a day and asks Claude Sonnet (effort `medium`) for a structured answer |
| `explain` job at 07:45 | Explains the last two weeks' unusual days up to yesterday, before the 08:00 digest |
| `sna explain run/list/reset`, `make explain` | Run (with a cost estimate first), read, redo |
| Digest, Stock page, Today cards | Likely cause under each unusual day; chart hover; an Unusual days tab; a line on the card |
| News triage tweaks | "Hot stocks" and recommendation roundups count as off-topic; order size judged against the company; summaries no longer name the source |

## What Sonnet sees for one day

- The numbers: the stock's, the Nifty 50's and the sector index's return, the excess return and z-score, and the stock's previous five sessions.
- Corporate actions with that ex-date (bonus, split, dividend).
- Filings from two sessions before to the next morning's open, with the first 700 characters of results, orders, presentations, transcripts and ratings.
- News from the same window, without articles the triage marked off-topic or repeated, most important first, with the triage's topic, importance and summary.
- When each document came out relative to the day: before it, on it, or after the close. Something published after the close cannot have caused the move, but the next morning's papers often say why it happened.

## What it answers

| Field | Values |
| --- | --- |
| cause | results, order, company_news, sector, market, corporate_action, flows (block deals, index changes, lock-in expiry, fund flows), unexplained |
| confidence | high (a document clearly explains it and the timing fits), medium, low |
| explanation | two or three sentences, at most 60 words, including anything that cuts against it |
| evidence | the documents relied on; ids it was not shown are dropped, and unexplained keeps none |

"Unexplained" is a valid answer: the instructions ask for it rather than a guess. Those days are worth a look by hand, and a model trained later learns from them too.

## Cost

About 4,000-6,000 tokens in and a few hundred out per day with Sonnet 5.5 ($2 / $10 per million), so roughly $0.02 per unusual day. Each stock has about one unusual day a month, so the daily job costs cents. The three-year history (several hundred days across 13 stocks) is several dollars: start with the last year.

## How to check it

```bash
git pull
uv sync
make migrate
uv run sna explain run --since 2026-07-01 --limit 10
uv run sna explain list --days 120
uv run sna explain run --since 2025-10-01
make scheduler
make ui
```

The first run prints how many days are waiting and a rough cost before it starts. `make scheduler` rebuilds the scheduler with the 07:45 explain job.

## Tweet draft

> Agent #7: the Move Explainer. Every time one of my stocks moves more than 2σ against the Nifty, Claude Sonnet reads that day's filings, the triaged news (the morning after included), the sector and the market, and writes the likely cause, how sure it is and which documents back it. "Unexplained" is allowed. ~2 cents a day. #BuildInPublic
