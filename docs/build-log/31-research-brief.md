# Step 31: The research brief

**Goal:** a complete research output for one stock, on its own page, laid out like Robyn's research results (meetrobyn.com): conclusion first, numbered folds, an evidence badge on every figure. The design is in [research-brief.md](../design/research-brief.md).

Three parts:

| Part | What |
| --- | --- |
| 31.1 | The missing facts (valuation, balance sheet and cash flow, peers, what's coming) and the Research brief page laid out from them, no AI (this part) |
| 31.2 | The view written by Sonnet from the facts only (verdict, stances, Observed → Read, decision cards), with a check that every number it uses is among the facts; the remaining folds |
| 31.3 | What changed since the last brief, Ask about buttons, fresh briefs for the stocks owned after results |

## Looking at Robyn

Robyn's public site is a general agent assistant; its research results aren't public, but the site's code carries example result pages. They all use one layout, the "briefing grammar": an eyebrow line, the verdict as the title, a two-line summary, three stances, a ruled row of key numbers, a scoping callout, then numbered folds with counts, entity cards with "Why it matters" and "Key risk", Observed → Read pairs, decision cards and sources, with an evidence badge (Disclosed, Stale, Low confidence, Not determinable) on every figure. The brief follows it.

## 31.1: the facts and the page

- **Valuation** (`agents/valuation.py`): trailing P/E point in time, the close over the last four quarters' EPS as known that day, adjusted for bonus issues and splits since; its last three years' median and 10th–90th percentile band, where today sits in that history; the sector index's and the Nifty 50's own P/E from NSE's index files; trailing EPS growth.
- **Balance sheet and cash flow** (`balance_sheets`, migration 0028): read in the xbrl job's pass over each company's files, from September and March filings: equity, borrowings (non-current and current added up), cash, total assets at the period end; cash from operations and capex over the half year or year. Tags are matched by name with alternatives and the tag used is kept; a file without a balance sheet is recorded so it isn't fetched again. `sna results balance SYMBOL` lists what was read.
- **The brief's facts** (`agents/research.py`): the eight-quarter trend; balance sheet lines and ratios (net debt, debt to equity, free cash flow, cash from operations against profit); a peer table (approved peers, else the largest in the industry) with each peer's valuation and growth; what's coming (board meetings announced, results due, ex-dates, promises falling due). Every figure carries a badge: Filed, Read by AI, Market, Stale or Not disclosed.
- **The page,** Research brief, first in the Research group: the lede (eyebrow, a headline from the facts, the latest quarter, stances, the ruled numbers, the callout) and six folds (valuation with a P/E chart against its own band, results, balance sheet and cash flow, peers as cards, what's coming as a timeline, red flags).

The balance-sheet tags couldn't be checked against a real filing here (NSE isn't reachable from the build machine), so the first xbrl run on the Mac is the test: `uv run sna results balance LT` shows what was read and from which tag.

### Checked

Tests cover the balance sheet and cash flow from an XBRL file (borrowings added up, a segment's figure and a quarter's cash flow left out, capex as an amount), a quarter end with no balance sheet due, dates in board-meeting notices, the next quarter end, trailing EPS across a split and before four quarters are known, a full valuation, the balance lines and ratios, what's coming, the stock first among its peers, figures turning Stale, the import recording a file without a balance sheet so the second run skips it, and the page rendering. The page was checked in light and dark on generated data. 389 tests pass.

## 31.2: the view

- **More facts** in `agents/research.py`: the order book summary, promises (credibility and the latest ones), management changes of two years, shareholding of five quarters, the lean and its reasons (from Portfolio's `assess`, now usable for any stock), and the most important news of 90 days.
- **`agents/brief.py`**: the facts as numbered lines with their badges; one Sonnet call with a fixed answer shape (verdict, summary, three stances, Observed → Read pairs citing fact ids, Why it matters and Key risk for the stock and its peers, decision cards, decisions to make now); a check that every number in the answer is one of the facts' numbers, as written or rounded; one retry naming the numbers that weren't; what still fails is dropped and recorded. Saved in `research_briefs` (migration 0029).
- **The page:** a "Write the view" button (with an API key) that shows its steps as it works ("Gathering the facts… Asking claude-sonnet-5-5 for the view on 38 facts… Checking every number…") and its cost; a choice of saved views; the verdict as the headline, the summary and the model's stances in the lede, and a note saying who wrote it, when, for how much and how many parts were dropped. New folds: The view (Observed → Read cards with their fact ids; hover one to read the fact), Order book, Management, Ownership, What moves this stock, What to watch and decide (decision cards and a checklist) and Sources (the numbered facts). Peer cards gain Why it matters and Key risk.
- **`sna brief SYMBOL`** prints the latest view; `--write` writes a new one.

The model couldn't be called from the build machine (no key there), so the write path was run with a stand-in that returned a hand-written view with one made-up figure ("improves 25% by March"): the check caught it, asked again, and dropped that decision card; the real figures (52%, ₹34,555 cr, 0.24×, P/E 65 against 70) passed. The first real view on the Mac is the live test.

### Checked

Tests cover numbers that count (rounded, labels, small counts, a fact's year) and ones that don't (a percentage, a P/E or an amount not in the facts, 1.3 for 1.17); dropping parts and falling back to the facts' headline for a verdict; writing a clean view in one call, saving it with its facts and cost, and a view with made-up numbers asked again then trimmed; the versions in order; and the page and `sna brief` showing a saved view. 393 tests pass.

## 31.3: staying current

- **What changed:** fact lines keyed by their label, compared between briefs (changed, new, gone) and between views (verdict, stances, decisions whose tag moved). A new view is given the previous verdict and stances and the facts that changed, and writes a "changed" line, checked like the rest (the previous facts' numbers count too).
- **The page:** the "What changed" callout under the lede, a **What changed** fold against the previous view, and a note when filed facts have moved since the view was written. **Ask about** buttons for the stock and each peer open Ask with the question filled in.
- **The briefs job** at 07:57: a new view for each owned stock with no view yet or with new results, a new balance sheet, a red flag or a major event since its last one, five at most; on the Agent map as "Research briefs" and in the digest under "Research briefs".

Checked on generated data with the stand-in model: LT wasn't due, a promoter pledge flag made it due ("a new red flag"), and the second view's "changed" line passed the check; the page showed the new verdict, the callout, the fold (the old verdict and the new Avoid stance), and Ask about BEL opened Ask with "What should I know about Bharat Electronics Limited (BEL)… and how does it compare with Larsen & Toubro Limited (LT)?". Tests cover the fact keys and both comparisons, filed-only comparison, the refresh (first view, nothing due, a red flag making it due, the previous view in the prompt), the digest section and the job's place before the digest. 395 tests pass.

## On the Mac

```
git checkout main
git pull
make start
uv run sna run xbrl
uv run sna results balance LT
uv run sna brief LT --write
```

The last command writes the first view for LT (one Sonnet call, a few cents) and prints it; the page then shows it. Or press **Write the view** on Research brief.

`make start` rebuilds and applies the database change; the xbrl run reads the balance sheets (a few minutes for the Nifty 50). Send the output of the last command if a line says "not in the file" for a company that does file it.
