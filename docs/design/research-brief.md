# Research brief

Version 1.1 · Nov 5, 2026 · @Ramki · changes are listed in [README.md](README.md)

A complete research output for one stock, on its own page (**Research brief**, in the Research group). Its layout follows the "briefing grammar" of Robyn's research results (meetrobyn.com), adapted to an Indian listed company and to what this system collects.

## What Robyn's research results do

Robyn is a general agent assistant; its research results (examples in its public site's code) all follow one layout:

1. **A lede, conclusion first:** a small eyebrow line (subject · date), the verdict as the title in one line, a two-line summary, three short opinionated stances ("Favor…", "Avoid…", "Diligence differently…"), a ruled row of three or four key numbers (some with meters, "6 / 10"), and a callout saying how the research was scoped.
2. **Numbered folds**, each with a count in its header ("Ranked comparable profiles · 10 companies"), opened only when needed.
3. **An evidence badge on every figure:** Disclosed, Parent proxy, Stale round, Low confidence, Not determinable; charts fade stale or low-confidence values.
4. **Entity cards:** where it is listed, a badge, a segment chip, three dated key numbers, then "Why it matters" and "Key risk", and an "Ask about …" button.
5. **Observed → Read pairs:** a fact, then what it means, kept apart.
6. **Decision cards** (Do now, Fix, Focus, Control, Target) ending with "Decisions to make now".
7. **Sources** at the end, each with a link.

Its finance agents also show their steps while working ("Reading three years of filings… Pulling the revenue series… Checking 90 days of news…"), state the cost of each run, mark surprises Confirmed or Uncertain, link every figure to its filing, and re-run showing "only the delta".

## The brief

### Lede

- **Eyebrow:** symbol · company · NSE · industry · brief of the date.
- **Title:** the verdict in one line. From the facts in 31.1 (valuation against its own history, the balance sheet); written by the model in 31.2.
- **Summary line:** the latest quarter's growth and margin.
- **Stances:** short labelled chips: Valuation, Balance sheet, Last quarter, Next, Watch (red flags). In 31.2, the model's three stances.
- **Ruled numbers:** trailing P/E (with its median), EPS growth, debt to equity, the next date; each with its evidence badge.
- **Callout:** what the brief is built from (filings, articles, quarters, prices) and what the badges mean.

### Evidence badges

| Badge | Meaning |
| --- | --- |
| Filed | As filed: an XBRL file or the exchange's own data |
| Read by AI | Read from a filing by an agent, QA passed |
| Market | Prices and NSE's index files |
| Stale | Older than a half year by now |
| Not disclosed | The filings don't carry it |

### Folds

| # | Fold | Content | Step |
| --- | --- | --- | --- |
| 1 | Valuation | Trailing P/E week by week against the middle 80% of its last three years and its median; sector index and Nifty 50 P/E; close, trailing EPS (its four quarters), market cap | 31.1 |
| 2 | Results | Eight quarters: revenue, profit, growth on the year, margin, EPS | 31.1 |
| 3 | Balance sheet and cash flow | Equity, borrowings, cash, net debt, debt to equity, cash from operations, capex, free cash flow, cash from operations to profit; the XBRL tag of each | 31.1 |
| 4 | Peers | An entity card for the stock and each peer: P/E, one-year change, latest revenue growth, market cap | 31.1; "Why it matters", "Key risk" and "Ask about" in 31.2 |
| 5 | What's coming | Board meetings announced, results due, ex-dates, promises falling due | 31.1 |
| 6 | Red flags | Open flags | 31.1 |
| 0 | The view | Observed → Read pairs citing fact ids; Why it matters and Key risk for the stock | 31.2 (only once a view is written) |
| 4 | Order book | Order book, years of revenue, book-to-bill, orders announced on the year, government share, largest client | 31.2 |
| 5 | Management | Promises kept and missed and the latest ones; management changes of the last two years | 31.2 |
| 6 | Ownership | Promoters, FIIs, DIIs, mutual funds, retail, pledges, the last five quarters | 31.2 |
| 8 | What moves this stock | The lean from the event study, its reasons and the last 12 weeks | 31.2 |
| 11 | What to watch and decide | Decision cards (Review now, Watch, Hold steady, Check) and "Decisions to make now" | 31.2 (with a view) |
| 12 | Sources | The numbered facts the view was written from, as the model saw them | 31.2 (with a view) |

Fold numbers are counted on the page, so without a view the facts' folds start at 1.

### How the facts are made (31.1, no AI)

- **Trailing P/E, point in time:** the close over the sum of the last four quarters' basic EPS known that day (dated by the results filing, else 45 days after the quarter). A bonus issue or split after a quarter's results scales that quarter's EPS by the action's price factor. Left out while trailing EPS is not positive. Its history is the last three years; the band is the 10th to 90th percentile (`agents/valuation.py`).
- **Sector and Nifty P/E:** from NSE's daily index files, already collected.
- **Balance sheet and cash flow:** from the half-yearly (September) and annual (March) results XBRL, read in the xbrl job's pass over each company's files: the balance sheet at the period end (single-date contexts without dimensions) and the cash flow over the half year or year. Tags are matched by name with alternatives (filers use the same Ind AS names under different prefixes); the tag used is stored. A file without a balance sheet is recorded so it isn't downloaded again (`agents/xbrl_results.py`, `balance_sheets`).
- **Peers:** the approved peers, else the largest in the NSE industry; each with its own valuation and latest results growth when its results are stored, else "Not tracked".
- **What's coming:** dates in board-meeting notices of the last 90 days that fall in the next 120 days; the next results due (45 days after a quarter, 60 after the year) when no meeting is announced; NSE corporate actions with a future ex-date; open promises falling due (`agents/research.py`).

### The view (31.2, as built)

- **The facts as numbered lines** (`agents/brief.py`, `fact_lines`): about 40 lines such as "F8 [Filed] Results Q2 FY27 (to 30 Sep 2026, consolidated): revenue ₹25,109 cr, +1% on the year; profit ₹2,898 cr, +52% on the year; margin 11.5%". They cover the valuation, eight quarters, the balance sheet, peers, the order book, promises, management changes, ownership, the lean and its reasons, the most important news of 90 days, what's coming and open red flags.
- **One call to the analysis model** (Sonnet, effort medium) with a fixed answer shape: verdict (one line), summary (two sentences), three stances (Favor, Watch, Avoid, Check), three to six Observed → Read pairs with the fact ids they rest on, Why it matters and Key risk for the stock and each peer, three to five decision cards (Review now, Watch, Hold steady, Check) with fact ids, and up to four "decisions to make now". The instructions: only the facts, no memory; every number one of the facts' numbers, as written or rounded, none calculated; cite the facts; say less about Read by AI and Stale facts; no buy, sell or hold.
- **The number check:** every number in the view is matched against the facts' numbers, as written or rounded (65 for 65.2; 1.2 for 1.17, not 1.3). Labels (Q2, FY27, F12) aren't numbers; whole numbers up to 12 count as counts ("3 of 5 quarters") unless they are a percentage, a multiple or an amount. If any number isn't found, the model is asked once more with the list; parts that still fail are dropped (a stance, an observation, a peer note, a decision), the verdict falls back to the facts' headline, and what was dropped is recorded and shown under Sources. Signs aren't checked: a fact's +9% allows 9%.
- **Saved versions** (`research_briefs`, migration 0029): the facts as given, the view, what was dropped, the model and the cost. The page shows the latest and offers the earlier ones; `sna brief SYMBOL` prints the latest, `--write` writes a new one.
- **Cost:** about 40 fact lines in, a view of about 2,500 tokens out: roughly $0.03–0.10 a view on Sonnet; a retry doubles it.

### Staying current (31.3)

"What changed since the last brief", the "Ask about …" buttons wired to Ask, and a fresh brief for the stocks owned after their results or a large event, flagged in the morning digest.

### Not planned

A consensus checker (street estimates against your view): there is no free source of Indian analysts' estimates.
