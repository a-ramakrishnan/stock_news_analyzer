# Agent design

Version 1.1 · Oct 25, 2026 (first written Oct 21, 2026) · @Ramki · companion to the [system design](design.md); changes are listed in [README.md](README.md)

## Agent team at a glance

A code orchestrator runs 17 single-purpose agents in four layers. Agents never call each other directly: each reads its inputs from the shared database and writes its results back, so any agent can be rebuilt or re-run on its own.

```text
Orchestrator (0)
├─ Collect:     1 Watchlist Manager · 2 Filings Collector · 3 News Collector
│               4 Market Signals Collector · 5 Price & Label
├─ Understand:  6 Triage & Dedup · 7 Event Extractor · 8 QA Checker
├─ Analyse:     9 Move Explainer · 10 Order Book Tracker · 11 Concall Analyst
│               12 Promise Ledger · 13 Bullion Analyst · 14 Theme & Peer Analyst
│               15 Red-flag Monitor
└─ Deliver:     16 Reporter · 17 Analyst Q&A
```

### Build status (Oct 25, 2026)

| # | Agent | Status | Build step |
| --- | --- | --- | --- |
| 0 | Orchestrator | Built: fixed schedule, run log; no LLM | 6 |
| 1 | Watchlist Manager | Built: no LLM needed (fuzzy matching in code); NSE SME list; peers; dashboard page | 2, 7, 11 |
| 2 | Filings Collector | Built: BSE + NSE | 3 |
| 3 | News Collector | Built: RSS + Google News, history since Oct 2023 | 4, 8 |
| 4 | Market Signals Collector | Partly: NSE bulk and block deals only | 11 |
| 5 | Price & Label | Built for stocks; bullion part not started | 5 |
| 6 | Triage & Dedup | Built (Haiku 5.5) | 9 |
| 7 | Event Extractor | Not started | — |
| 8 | QA Checker | Not started | — |
| 9 | Move Explainer | Built (Sonnet 5.5) | 10, 11 |
| 10 | Order Book Tracker | Not started | — |
| 11 | Concall Analyst | Not started; recommended next | — |
| 12 | Promise Ledger | Not started | — |
| 13 | Bullion Analyst | Not started | — |
| 14 | Theme & Peer Analyst | Not started (peers exist for the Move Explainer) | — |
| 15 | Red-flag Monitor | Not started | — |
| 16 | Reporter | Partly: Markdown digest and Streamlit dashboard; no Telegram, email or weekly report; no LLM | 6, 7 |
| 17 | Analyst Q&A | Not started | — |

The build order changed in one place: the Move Explainer came before the Event Extractor and QA Checker, reading filings and triaged news directly. Its explanations were useful without typed events.

A daily run goes top to bottom: collect at 8:00 and every 15 minutes in market hours, understand each new item as it lands, analyse after the 15:30 close, deliver the digest at 8:00 the next morning.

## Which LLMs are needed

You need one capable cloud LLM for judgment work and, optionally, a cheaper one for high-volume sorting. Only about half the agents use an LLM at all; collectors and price labelling are plain code. A setup of 50 watchlist stocks and 10 holdings should cost roughly $30–80 a month in LLM fees (estimate).

| Work type | Agents | What the model must do | Suggested model | Price per 1M tokens (input / output) |
| --- | --- | --- | --- | --- |
| Deep reasoning | Orchestrator, Move Explainer, Concall Analyst, Promise Ledger, Analyst Q&A | Read long documents, compare across quarters, weigh competing causes | Claude Opus 5.5 (`claude-opus-5-5`) | $4 / $20 |
| Structured extraction | Event Extractor, Order Book, Red-flag, Theme & Peer, QA Checker | Fill a fixed JSON schema accurately from a filing or article | Claude Opus 5.5 at low effort, or Claude Sonnet 5.5 (`claude-sonnet-5-5`) to save cost | $4 / $20 or $2 / $10 |
| High-volume sorting | Triage & Dedup | Decide relevance and company match for hundreds of items a day | Claude Haiku 5.5 (`claude-haiku-5-5`) or a local open-weight model | $0.10 / $0.50 |
| No LLM | Collectors, Price & Label, Reporter formatting | Fetch, parse, compute | Plain Python | none |
| Speech to text | Concall Fetcher (audio-only calls) | Transcribe 60–90 minute calls | Whisper (local, faster-whisper) | free if local |
| Embeddings | Search over transcripts and documents | Turn text into vectors for semantic search | Local model such as bge-m3 via sentence-transformers | free if local |

