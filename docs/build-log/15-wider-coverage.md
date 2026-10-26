# Step 15: Wider coverage

**Goal:** run the earnings-call and order agents for every company on the watchlist. After step 14, most of their output was for DIACABS, KMEW and LT.

## Why the output was narrow

- **Earnings calls were read only for owned stocks.** The Concall Analyst, and so the Promise Ledger, skipped any stock on the watchlist that wasn't marked owned.
- **Single orders were missed.** The filing classifier recognised order wins by the plural wording that L&T and NSE use ("Bagging/Receiving of orders/contracts"). Smaller and SME companies usually file a single order: "Receipt of Work Order", "Letter of Award", "L1 bidder", "bags Rs 300 crore contract". Those filings were classed "other", so the Order Book Tracker never saw them.
- **Some companies have no order book.** Banks, consumer companies and makers of standard products don't win orders the way an EPC or capital-goods company does. They are expected to show none.

## What changed

| Piece | Why |
| --- | --- |
| Filing classifier (`sources/announcements.py`) | `order_win` also matches work order, letter of award or intent, award of contract or work, receipt of order or purchase order, order received, new order, lowest or L1 bidder, and "bags". `sna filings reclassify` applies the new wordings to stored filings. Haiku still drops any that turn out not to be order wins. |
| Concall Analyst scope | Every watchlist stock, owned or not |
| `sna orders coverage` | For each watchlist stock: order-win filings found, read, copies, not order wins, waiting for a PDF, unread; orders; order books; whether its order book is tracked. It shows directly why a company does or doesn't appear. |
| Dashboard | The Earnings calls tab no longer says calls are read only for owned stocks |

## On the Mac

```
uv run sna filings reclassify
uv run sna orders coverage
uv run sna orders run
uv run sna concalls run
uv run sna promises check
uv run sna orders coverage
```

`concalls run` shows its cost estimate before it starts. The watch-only stocks add their transcripts from the last 120 days.

## Next

KMEW and DIACABS still lack enough consecutive quarters of revenue for book-to-bill and execution. Quarterly revenue from results filings would fill them in.
