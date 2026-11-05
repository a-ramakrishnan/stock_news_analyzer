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

## On the Mac

```
git checkout main
git pull
make start
uv run sna run xbrl
uv run sna results balance LT
```

`make start` rebuilds and applies the database change; the xbrl run reads the balance sheets (a few minutes for the Nifty 50). Send the output of the last command if a line says "not in the file" for a company that does file it.