Prices are Anthropic's API list prices as of Oct 2026.

**As built:** Haiku 5.5 (low effort) for triage and Sonnet 5.5 (medium effort) for the Move Explainer. Opus 5.5 isn't used anywhere yet: Sonnet gave good explanations at half the price. Every call is logged to `llm_calls` with tokens and cost. Calls stop when the month's spend reaches `LLM_MONTHLY_BUDGET_USD` ($20). The fixed instructions are prompt-cached.

### Rough monthly cost (estimate)

| Agent | Daily volume | Approx. cost per day |
| --- | --- | --- |
| Triage (Haiku 5.5) | \~300 items × 2K tokens | under $0.10 |
| Event extraction (Sonnet 5.5) | \~60 relevant items × 4K tokens | about $1.00 |
| Move explanations (Opus 5.5) | \~5 flagged moves × 20K tokens | about $0.55 |
| Daily digest (Opus 5.5) | 1 run × 30K tokens | about $0.20 |
| Concalls (Opus 5.5) | \~40 calls a year, about $0.30 each | about $0.03 averaged |

**Actual so far:**

| Agent | Work | Cost |
| --- | --- | --- |
| Triage (Haiku 5.5) | 4,230 articles back to Oct 2023, batches of 15 | $0.28 in total, about $0.00007 an article |
| Move Explainer (Sonnet 5.5) | 562 unusual days back to Oct 2023 | $2.42 in total, about $0.004 a day explained |

The daily run costs a few cents, well under the estimate below, because the watchlist has about 15 stocks rather than 50 and the Opus agents aren't built yet.

Estimate: about $2 a day, or roughly $60 a month. Three levers cut this by half or more: the Batch API (50% off for anything not urgent, such as backfills and overnight extraction), prompt caching of the fixed instructions and schemas, and running triage locally.

### Can it run on a local LLM only?

Partly. Open-weight models of 7–14B parameters (Qwen, Llama, Gemma families, run through Ollama) handle triage and simple extraction on a 16 GB laptop. They are noticeably weaker at concall comparison and move explanation, where mistakes are costly. Recommended: local for triage and embeddings, cloud for reasoning.

## Other tools needed

Run the daily pipeline from a code orchestrator that calls each agent in a fixed order. Use an LLM orchestrator only for open questions ("why is my portfolio down this week?"). A fixed order is cheaper, repeatable and easier to debug; LLM judgment stays inside each agent.

