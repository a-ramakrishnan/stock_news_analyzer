# Indian Market News Intelligence System — Design

Version 1.0 · Oct 21, 2026 · @Ramki · changes are listed in [README.md](README.md)

## Goal and principles

Build a personal system that tracks news and filings for a watchlist of Indian stocks and bullion, explains why each one moves, and gradually builds a structured database that can train a model later. The system avoids chart-based technical analysis. Prices are used only to label what each news item did to the stock.

The system is built as independent agents under an orchestrator; models, tools, data, hosting and a step-by-step guide per agent are in [Agent design](agent-design.md).

- **Filings first, news second.** Under SEBI LODR Regulation 30, listed companies must report material events (order wins, capacity additions, fundraises, rating changes, management exits) to NSE/BSE, generally within 24 hours. These filings are the factual record. News adds context, sentiment and rumour.
- **Concalls are mandatory disclosures.** Companies must upload earnings call audio within about 24 hours and the transcript within about 5 working days. So the concall archive can be built from exchange filings.
- **Structured events, not just sentiment.** Each document becomes typed events with fields (client, order value in Rs crore, execution timeline), so questions like "who is winning orders" become database queries.
- **Point-in-time correctness.** Every item records when it was published and when the system first saw it. A model trained later must not learn from information it would not have had at the time.
- **Keep raw documents forever.** Extraction improves over time. Raw text plus versioned extractions means the whole archive can be re-processed cheaply.

## Data sources

Start with BSE announcements, RSS news feeds and NSE bhavcopy prices: all are free and cover about 80% of what is needed. Add the other sources one module at a time.

