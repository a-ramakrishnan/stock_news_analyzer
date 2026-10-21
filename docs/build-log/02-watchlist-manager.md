# Step 2: Database tables + Watchlist Manager (agent 1)

**Goal:** turn the names you type into exact listed instruments, and store what you track and own. Every later agent starts from this watchlist.

## What was added

| Piece | Why |
| --- | --- |
| Alembic migrations (`sna db upgrade`) | Tables are created and changed by versioned migrations, never by hand |
| `companies` table | Master list of listed securities keyed by ISIN, with NSE symbol, BSE code and industry |
| `watchlist` table | What you track: stocks (by ISIN) or bullion (gold/silver), owned flag, quantity, notes |
| `company_peers` table | Peers you approve, used later to read news across competitors |
| `sources/securities.py` | Downloads and parses NSE's equity list, the Nifty 500 list (industry) and BSE's scrip list (BSE codes) |
| `agents/watchlist.py` | Resolves names with fuzzy matching, manages the watchlist, suggests peers |
| `config/watchlist.yaml` | Your watchlist as a file you can edit and reload |
| Separate `sna_test` database for tests | `make test` never touches your real data |

## How the Watchlist Manager resolves a name

1. Exact match on NSE symbol, BSE code or ISIN wins outright (`LT`, `590003`, `INE036D01028`).
2. Otherwise, names are normalised (`&` becomes "and", "Limited"/"Ltd" dropped) and fuzzy-matched against every listed company.
3. It picks a company only when the best match scores 90+ and is at least 5 points ahead of the next. Otherwise it lists the candidates and asks for the NSE symbol.

No LLM is used. Simple matching is enough here and costs nothing.

## Decisions

- **ISIN is the key** for every company: names change, symbols change, ISINs don't.
- **BSE codes come from BSE's scrip list.** Step 3 (Filings Collector) needs them to fetch BSE announcements.
- **Peers come from the same NSE industry, largest market cap first.** NSE's Nifty 500 industry is broad ("Financial Services" mixes banks, NBFCs and insurers), so suggestions are only suggestions; you approve them. See the update below.
- **Raw downloads are kept** under `data/reference/<date>/`, in line with "keep raw data forever".
- **Manual fallback:** NSE sometimes blocks scripted downloads. Every list can be loaded from a file you saved in a browser (`--nse-file`, `--nifty500-file`, `--bse-file`).

## How to check it

```bash
make migrate && make securities && make watchlist
uv run sna watchlist peers "Karur Vysya Bank"
make test
```

Expected `make watchlist` output (codes as listed on NSE/BSE):

```
NSE          BSE      ISIN          OWNED       QTY  NAME / INDUSTRY
KARURVYSYA   590003   INE036D01028  True          -  Karur Vysya Bank Limited / ...
LT           500510   INE018A01030  True          -  Larsen & Toubro Limited / ...
MSUMI        543498   INE0FS801015  True          -  Motherson Sumi Wiring India Limited / ...
```

## Update after the first live run

The first `make securities` on a Mac loaded 2,608 NSE, 5,113 BSE and 501 Nifty 500 rows, and all three stocks resolved correctly (LT / 500510, KARURVYSYA / 590003, MSUMI / 543498).

It also showed that BSE's scrip list has an `INDUSTRY` field but leaves it empty, so the planned finer BSE industry isn't available from that list. BSE's per-company header endpoints didn't return usable data either. Follow-up change:

- Store BSE's `Mktcap` (market cap in Rs crore) on each company, and rank peer suggestions by it.
- The test sample now mirrors BSE's real response (`INDUSTRY: null`).
- Finer industry labels ("Private Sector Bank") are deferred to the Theme & Peer agent (Phase 4), which can classify companies from annual reports and concalls.

## Tweet draft

> Agent #1 is live: the Watchlist Manager. I type "Motherson Sumi Wiring", it finds the exact ISIN, NSE symbol and BSE code from the official exchange lists, marks it as owned, and suggests same-industry peers for me to approve. No LLM needed for this one. #BuildInPublic