| Need | Recommended | Alternatives |
| --- | --- | --- |
| Agent framework | Anthropic Python SDK: tool runner for agents with tools, structured outputs for extractors | Claude Agent SDK (built-in file/web tools, subagents); LangGraph; Claude Managed Agents (Anthropic hosts the loop and runs it on a schedule) |
| Orchestration and scheduling | Prefect or plain APScheduler; cron on a server | Airflow (heavier), GitHub Actions on a schedule |
| Agent-to-agent hand-off | Database tables as the shared state; each agent reads its input table and writes its output table | A queue (Redis, RabbitMQ) once volume grows |
| Database | PostgreSQL 16 + pgvector | SQLite + sqlite-vec for a first prototype |
| Raw file storage | Local folder or S3-compatible bucket for PDFs and audio | Cloudflare R2, Backblaze B2 |
| Fetching | httpx, feedparser for RSS, Playwright for pages that need a browser | requests, Scrapy |
| Exchange data access | Direct BSE endpoints; [nse-bse-api](https://github.com/bshada/nse-bse-api) or the [NSE-BSE MCP server](https://glama.ai/mcp/servers/dfsjjrmab9) as helpers | Paid vendor API |
| PDF parsing | PyMuPDF or pdfplumber; send hard PDFs (tables, scans) straight to Claude as documents | OCR with Tesseract for scanned filings |
| Speech to text | faster-whisper | Cloud transcription APIs |
| Prices | NSE bhavcopy download; yfinance as fallback | jugaad-data, paid feeds |
| Delivery | Telegram bot (python-telegram-bot) and email (SMTP or Resend) | Slack, WhatsApp Business API |
| Dashboard | Streamlit | Metabase on top of Postgres, a Next.js app later |
| Observability | Log every LLM call (prompt version, tokens, cost, output) to a table; Langfuse for traces | OpenTelemetry |
| Secrets | `.env` file locally; the cloud provider's secret store on a server | Doppler, 1Password CLI |
| Code and deployment | GitHub repo, Docker Compose (app + Postgres) | Kubernetes is unnecessary at this scale |

## Data requirements

The daily data is small; the history you backfill decides how useful the database is. Plan for 5–10 GB a year including PDFs, which fits on any laptop (estimate for 50 stocks).

| Data | Frequency | Backfill | Approx. volume (50 stocks) |
| --- | --- | --- | --- |
| Exchange filings (text + PDF) | Every 15 minutes in market hours | 3 years | \~7,500 filings a year; PDFs are most of the storage (\~4 GB a year) |
| News articles | Hourly | 1 year (RSS rarely goes further back) | \~10,000 articles a year; text only, under 0.5 GB |
| Concall transcripts and audio | Quarterly, per holding | 8–12 quarters | \~40 transcripts a year for 10 holdings; audio \~50 MB per call if kept |
| Investor presentations, annual reports | Quarterly / yearly | 3 years | \~1 GB a year |
| Daily prices (bhavcopy) | After market close | 5 years for all NSE stocks | \~2,000 stocks × 250 days; under 1 GB in total |
| Index levels (Nifty 50, sector indices) | Daily | 5 years | Tiny |
| Bullion (IBJA, MCX, USD/INR) | Daily | 5 years | Tiny |
| Tenders, bulk/block deals, SAST, ratings, MF holdings | Daily to monthly | 2 years | Small; mostly structured rows |
| Reference data: ISIN, symbols, sector, peers | Monthly refresh | Current | Tiny |
| Derived: events, orders, promises, labels | As produced | Re-extracted from raw data | A few hundred MB |

### What a future model needs

- **Breadth, not just your watchlist.** 50 stocks produce too few events of each type to learn from. Run the cheap layers (collection, triage, extraction) on a wider universe, such as the Nifty 500, and keep deep analysis for your own stocks.
- **At least 3 years of history**, so every event type appears in good and bad markets.
- **Labels for every event:** excess returns at 1, 5 and 20 days.
- **Point-in-time timestamps** on every row, and raw documents kept unchanged.
- **Your own corrections** to explanations and extractions, stored as labelled feedback.

## Hosting: local or cloud

**As built:** it runs on a Mac with Docker Compose. Postgres 16 + pgvector is on port 5433, and there is an optional `ui` container for the dashboard. The scheduler runs with `sna orchestrator start`. Keys live in `.env`, which is never committed. No cloud server yet.

It runs locally. Build and test on your laptop, then move to a small cloud server once the daily digest is useful, so it runs even when the laptop is off. The LLM calls go to the cloud API either way.

| Option | Hardware | Approx. cost a month | Good for | Watch out for |
| --- | --- | --- | --- | --- |
| Laptop | 16 GB RAM, 50 GB free disk, Docker | $0 + LLM fees | Building, testing, backfills | Misses runs when asleep or off; set the morning run for when it is usually on |
| Laptop + local LLM | 32 GB RAM, or a GPU with 12–24 GB VRAM | $0 + reduced LLM fees | Free triage and embeddings | Local models are weaker at concall analysis |
| Small cloud server (recommended once stable) | 2 vCPU, 4 GB RAM, 80 GB disk, Mumbai region (AWS Lightsail, DigitalOcean Bangalore, Hetzner, Oracle Cloud free tier) | roughly $10–25 | Always-on scheduled runs, Telegram alerts | NSE blocks many cloud IP ranges; BSE and RSS are usually fine. Test exchange access from the server early |
| Managed agents | No server: Claude Managed Agents runs the agent loop and schedule | API usage only | Least infrastructure to look after | Database still needs a home (managed Postgres such as Supabase or Neon, which have free tiers) |
| Hybrid | Laptop for heavy backfills and Whisper; server for daily runs | roughly $10–25 | Best balance | Keep the database on the server and connect to it from the laptop |

Server prices are approximate and change often; check current pricing before choosing.

### Recommended setup

1. One GitHub repo with a `docker-compose.yml`: the app container plus a Postgres + pgvector container.
2. Develop and backfill on the laptop.
3. Deploy the same compose file to a small Mumbai-region server; run the scheduler there.
4. Back up Postgres nightly to object storage (`pg_dump` to an S3-compatible bucket).
5. Keep API keys in a `.env` file that is never committed.

## Agent-by-agent build guide

An orchestrator plus 17 agents in four layers: Collect, Understand, Analyse, Deliver. Each agent does one job, reads one set of tables and writes another, so each can be built, tested and tweeted about on its own. Build them in the order listed.

### Control layer

#### 0. Orchestrator

- **Job:** run the daily schedule, call each agent in order, retry failures, and decide what needs deep analysis.
- **Trigger:** schedule (8:00 IST pre-market, every 15 minutes 9:15–15:30, 18:30 after close, Saturday 9:00 weekly).
- **As built (step 6):** APScheduler with cron times in `config/schedule.yaml`: filings every 30 minutes 07:00–23:30; news at :15 and triage at :25 every hour from 06:00; prices 19:30 and 21:30 and deals 19:00 and 22:00 on weekdays; explanations 07:45; digest 08:00; company lists Sunday 09:00. Each job is logged to `runs`. Any job runs by hand with `sna run <job>`, and `make backfill` loads history.
- **LLM:** none for the fixed schedule; Opus 5.5 when you ask an open question.
- **Reads / writes:** `runs` table (status, timings, cost per agent).

1. Load the watchlist and the schedule for this time slot.
2. Call the collectors in parallel; wait for all to finish or time out.
3. Call Triage, then Event Extractor, then QA Checker on new items only.
4. After close: call Price & Label, then Move Explainer for flagged stocks.
5. Call the analysis agents whose inputs changed (new orders, a new concall, a new rating).
6. Call Reporter; log run time, token use and cost; alert you on failure.

> Tweet: Day 1 of building an AI research desk for Indian stocks. Not charts, just news, filings and concalls. 17 small agents, one orchestrator. First up: the conductor that wakes everyone at 8am and keeps the bill in check. #BuildInPublic #IndianStockMarket

### Collect layer

#### 1. Watchlist Manager

- **Job:** turn the names you type into exact instruments, and keep reference data current.
- **Trigger:** when you add or remove a stock; monthly refresh.
- **LLM:** Haiku 5.5, only for fuzzy name matching ("L&T", "Larsen").
- **As built (steps 2, 7, 11):** no LLM. rapidfuzz matching against the NSE main board, NSE SME and BSE lists; an exact full-name match wins; a symbol pins ambiguous names. Peers are suggested from the same industry, largest first, and approved on the dashboard's Manage stocks page. That page also adds stocks, marks them owned and loads their history.
- **Reads / writes:** `companies`, `watchlist`, `relationships` (first-pass peers).

1. Accept a name, symbol or ISIN; for bullion accept "gold" or "silver".
2. Match against the NSE/BSE master list; ask you to confirm if more than one match.
3. Store ISIN, NSE symbol, BSE code, sector, industry, aliases (old names, brand names).
4. Suggest 3–5 listed peers from the same industry for you to approve.
5. Mark whether you own it and the quantity.

> Tweet: Agent #1: Watchlist Manager. Type "L&T" and it resolves to the right ISIN, NSE and BSE codes, sector, and suggests peers. Sounds boring; it's the reason every later agent links news to the right company. #BuildInPublic

#### 2. Filings Collector

- **Job:** pull every new corporate announcement for watchlist companies.
- **Trigger:** every 15 minutes in market hours; hourly otherwise.
- **As built (step 3):** BSE and NSE announcements every 30 minutes. PDFs are downloaded for important filing types; text extracted with pypdf (NUL characters stripped). History since Oct 2023.
- **LLM:** none.
- **Reads / writes:** `documents`, raw PDF storage.

1. Query BSE announcements for each company since the last fetch.
2. Download the attached PDF; compute a content hash to skip duplicates.
3. Extract text (PyMuPDF); keep the PDF.
4. Store with filing category, `published_at` and `first_seen_at` in IST.
5. Flag concall transcripts, audio links, results and presentations for the Concall Analyst.

> Tweet: Agent #2: Filings Collector. In India, order wins, results and concall transcripts have to be filed with the exchanges. This agent checks BSE every 15 min and stores every filing with the exact minute it appeared. Primary source beats headlines. #BuildInPublic

#### 3. News Collector

- **Job:** gather news articles that mention watchlist companies, sectors or bullion.
- **Trigger:** hourly.
- **LLM:** none.
- **Reads / writes:** `documents`.
- **As built (steps 4, 8):** RSS feeds listed in a config file plus a Google News search per company. History since Oct 2023 comes from Google News searches one month at a time.

1. Read RSS feeds (ET Markets, Moneycontrol, Business Standard, Mint, BusinessLine, Financial Express, CNBC-TV18, NDTV Profit).
2. Run a Google News RSS query per company name and alias.
3. Fetch the full article text where the site allows it; otherwise keep the summary.
4. Hash and store with source, `published_at` and `first_seen_at`.

> Tweet: Agent #3: News Collector. 8 Indian business news feeds + Google News for every stock on my list, hourly. Everything stored with timestamps so a future model can't cheat by seeing tomorrow's news. #BuildInPublic

#### 4. Market Signals Collector (Phase 4)

- **Job:** collect structured market data that shows who is buying, selling or winning tenders.
- **Trigger:** daily after close; monthly for MF portfolios.
- **LLM:** Haiku 5.5 only to read messy tender PDFs.
- **As built (step 11), deals only:** NSE bulk and block deals from the CSV download (the JSON API stops at 70 rows), twice each weekday evening, stored in `deals`. About 83,000 deals since Oct 2023, about 220 of them in watchlist stocks. SAST, pledges, ratings, tenders and MF holdings are not started.
- **Reads / writes:** `signals` (bulk/block deals, SAST, pledges, ratings, tenders, MF holdings).

1. Download NSE/BSE bulk and block deal files and SAST disclosures.
2. Pull rating actions from CRISIL, ICRA, CARE and India Ratings.
3. Scrape tender awards from CPPP, GeM, IREPS and NHAI for watchlist companies.
4. Load monthly mutual fund portfolio files for holding changes.
5. Store each as a structured row linked to the ISIN.

> Tweet: Agent #4: Market Signals. Promoter buys, pledges, bulk deals, rating changes, government tender awards. Often these show up before the press release. #BuildInPublic

#### 5. Price & Label

- **Job:** store daily prices and measure what each event did to the stock.
- **Trigger:** 18:30 IST daily.
- **As built (step 5):** NSE bhavcopy for every stock (main board and SME), Nifty and sector index closes, and corporate actions for adjustment. Unusual means more than 2σ of the last 60 days (`UNUSUAL_THRESHOLD`). Labels are 0/1/5/20-day excess returns after each filing, in `event_labels`. Bullion is not started.
- **LLM:** none.
- **Reads / writes:** `prices_daily`, `event_returns`, `moves` (flags only).

1. Download the NSE bhavcopy; load closes, volumes and delivery %.
2. Compute each stock's return minus its benchmark (Nifty 50 or sector index).
3. Flag moves larger than 2× the stock's 60-day typical move.
4. For events 1, 5 and 20 trading days old, write the excess return labels.
5. For bullion, compute the Rs move and split it into global price and USD/INR parts.

> Tweet: Agent #5: Price & Label. No charts, no indicators. Prices are used for one thing: measuring how much each piece of news actually moved the stock vs the Nifty. That's the training label for the model later. #BuildInPublic

### Understand layer

#### 6. Triage & Dedup

- **Job:** throw away noise, merge duplicate stories, and confirm which company each item is about.
- **Trigger:** after each collection run.
- **LLM:** Haiku 5.5 or a local model.
- **As built (step 9):** headline duplicates are dropped in code (fuzzy match within 3 days). Haiku 5.5 then reads new articles in batches of 15 per company and records relevance, one of 12 topics, sentiment, importance (1–5), a one-line summary, and which earlier report tells the same story. Results go to `news_triage`. Off-topic articles are hidden in the digest and dashboard, not deleted.
- **Reads / writes:** `documents` → `document_companies`, `story_clusters`.

1. Group near-identical items (same story from many outlets) by text similarity.
2. Ask the model: which listed companies is this about, and is it material (yes / no / maybe)?
3. Drop market-wrap and listicle items with no company-specific content.
4. Pass material items to the Event Extractor.

> Tweet: Agent #6: Triage. \~300 items a day come in; one order win shows up in 15 outlets. This agent clusters duplicates, checks which company it's really about, and drops noise. Runs on the cheapest model, costs under 10 cents a day. #BuildInPublic

#### 7. Event Extractor

- **Job:** turn each material item into typed events with numbers.
- **Trigger:** after Triage.
- **LLM:** Sonnet 5.5 (or Opus 5.5 at low effort) with structured JSON output.
- **Reads / writes:** material documents → `events`, `orders`.

1. Pick the schema for the filing type (order win, capex, rating, management change, results, and so on).
2. Extract fields: client, value in Rs crore, segment, execution period, dates.
3. Score sentiment and materiality (value ÷ annual revenue).
4. Keep a quote from the source for every number.
5. Store with prompt version and model name.

> Tweet: Agent #7: Event Extractor. A 3-page BSE filing becomes: ORDER\_WIN, client NHAI, Rs 1,240 cr, roads, 30 months. Every number carries a quote from the source so I can check it. This is where text becomes data. #BuildInPublic

#### 8. QA Checker

- **Job:** catch extraction mistakes before they reach the database.
- **Trigger:** after each extraction batch.
- **LLM:** Sonnet 5.5, plus plain code checks.
- **Reads / writes:** `events` → `events.qa_status`, `review_queue`.

1. Check each number appears in its quoted source text.
2. Check units (crore vs lakh vs million) and that values are plausible against company revenue.
3. Ask a second model pass to confirm the event type and company.
4. Send failures to a review queue for you; pass the rest.

> Tweet: Agent #8: QA Checker. LLMs make confident mistakes, like crore vs lakh. A second agent checks every number against the source and sends anything odd to me for review. My corrections become training data too. #BuildInPublic

### Analyse layer

#### 9. Move Explainer

- **Job:** explain why a stock made an unusual move.
- **Trigger:** after Price & Label flags a move; also on demand.
- **LLM:** Opus 5.5.
- **Reads / writes:** `moves`, `events`, `documents`, `relationships` → `moves.explanation`.
- **As built (steps 10, 11):**
  - **Model:** Sonnet 5.5 at medium effort instead of Opus.
  - **Evidence:** read directly from filings, triaged news, corporate actions, bulk and block deals with their share of volume, and peer moves. The window runs from 2 sessions before the day to 09:15 the next morning.
  - **Output:** one cause (results, order, company_news, sector, market, corporate_action, flows, unexplained), a confidence, an explanation and cited evidence ids, in `move_explanations`.
  - **Schedule:** runs at 07:45 for the last 14 days; `sna explain run --redo-unexplained` retries old ones.
  - **Not yet:** the 5-day re-check and right/wrong marking.

1. Gather events and news for the stock, its peers and its sector from the previous 1–3 trading days.
2. Add context: the market and sector move that day, any bulk deals or rating changes.
3. Ask the model to rank likely causes with confidence and cite the documents.
4. If nothing fits, write "no news found" and schedule a re-check in 5 trading days.
5. Let you mark the explanation right or wrong.

> Tweet: Agent #9: Move Explainer. Stock up 7% vs Nifty? It pulls every filing, article and peer event from the last 3 days, ranks the likely causes, and cites sources. When there's no news, it says so and checks again in a week. #BuildInPublic

#### 10. Order Book Tracker

- **Job:** show who is winning orders and who is executing them.
- **Trigger:** on each new order event; quarterly after results.
- **LLM:** Sonnet 5.5 to read order book figures from results and presentations.
- **Reads / writes:** `orders`, `order_book_snapshots`, results data → `order_metrics`.

1. Add up announced orders per company per quarter, by client type.
2. Read the reported order book from results, presentations and concalls.
3. Compute book-to-bill (new orders ÷ revenue) and execution rate (revenue ÷ opening order book).
4. Flag gaps between announced orders and the reported book.
5. Rank peers within each sector.

> Tweet: Agent #10: Order Book Tracker. Every order win from exchange filings, added up per quarter and matched against the order book companies report. Who's winning, who's actually executing, ranked within the sector. #BuildInPublic

#### 11. Concall Analyst

- **Job:** read each earnings call of stocks you own and pull out what matters.
- **Trigger:** when the Filings Collector flags a new transcript or audio file.
- **LLM:** Opus 5.5; faster-whisper for audio-only calls.
- **Reads / writes:** transcript documents → `concalls`, `concall_points`.

1. Download the transcript PDF (or transcribe the audio).
2. Split opening remarks from Q\&A; tag each speaker as management or analyst.
3. Extract guidance, demand commentary by segment, capex, margins, order book, risks, new initiatives.
4. List the questions analysts pressed on and whether management answered directly.
5. Write 3–5 action points for you.

> Tweet: Agent #11: Concall Analyst. 60-page transcript in, 1 page out: guidance, demand by segment, capex, risks, which analyst questions management dodged, and 3 things for me to watch. #BuildInPublic

#### 12. Promise Ledger

- **Job:** track every forward-looking statement and check whether management delivered.
- **Trigger:** after each Concall Analyst run and each results filing.
- **LLM:** Opus 5.5.
- **Reads / writes:** `concall_points`, results, earlier calls → `promises`, `credibility_scores`.

1. Record each new promise with metric, target value and target date.
2. Compare with earlier calls: new topics, topics dropped, tone changes, revised targets.
3. Mark earlier promises kept, delayed, dropped or quietly revised.
4. Update the management credibility score (share of promises met on time).
5. Highlight promises due this quarter.

> Tweet: Agent #12: Promise Ledger. "Plant 2 by Q3, margins 18–20%": every promise from every concall gets a due date. Next quarter the agent checks: kept, delayed, or quietly dropped? After 8 quarters you get a management credibility score. #BuildInPublic

#### 13. Bullion Analyst

- **Job:** explain daily moves in Indian gold and silver prices.
- **Trigger:** daily after IBJA and MCX close.
- **LLM:** Sonnet 5.5.
- **Reads / writes:** bullion prices, USD/INR, news → `bullion_notes`.

1. Split the Rs price move into global price and USD/INR parts.
2. Collect drivers: Fed and US yield news, central bank buying, ETF flows, import duty, festival demand.
3. Write a short daily note with the main driver.

> Tweet: Agent #13: Bullion. Gold up 1.2% in rupees today: how much was the global price and how much was a weaker rupee? Plus the Fed, ETF flows and duty news behind it. #BuildInPublic

#### 14. Theme & Peer Analyst

- **Job:** connect events across companies: themes, peers, customers and suppliers.
- **Trigger:** daily after extraction; weekly summary.
- **LLM:** Sonnet 5.5.
- **Reads / writes:** `events`, `relationships` → `themes`, `peer_signals`.

1. Tag each event with themes (data centres, defence, railways, transmission, and so on).
2. Track event count, order value and sentiment per theme per month.
3. When a company has news, write read-across signals for its peers, suppliers and customers.
4. Grow the relationship map from annual reports and concalls.

> Tweet: Agent #14: Theme & Peer. A big wagon order for one company is also news for its suppliers. This agent maps customers, suppliers and peers, and tracks themes like defence or data centres over time. #BuildInPublic

#### 15. Red-flag Monitor

- **Job:** warn early on governance and balance-sheet risks.
- **Trigger:** on each relevant filing or signal.
- **LLM:** Sonnet 5.5.
- **Reads / writes:** `events`, `signals` → `alerts`.

1. Watch for auditor or CFO resignation, rising promoter pledges, rating downgrades, delayed results, large related-party deals, SEBI orders.
2. Score severity and send high-severity alerts immediately.

> Tweet: Agent #15: Red-flag Monitor. Auditor quits, promoter pledge jumps, rating cut, results delayed: I get a ping the same hour, not a week later in the news. #BuildInPublic

### Deliver layer

#### 16. Reporter

- **Job:** turn everything into short reports you read.
- **Trigger:** 8:00 IST daily digest; Saturday 9:00 weekly report; immediate alerts.
- **LLM:** Opus 5.5 to write; code to format.
- **As built (steps 6, 7):** the daily digest is put together in code (no LLM yet) and saved as Markdown under `data/digests/`. It has filings, triaged news with stars and topics, unusual moves with their likely cause, and bulk/block deals.
  
  The Streamlit dashboard (`make ui`) has seven pages: Today, Stock, Filings, News, What moves the stock, Manage stocks, System. System shows AI usage.
  
  Telegram, email and the weekly report are not built yet.
- **Reads / writes:** all output tables → Telegram, email, dashboard.

1. Daily: overnight filings, explained moves, new orders, red flags, bullion note.
2. Weekly per holding: promises due, order book changes, rating changes, unexplained moves, upcoming concalls.
3. Send by Telegram and email; publish to the Streamlit dashboard.

> Tweet: Agent #16: Reporter. Every morning at 8, one Telegram message: what was filed overnight, why my stocks moved, new orders, red flags, gold. Saturday: a one-page "what changed" for each stock I own. #BuildInPublic

#### 17. Analyst Q&A

- **Job:** answer your questions over the whole database.
- **Trigger:** when you ask (Telegram or dashboard).
- **LLM:** Opus 5.5 with tools: SQL queries and vector search.
- **Reads / writes:** all tables (read-only).

1. Turn your question into SQL and document searches.
2. Run them, read the results and answer with citations.
3. Save useful questions as recurring reports.

> Tweet: Agent #17: Ask the database. "Which capital goods companies raised margin guidance two quarters in a row?" Plain English in, cited answer out, from my own data. #BuildInPublic

## Build-in-public plan

Each build step has a log with a draft post in [`docs/build-log/`](../build-log/) (steps 1–11 so far).

Post one agent per post, in build order, with something visual each time: a screenshot of real output does better than a description. The tweet drafts above are starting points; rewrite them with real numbers once each agent runs.

| Post | Topic | What to show |
| --- | --- | --- |
| 1 | Why: news and filings, not charts; the orchestrator + 17-agent plan | The agent team diagram from this doc |
| 2–6 | Collect layer, agents 1–5 | Count of filings and articles collected in week 1; a sample filing with its timestamp |
| 7–9 | Understand layer, agents 6–8 | Before/after: raw filing text next to the extracted JSON event; a QA catch (crore vs lakh) |
| 10 | First "why did it move?" explanation | A real flagged move with ranked causes and sources |
| 11 | Order book league table | A peer ranking chart for one sector |
| 12–13 | Concall Analyst and Promise Ledger | A one-page concall summary; a promise marked "delayed" |
| 14–16 | Bullion, themes, red flags | A daily gold note; a theme trend chart; a red-flag alert |
| 17–18 | Reporter and Q&A | The 8am Telegram digest; a question answered with citations |
| 19 | Costs and lessons | Monthly LLM bill by agent; what broke and how it was fixed |

- Pin a thread that links every post, and add to it as each agent ships.
- Share the open parts (schemas, prompts, collectors) on GitHub; it brings feedback and contributors.
- Blur or generalise company names in examples if you prefer, and add "not investment advice" to posts. Publishing buy/sell calls can require SEBI research analyst registration.
