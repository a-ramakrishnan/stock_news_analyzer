# Step 4: News Collector (agent 3)

**Goal:** news articles about watchlist companies, from Indian business news feeds and a Google News search per company, stored with their publication time and linked to every watchlist company they mention.

## What was added

| Piece | Why |
| --- | --- |
| `config/news_feeds.yaml` | The feeds to read (Economic Times, Moneycontrol, Business Standard, Mint, Hindu BusinessLine, Financial Express), editable without code changes |
| `sna news check-feeds` | Fetches every feed once and reports which work, so dead or moved feeds are easy to spot |
| `sources/news.py` | Fetches feeds with the same browser-like client as the filings, parses RSS/Atom with `feedparser`, builds Google News search URLs |
| `agents/news.py` | Matches each article to watchlist companies, stores it once, links it to every company it mentions |
| Migration 0004 | `documents.url` and `documents.publisher` for articles; `watchlist.aliases` for other names the press uses |
| `aliases` in `config/watchlist.yaml` | "L&T", "KVB", "MSWIL" |
| `sna news fetch / list`, `make news` | Daily use and checking what came in |

## How articles are matched to companies

1. Every company is matched by its name without "Limited" ("Larsen & Toubro"), and without a trailing "India" ("Motherson Sumi Wiring").
2. Plus the `aliases` you list. Short or all-capital aliases ("L&T", "KVB") must match exactly, so "l&t" or "kvbx" don't count; longer names ignore case.
3. "&" also matches "and", so "Larsen and Toubro" matches "Larsen & Toubro".
4. Only articles that mention at least one watchlist company are stored. One article can be linked to several companies ("L&T, Karur Vysya Bank among top gainers").

Known limitation: "L&T" also matches "L&T Finance" and "L&T Technology Services", which are different companies. The Triage agent (step 6) will sort these out; until then a few extra L&T articles may appear.

## Decisions

- **Headline and summary only.** Feeds carry a headline and a short summary; full articles are often paywalled. That is enough to explain most moves and to match companies. Full text can be fetched later for articles that matter.
- **Google News** adds outlets that have no usable feed (CNBC-TV18, NDTV Profit, regional papers): one search per company, quoted name, last 7 days.
- **Point in time:** `published_at` comes from the feed; if a feed gives no date, the time we saw it is used and `raw.date_missing` is set.
- **Duplicates:** the same article is stored once per source (by its feed id). The same story from different outlets is kept separately for now; the Triage agent (step 6) clusters them.
- **A web page instead of a feed** (an "Access Denied" page served with HTTP 200) is reported as an error rather than read as an empty feed.

## Also in this PR

- **Broken files at the source:** NSE served the same 2,523,136-byte truncated PDF for the 21 Oct L&T order win every time (its server's Content-Length says so too). When two downloads come back identical and incomplete, the file is now kept as is, its readable text is recovered, and it is marked `partial` instead of being retried forever. Run `uv run sna filings attachments --retry-failed` to apply this to the stored filing.
- **README commands** no longer have `# comments` on the same line: macOS's zsh passes them to the command as extra words.

## How to check it

```bash
git pull
make migrate
make watchlist
uv run sna news check-feeds
make news
uv run sna news list
```

`make watchlist` reloads the file so the new aliases are stored. Paste the `check-feeds` output: any feed marked FAIL gets fixed or removed in this PR.

## Tweet draft

> Agent #3: News Collector. 11 Indian business feeds + a Google News search per stock, every article matched to my watchlist by name and nickname ("L&T", "KVB"), stored with its publish time. Headlines and summaries only for now: enough to answer "why did it move?". #BuildInPublic
