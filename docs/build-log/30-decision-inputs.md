# Step 30: Decision inputs

**Goal:** help decide how to shape the portfolio. Rules of thumb such as "a big order win lifts L&T" or "good results with a profit fall sink a stock" are tested against what happened, then used, with the evidence shown, for each stock owned.

Three pull requests:

| Part | What |
| --- | --- |
| 1. The Nifty 50 | All Nifty 50 companies collected, as study-only stocks, without spending the AI budget (this part) |
| 2. The evidence | An event study: for each kind of event (order wins by size, results by revenue and profit growth, management exits, pledges, rating actions, block deals...), how the stock moved against the Nifty 50 and its sector over 1, 5 and 20 trading days, how often it went each way, and over how many cases |
| 3. The portfolio | Per stock owned, its recent events with what similar events did, adding up to a lean (positive, neutral or negative) and the reasons; sector weights against the Nifty 50. Inputs, not advice: no buy or sell calls |

## Part 1: the Nifty 50

More companies make the evidence worth trusting: ten stocks give a handful of large order wins, fifty give dozens.

- **`sna watchlist nifty50`** downloads NSE's list of the index's current members (`ind_nifty50list.csv`, beside the Nifty 500 list the app already reads), adds the ones not on the watchlist, then loads their history and their results from NSE's XBRL files. NSE changes the index twice a year; running it again adds the newcomers.
- **Sector benchmarks** come from NSE's industry for each company, e.g. Construction and Capital Goods → Nifty Infrastructure, Financial Services → Nifty Financial Services, or Nifty Bank for a bank. An index NSE doesn't publish is left out.
- **Study only:** a new column on the watchlist. Study-only stocks get filings, news, prices, labels and results, and the Haiku agents read them (news triage, events, orders). They get no Sonnet work: earnings calls, promises and the explanation of unusual days, which would cost $15–30 a quarter for 40 more companies. On Today they are one table, unusual moves first, instead of forty cards; in the digest they appear in the sections (results, orders, events, flags), not one by one. Unticking Study only on Manage stocks follows one fully; a stock owned, or added by hand, always is.
- **The backlog:** loading forty companies' history leaves months of filings and news to read. Triage, events and orders now read the last three days first, and the events and orders agents cap their calls per scheduled run (25 and 15), so the backlog is read over the following days within the budget, and today's news is never stuck behind it.

### Checked

Tests cover the list parser, adding members (study-only, sector benchmarks, a bank, an index NSE doesn't publish, stocks already followed left alone, running it twice), the command, study-only stocks left out of the scheduled move explanations, fresh news triaged before a backlog, and the Study only column on Manage stocks. Today and Manage stocks were checked on the demo database.

## Part 2: the evidence

`agents/study.py` turns everything stored into cases and measures what followed each one. No AI: it reads what the agents already wrote.

| Kind | From | Dated by |
| --- | --- | --- |
| Results: revenue and profit up (or up 20%+), revenue up and profit down, revenue down and profit up, both down, little change (within ±2%), swung to a loss, back to a profit | Each quarter's figures (XBRL or the Results Reader) against the same quarter a year before | The results filing, the first in the 100 days after the quarter ended |
| Order win: large (5%+ of a year's revenue), medium (1–5%), small (under 1%), size not given | Each order-win filing, its orders' values added up, against revenue over the four quarters reported before it | The filing |
| Events, e.g. "Management change: negative", "Credit rating: positive" | The Event Extractor's events of importance 3 or more that the QA check passed or you accepted | The filing |
| Red flag, by kind | The Red-flag Monitor, flags raised from a filing | The filing |
| Block or bulk deal: buy or sell | NSE's deals | After that day's close |

Each case's move is the stock's return against the Nifty 50 (and its sector index) over 1, 5 and 20 trading days from day 0, the first close that could reflect the news, compounded as for the event labels. Per kind: the number of cases, the median, the 25th to 75th percentile ("the middle half") and the share that beat the benchmark. Under 10 cases is marked "few cases".

**The page:** What news does to prices, in Research. Choose the horizon, the benchmark and which kinds; the kinds are listed by group with a range bar (the middle half as a band, the median as a tick, zero as a line, on one scale), and a kind's cases are listed below with their 1, 5 and 20-day moves, stocks owned marked. "How to read this" spells out what the numbers mean and what they don't. `sna evidence` prints the same in the terminal.

**Point in time:** an order's size uses only revenue reported before the order; a quarter is compared with figures filed a year earlier. Nothing is measured with information that came later.

**What it can't say:** cases overlap (a results filing can also carry an event), the market moves for many reasons at once, and big news is often priced in within minutes, before the close. The medians show what usually followed, not what caused it.

### Checked

Tests cover each results kind, order sizes, the summary statistics, a full run over generated prices with results, an order, events (one counted, one routine, one failed by QA) and a deal, including day 0 for news after the close and the order sized only on revenue known then, and the CLI. The page was checked in light and dark on generated data for twelve stocks over fourteen months, where order wins worth 5% or more of a year's revenue had been given a drift: the study found it (median +2.3% over 5 days, 87% rising), and the other kinds stayed near zero.

## On the Mac

```
git checkout main
git pull
make start
uv run sna watchlist nifty50
```

The last command takes a few hours (filings and Google News for each company since October 2023); it can run overnight, and running it again fills any gaps.
