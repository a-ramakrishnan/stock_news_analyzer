# Step 11: Bulk/block deals and peer moves

**Goal:** fewer "unexplained" days. In the first ten explanations, six were unexplained, mostly small companies (KMEW +7%, Gaudium -6%, BlackBuck -5%) moving with no news. Two things often explain those days and we did not collect them: large trades by funds and promoters, and whether similar companies moved too.

## What was added

| Piece | Why |
| --- | --- |
| `deals` table (migration 0011) | Every NSE bulk and block deal: day, symbol, client, buy/sell, shares, price; linked to a company by NSE symbol |
| `sources/deals.py` | Reads NSE's historical deals API (JSON) and its CSV downloads; columns are found by the words in their names, as NSE's names differ between the two |
| `agents/deals.py` | Fetches a month per request, stores each deal once, re-reads the last three days as NSE sometimes adds deals late |
| `deals` job, 19:00 and 22:00 on weekdays | NSE publishes the day's deals in the evening |
| `sna deals probe/backfill/fetch/list/load` | Check the format, load history, read, or load a downloaded file |
| Peers | Approved peers first (new Peers column on Manage stocks), otherwise the largest companies in the same NSE industry |
| Move Explainer | Now also sees the stock's deals from two sessions before to the day, with each deal's share of the day's volume, and each peer's return that day with their average |
| `sna explain run --redo-unexplained` | Tries the "unexplained" days again with the new evidence |
| Digest, Stock page | Bulk/block deals listed per stock; a new Bulk/block deals tab |

## Bulk vs block deals

- **Bulk deal:** one client trades more than 0.5% of a company's shares in a day, in the normal market. Reported by the broker after the close.
- **Block deal:** a single trade of at least Rs 10 crore in the separate morning block window.

A promoter selling 3% of a small company through a bulk deal, or a fund buying a stake in a block, is often the whole story of an unusual day. "Share of the day's volume" tells the explainer how much of the trading that deal was.

## How to check it

```bash
git pull
uv sync
make migrate
uv run sna deals probe
uv run sna deals backfill --since 2023-10-01
uv run sna deals list --days 365
uv run sna explain run --since 2023-10-01 --redo-unexplained
make scheduler
```

`deals probe` prints NSE's raw format for the last week: if the backfill reports errors, paste its output. Set peers for small companies on the dashboard's Manage stocks page before the re-run, for example other IVF or hospital chains for Gaudium IVF.

## Tweet draft

> My "why did it move" agent said "unexplained" too often for small caps, so I gave it two more senses: NSE's bulk and block deals (who bought or sold, and what share of the day's volume that was) and how its peers moved that day. Often the answer is just a fund or promoter trade. #BuildInPublic