| Category | Sources | What it gives | Access | Priority |
| --- | --- | --- | --- | --- |
| Primary filings | [BSE corporate announcements](https://www.bseindia.com/corporates/ann.html), [NSE corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-announcements), company IR pages | Order wins, results, concall transcripts and audio, investor presentations, credit ratings | BSE has a JSON endpoint behind its site; NSE needs session cookies and blocks heavy scraping | Phase 1 |
| Concall aggregators | [Screener.in](https://www.screener.in), [Trendlyne](https://trendlyne.com), [Tijori Finance](https://www.tijorifinance.com) | Transcript, presentation and annual report links per company, going back several years | Web pages; check terms before scraping | Phase 3 |
| News (RSS) | Economic Times Markets, Moneycontrol, Business Standard, Mint, Hindu BusinessLine, Financial Express, CNBC-TV18, NDTV Profit; Google News RSS per stock name | Explanations, rumours, sector stories, management interviews | RSS feeds, free | Phase 1 |
| Early order signals | [CPPP eProcurement](https://eprocure.gov.in), [GeM](https://gem.gov.in), [IREPS](https://www.ireps.gov.in) (railways), NHAI, defence ministry, [PIB](https://pib.gov.in) releases | Tender awards, sometimes before the company announces them | Public portals; often messy HTML or PDF | Phase 4 |
| Market structure | NSE bulk and block deals, SAST insider-trading disclosures, promoter pledges, quarterly shareholding patterns, mutual fund monthly portfolios (AMFI and AMC sites) | Who is buying or selling: promoters, institutions, funds | Exchange downloads, monthly AMC files | Phase 4 |
| Credit ratings | CRISIL, ICRA, CARE, India Ratings press releases | Upgrades and downgrades; early warning of stress | Public press releases | Phase 4 |
| Bullion | [IBJA](https://ibjarates.com) daily rates, MCX, RBI USD/INR reference rate, [World Gold Council](https://www.gold.org) (ETF flows, central bank buying), US Fed and yield news, Indian import duty changes | Indian gold and silver prices are mostly the global price × USD/INR, plus duty and seasonal demand | Free sites and RSS | Phase 2 |
| Prices (labels only) | [NSE daily bhavcopy](https://www.nseindia.com/all-reports), BSE bhavcopy; yfinance (`.NS` tickers) as a fallback | Daily closing prices, used only to measure each event's effect | Free daily files | Phase 1 |
| Macro and policy | RBI policy statements, SEBI orders and circulars, Union Budget, PLI scheme notifications, GST council | Sector-wide tailwinds and headwinds | Public | Phase 2 |

Paid vendors (CMOTS, Accord Fintech, Capitaline, Tijori API) are worth considering later if reliability matters more than cost.

## Architecture

Every source flows into one raw document store; an LLM turns de-duplicated documents into typed events, and four modules read those events from a single database.

```text
Sources: exchange filings, news RSS, tender portals, market signals, bullion, macro
   │
   ▼
Collectors ──► raw document store (text, PDFs, published_at, first_seen_at)
   │
   ▼
Triage & de-duplication ──► LLM event extraction ──► typed events
   │
   ▼
PostgreSQL + pgvector ◄── daily prices (bhavcopy, labels only)
   │
   ├─► Move explainer
   ├─► Order and execution tracker
   ├─► Earnings call analysis and promise ledger
   └─► Digest, dashboard, Q&A
```

Prices skip the extraction pipeline: they go straight to the database and are used only to label events with their price effect.

## Core modules

Four modules do the core work: event extraction feeds the other three.

### 1. Event extraction

An LLM reads each document and returns typed events as JSON. Example: `ORDER_WIN {client: "NHAI", value_cr: 1240, segment: "roads", execution_months: 30, source: "BSE filing"}`.

| Event type | Key fields |
| --- | --- |
| Order win / LoI | Client, value (Rs crore), segment, domestic/export, execution period |
| Capex / capacity | Plant, capacity added, cost, commissioning date |
| Guidance change | Metric, old value, new value, period |
| Results surprise | Revenue, EBITDA, PAT vs last year and vs consensus where available |
| Management change | Role, person, reason given |
| Credit rating action | Agency, old rating, new rating, outlook |
| Regulatory / legal | Regulator, order type, penalty, litigation amount |
| M&A / fundraise | Counterparty, value, structure (QIP, rights, preferential, OFS) |
| Promoter action | Buy, sell, pledge, release; quantity and % of holding |
| Disruption | Plant shutdown, fire, strike, export ban, raw-material shock |

Each event stores a sentiment score, a materiality score (event value ÷ annual revenue or market cap), the source document id and the model/prompt version.

### 2. Move explainer ("why did it move?")

1. Each evening, compute every watchlist stock's return minus its benchmark (Nifty 50 or its sector index).
2. Flag a stock whose excess move is more than about 2× its usual daily move over the last 60 days.
3. Pull all events and news for that stock, its sector and its peers from the previous 1–3 trading days.
4. The LLM ranks likely causes with a confidence level, and cites the documents.
5. If nothing explains the move, record "no news found". This is useful too: it often means informed buying or selling ahead of an announcement, and it can be checked again a week later.

The same price data labels every event with the stock's excess return over 1, 5 and 20 days. These labels are what a future model learns from.

### 3. Order and execution tracker

- **Order inflow:** total announced orders per company per quarter, by client type (government, private, export).
- **Order book check:** compare announced orders with the order book reported in results or concalls. A gap means unannounced small orders, or cancellations.
- **Book-to-bill:** new orders ÷ revenue. Above 1 means the order book is growing.
- **Execution rate:** revenue ÷ opening order book, compared with the execution period management stated.
- **Concentration:** share of orders from the top client and from government.
- **Peer ranking:** within a sector (EPC, defence, railways, power T&D), rank companies on inflow growth, execution rate and margins.

### 4. Earnings call analysis (stocks you own)

1. **Find and download:** check BSE filings daily for transcript PDFs and audio links; fall back to the company IR page or Screener.
2. **Parse:** extract the text, split the opening remarks from Q&A, tag each speaker as management or analyst.
3. **Extract:** guidance (revenue, margin, capex, order inflow), demand commentary by segment, risks named, new initiatives, and what analysts pressed on.
4. **Promise ledger:** store every forward-looking statement with a target date, e.g. "Plant 2 commissioning by Q3 FY27, EBITDA margin 18–20%". Each new call and result marks it kept, delayed, dropped or quietly revised.
5. **Compare with earlier calls:** what's new this quarter, what management stopped mentioning, tone changes on the same topic, dodged questions, concerns analysts keep raising.
6. **Action points:** a short list for you, e.g. "Margin guidance cut for the second quarter in a row; watch Q3 gross margin" or "Order book now 4.2× revenue; execution is the key risk".

Audio is a fallback: when only audio exists, transcribe it with a speech-to-text model (Whisper or similar) before parsing.

## Extended ideas

These build on the core modules. Each adds a new kind of signal to the database.

| Idea | What it does | Example | Data needed |
| --- | --- | --- | --- |
| Peer and supply-chain effects | Maps each company's customers, suppliers and peers, so one company's news reaches the others | A big Railways wagon order to one maker is read as a signal for wheel and coupler suppliers | Annual reports, concalls, a hand-built relationship table refined by the LLM |
| Theme tracker | Groups events across companies into themes and tracks their strength over time | "Data centres", "defence indigenisation", "transmission capex": event count, order value and sentiment per month | Event table plus a theme tag per event |
| Management credibility score | Turns the promise ledger into a score: share of guidance met on time, in full | A company that met 9 of 12 commitments over 3 years scores higher than one that missed 6 | Promise ledger plus quarterly results |
| Smart-money overlay | Combines events with institutional and promoter behaviour | An order win followed by promoter buying and rising MF holding is a stronger signal than either alone | Bulk/block deals, SAST, shareholding patterns, MF portfolios |
| Tender pipeline | Tracks government tenders bid, won (L1) and awarded before the company files | NHAI or IREPS award lists show the L1 bidder weeks before a formal order filing | CPPP, GeM, IREPS, NHAI portals |
| Surprise measurement | Compares results and guidance with what was expected, not with last year | Profit up 20% when the market expected 30% is negative news | Consensus estimates (paid) or management's own previous guidance as a free proxy |
| Unexplained-move watch | Re-checks moves with no news a week later to see what came out | A 6% jump with no news, followed by an order filing 4 days later | Move explainer log |
| Red-flag monitor | Alerts on governance and balance-sheet warnings | Auditor resignation, promoter pledge rising, related-party deals, rating downgrade, delayed results, CFO exit | Filings, ratings, shareholding |
| Weekly "what changed" report | One page per holding: promises due this quarter, new orders, rating changes, unexplained moves, upcoming concall dates | Sent Saturday morning by email or Telegram | All modules |
| Ask-the-database chat | Ask questions in plain English over the stored events and transcripts | "Which capital goods companies raised margin guidance in the last two quarters?" | Event tables plus vector search over documents |
| Bullion module | Tracks the drivers of Indian gold and silver prices and explains daily moves | Gold up 1.2% in Rs: 0.8% from the global price, 0.4% from a weaker rupee | IBJA, MCX, USD/INR, WGC, Fed news, import duty |
| Annual report reader | Extracts segment data, capacity, related-party transactions and contingent liabilities each year | Tracks capacity utilisation claims against later results | Annual report PDFs from exchange filings |

## Database design

Use PostgreSQL with the pgvector extension: structured tables for events and ledgers, plus vector search over document text.

| Table | Holds | Key columns |
| --- | --- | --- |
| `companies` | One row per listed company or commodity | ISIN, NSE symbol, BSE code, name, sector, industry, aliases |
| `watchlist` | What you track and why | company, owned (yes/no), quantity, added date, notes |
| `sources` | Each feed or site | name, type (filing, news, tender), URL, reliability rank |
| `documents` | Every raw item ever fetched, never edited | URL, source, title, full text, content hash, published\_at, first\_seen\_at (IST) |
| `document_companies` | Which companies a document mentions | document, company, relevance score |
| `story_clusters` | Groups of documents reporting the same story | cluster id, first document, first\_seen\_at |
| `events` | Structured events extracted from documents | type, company, fields (JSON), sentiment, materiality, document, extractor version |
| `orders` | Order wins as their own ledger | company, client, value (Rs crore), segment, award date, execution months |
| `order_book_snapshots` | Order book as reported each quarter | company, quarter, order book (Rs crore), source |
| `concalls` | One row per earnings call | company, quarter, date, transcript URL, audio URL, text |
| `concall_points` | Extracted points from each call | concall, category (guidance, demand, risk, capex), text, sentiment |
| `promises` | The promise ledger | company, statement, metric, target value, target date, status, checked\_on |
| `relationships` | Customer, supplier and peer links | company A, company B, type, evidence document |
| `prices_daily` | Daily close from bhavcopy | company, date, close, volume, delivery % |
| `event_returns` | The labels | event, excess return day 0, 1, 5, 20, benchmark used |
| `moves` | Flagged unusual moves and their explanation | company, date, excess return, ranked causes, confidence, status |

### Rules that make the data usable for a model later

- **Point in time:** store `published_at` and `first_seen_at` in IST for every document. Train only on what was known before market close on that date.
- **Immutable raw data:** never edit a document. Corrections arrive as new documents.
- **Versioned extraction:** every event records its prompt and model version. When prompts improve, re-run extraction into a new version and compare.
- **Stable identifiers:** link everything to ISIN. Names change, and news spells them inconsistently.
- **De-duplication:** one order win reported by 15 outlets is one event with 15 sources, not 15 events.
- **Measure surprise:** store what was expected (previous guidance or consensus) beside what happened.
- **Benchmark-adjusted labels:** label events with returns relative to Nifty or the sector index, so market-wide days don't drown out company news.
- **Human feedback:** let yourself mark an explanation right or wrong. These corrections are the highest-quality training labels you will have.

## Tech stack and roadmap

A single Python codebase, one PostgreSQL database and a scheduler are enough; everything runs on a laptop or a small cloud server.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Best libraries for scraping, PDFs and data |
| Fetching | httpx, feedparser (RSS), Playwright for pages that need a browser | Polite, cached fetching |
| PDF and audio | pdfplumber or PyMuPDF; Whisper-class speech-to-text for audio-only calls | Transcripts and filings are mostly PDFs |
| Database | PostgreSQL + pgvector | Structured tables and semantic search in one place |
| LLM | Claude API with structured (JSON) outputs; small model to filter, larger model for concalls | Reliable extraction into fixed schemas |
| Scheduling | cron or APScheduler: filings every 15 minutes in market hours, news hourly, prices after close | Simple and dependable |
| Interface | Daily email or Telegram digest first; Streamlit dashboard later | Value from day one, UI when the data is rich |

| Phase | Builds | Gate before the next phase |
| --- | --- | --- |
| 1 | Filings, news and price collection; the raw archive; watchlist | Archive fills reliably every day |
| 2 | Triage, event extraction, move explainer, bullion and macro sources, digest | Explanations are useful on real moves |
| 3 | Concall analysis, promise ledger, order book tracker | Extraction checked against the source documents |
| 4 | Market signals, tenders, ratings, red flags, themes, Q&A | — |

Phases follow the Priority column of the data sources table. This table was rebuilt from the text when the design moved into the repo; the original roadmap diagram was not kept.

Start with Phase 1: it creates the document archive every later phase depends on, and each phase's gate must pass before the next one starts. Durations are estimates for part-time work.

## Does something like this already exist?

Parts of it exist; the whole system does not. Concall summaries, filing alerts and some order-book data are already available from Indian platforms. A personal, structured database built for modelling (cross-quarter promise tracking, order ledgers, event-to-return labels, move explanations) is not offered as a public product.

| Product | What it covers | What it lacks for this plan |
| --- | --- | --- |
| [Tijori Finance](https://tradingqna.com/t/tijori-s-ai-stack-for-company-research/194604) | Concall Monitor: transcribes live calls, produces summaries and dashboards, and compares management statements with earlier filings to flag inconsistencies. [Raised $5M from Zerodha](https://www.yourstory.com/2025/11/tijori-raises-5m-from-zerodha-to-expand-its-ai-product-suite) in Nov 2025 to expand its AI products. | Closest match on concalls. Data stays on their platform; no exportable event database or return labels |
| [Trendlyne](https://help.trendlyne.com/support/solutions/articles/84000396310) | Keyword search inside NSE/BSE announcement PDFs, hourly or daily announcement digests, superstar portfolio and insider/SAST alerts, bulk and block deal alerts, earnings call RSS | Alerts, not analysis; no order ledger or promise tracking |
| [Screener.in](https://www.winvesta.in/blog/investors/fundamental-analysis-tools-and-screeners-2026-guide) | Financials, links to concall transcripts and presentations; Premium (about Rs 4,999/year) includes AI credits for questions over company documents | Document Q&A on demand; nothing tracked over time |
| [ArthaLens](https://tradingqna.com/t/arthalens-free-quarterly-earnings-call-transcript-summaries-guidance-q-a-for-indian-listed-companies/182279) | Free LLM summaries of Indian earnings calls: guidance, Q&A, summary | Summaries per call; no comparison across quarters or database |
| [Perplexity Finance](https://techcrunch.com/2025/08/18/perplexity-now-supports-live-earnings-call-transcripts-for-indian-stocks/) | Live transcripts of Indian earnings calls inside its finance dashboard (Aug 2025) | General-purpose; no watchlist memory or structured storage |
| Sovrenn, [Askfuzz](https://askfuzz.ai/company/itd-cementation-india-ltd) | Results, promoter and HNI buying, capacity expansions, order book and revenue guidance | Curated summaries; not a queryable event history |
| [Concall Summariser](https://chromewebstore.google.com/detail/bjllboeebgehndfkgdfhndkiljmofghb) | Chrome extension: paste a transcript, get a structured note using your own AI key | Manual, one call at a time |
| [NSE-BSE MCP server](https://glama.ai/mcp/servers/dfsjjrmab9) (open source) | Lets an LLM such as Claude query 58 NSE/BSE data tools, including announcements and document download | A useful building block for ingestion, not an analysis system |
| [nse-bse-api](https://github.com/bshada/nse-bse-api) (open source, MIT) | Node library for NSE/BSE data including corporate announcements | Data access only |
| [Apify NSE/BSE announcements scraper](https://apify.com/nexgendata/nse-bse-announcements) | Hosted scraper with alerts for new filings, from about $50 per 1,000 records | Paid; NSE only per its listing |

**What this means for the build:** use these products for what they already do well (Tijori or ArthaLens for quick concall reads, Trendlyne for alerts). Build your own in the places no product covers: the structured, point-in-time database, the promise ledger across quarters, order and execution tracking, and the event-to-return labels. That database is also the asset a future model needs.

The product descriptions above come from search results; the source pages could not be opened from this environment, so check current features and prices on each site.

## Risks and open decisions

| Risk | Mitigation |
| --- | --- |
| NSE blocks scrapers; some sites' terms forbid scraping | Prefer BSE endpoints and RSS; fetch slowly with caching; consider a paid vendor for critical feeds |
| LLM extraction errors (wrong order value, wrong company) | Validate numbers against the source text; keep the source link on every event; review a sample weekly |
| Same story counted many times | Content hashing plus story clustering before extraction |
| Lookahead bias in a future model | Point-in-time timestamps; train only on data known before market close |
| LLM cost grows with coverage | Cheap model to filter relevance, stronger model only for material filings and concalls; prompt caching |
| Explanations sound confident but are wrong | Show confidence and cited sources; record your own right/wrong feedback |
| Advice and regulation | Personal research use only. Sharing recommendations publicly can require SEBI research analyst registration |

### Open decisions

- [ ] Run on a laptop, or on a small cloud server so it works when the laptop is off?
- [ ] Monthly LLM budget? Concall analysis is the largest cost.
- [ ] Watchlist size, and how many of those stocks you own?
- [ ] Dashboard, or a daily email/Telegram digest first?
- [ ] Pay for a data vendor or consensus estimates now, or stay free until Phase 4?
