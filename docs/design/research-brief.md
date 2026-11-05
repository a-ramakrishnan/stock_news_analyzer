# Research brief

Version 1.0 · Nov 5, 2026 · @Ramki · changes are listed in [README.md](README.md)

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
| – | The view | Observed → Read pairs | 31.2 |
| – | Order book | Book-to-bill, largest wins | 31.2 |
| – | Management | Who's who, changes, promises against delivery | 31.2 |
| – | Ownership | Promoter, FII and DII trend, pledges, deals | 31.2 |
| – | What moves this stock | The event study and Week by week for this stock | 31.2 |
| – | What to watch and decide | Decision cards (Review now, Watch, Hold steady) and "Decisions to make now" | 31.2 |
| – | Sources | Every filing and article used, linked | 31.2 |

### How the facts are made (31.1, no AI)

- **Trailing P/E, point in time:** the close over the sum of the last four quarters' basic EPS known that day (dated by the results filing, else 45 days after the quarter). A bonus issue or split after a quarter's results scales that quarter's EPS by the action's price factor. Left out while trailing EPS is not positive. Its history is the last three years; the band is the 10th to 90th percentile (`agents/valuation.py`).
- **Sector and Nifty P/E:** from NSE's daily index files, already collected.
- **Balance sheet and cash flow:** from the half-yearly (September) and annual (March) results XBRL, read in the xbrl job's pass over each company's files: the balance sheet at the period end (single-date contexts without dimensions) and the cash flow over the half year or year. Tags are matched by name with alternatives (filers use the same Ind AS names under different prefixes); the tag used is stored. A file without a balance sheet is recorded so it isn't downloaded again (`agents/xbrl_results.py`, `balance_sheets`).
- **Peers:** the approved peers, else the largest in the NSE industry; each with its own valuation and latest results growth when its results are stored, else "Not tracked".
- **What's coming:** dates in board-meeting notices of the last 90 days that fall in the next 120 days; the next results due (45 days after a quarter, 60 after the year) when no meeting is announced; NSE corporate actions with a future ex-date; open promises falling due (`agents/research.py`).

### The view (31.2)

One Sonnet call per brief, given only the assembled facts with their badges and sources, writes the verdict title, three stances, the Observed → Read pairs, Why it matters / Key risk for the stock and its peers, and the decision cards. A check rejects any number in its text that is not among the facts, so no figure is made up. The page shows the steps while it works and the cost of the run; each brief is saved, so a re-run shows what changed since the last one. Expected cost: about $0.10–0.30 per brief.

### Staying current (31.3)

"What changed since the last brief", the "Ask about …" buttons wired to Ask, and a fresh brief for the stocks owned after their results or a large event, flagged in the morning digest.

### Not planned

A consensus checker (street estimates against your view): there is no free source of Indian analysts' estimates.
