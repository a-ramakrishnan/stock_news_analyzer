# Design documents

| File | Covers |
| --- | --- |
| [design.md](design.md) | Goal and principles, data sources, architecture, core modules, extended ideas, database, tech stack and roadmap, existing products, risks |
| [agent-design.md](agent-design.md) | The agent team, LLMs and costs, tools, data requirements, hosting, the agent-by-agent build guide, the build-in-public plan |

These files are the reference for the design. Change them in a pull request like code: edit the text, bump the version line at the top of each changed file, and add an entry below.

Versions: a minor bump (1.1) for corrections and decisions that fit the existing plan, a major bump (2.0) when the plan itself changes, such as agents added or dropped, or the architecture changed. Building agents in a different order is a minor change.

## Changes

### 1.16 · Oct 27, 2026

- Theme & Peer Analyst after its first runs: read-across goes only to companies with the theme among their core themes, and "Exports and overseas" links no one; 186 signals became 42 that read as relevant
- README: step 20 marked done

### 1.15 · Oct 27, 2026

- Step 20, the Theme & Peer Analyst:
  - agent 14 marked built, with "As built" notes: themes by Haiku 5.5 rather than Sonnet (classification, 40 items a call); strength and read-across in code; read-across without a direction
  - the `theme_tags` and `peer_signals` tables mapped to the plan's `themes` and `peer_signals`
  - the dashboard has a Themes page (eight pages)
- Status tables and the block diagram updated; the last agent left is Analyst Q&A

### 1.14 · Oct 27, 2026

- The Bullion Analyst's first notes recorded in its "As built" notes: four unusual days explained from their news for $0.035
- News Collector: Google News refused the browser-imitating client (HTTP 503); a refused feed is now retried with a plain client, which restored company searches (160 new articles on the first run)
- README: step 19 marked done

### 1.13 · Oct 27, 2026

- Step 19, the Bullion Analyst:
  - agent 13 marked built, and agent 5's bullion part: the Indian price is taken from the NSE gold and silver ETFs in the stored bhavcopy, as IBJA and MCX offer no free download
  - global prices and USD/INR from stooq or Yahoo Finance; each day's move split into global, USD/INR and other; Sonnet 5.5 notes on unusual days only
  - the `market_series` and `bullion_moves` tables mapped to the plan's `bullion_notes`; the bullion data source row updated
- After the first run: global prices taken at the Indian close from Yahoo's hourly prices (the daily New York close put half of each move on the wrong day); notes wait when the day's news can't be fetched
- Status tables and the block diagram updated; the next agents are the Theme & Peer Analyst, then Analyst Q&A

### 1.12 · Oct 27, 2026

- Delivery: Telegram is set aside for now; email delivery of the digest and high-severity red flags is planned for later. Status tables, the Reporter notes and the decisions list updated.
- The Red-flag Monitor after its first runs: a promoter selling is graded by the share of the company sold (worked out from the number of shares where the filing gives no percentage), funds trimming stakes are low, and mixed court outcomes a step lower
- The recommended next step is now the Bullion Analyst; block diagram updated

### 1.11 · Oct 27, 2026

- Step 18, the Red-flag Monitor:
  - agent 15 marked built, with "As built" notes: rules over the checked events and results deadlines, no LLM (the plan had Sonnet score severity; the checked events make rules enough)
  - the `red_flags` table mapped to the plan's `alerts`
- Event amounts kept to four decimals of a crore, so penalties in lakh keep their value
- Status tables and the block diagram updated; the next step is Telegram delivery

### 1.10 · Oct 27, 2026

- Step 17, the rest of the Event Extractor and the QA Checker:
  - agents 7 and 8 marked built, with "As built" notes
  - typed events from filings that results, orders and calls don't cover, with materiality against trailing revenue
  - code checks on every event, a Sonnet 5.5 second pass on flagged and important ones, a review queue kept on the events themselves
  - the `events` and `event_filings` tables mapped to the plan
- Status tables and the block diagram updated; the next step is the Red-flag Monitor, built on the events

### 1.9 · Oct 26, 2026

- Results from the exchange's XBRL files (no LLM) as the first source, the PDF reader as the fallback:
  - NSE's results listing (to January 2025) and its Integrated Filing (Financial) listing (from February 2025)
  - XBRL figures checked too: profit against EPS × shares, half years under a quarter's label rejected; failed figures keep the PDF reading
  - a daily `xbrl` job at 07:15, before the PDF reader
- SME corporate actions fetched from NSE's SME section
- Status tables and the block diagram updated

### 1.8 · Oct 26, 2026

- The Results Reader after its first real runs:
  - figures kept only if the exact number is in the filing, and checked against each other; a decimal point lost in the PDF text is restored
  - a results press release's key-figures table used when a filing has no statement
  - Sonnet 5.5 as a second try for answers Haiku cuts off
- NSE SME companies' filings fetched from NSE's SME section (SSEGL had none)
- Order measures use the latest order book the results cover
- Block diagram: SME filings shown under sources

### 1.7 · Oct 26, 2026

- Step 16, the Results Reader:
  - agent 7, the Event Extractor, marked partly built: results figures from every results filing (Haiku 5.5)
  - "As built" notes under event extraction and agent 7
  - the order tracker's revenue gaps filled from results, including half-yearly SME results
  - the `results` and `result_filings` tables mapped to the plan
  - status tables and the block diagram updated; the next step is the rest of the Event Extractor and the QA Checker

### 1.6 · Oct 26, 2026

- A block diagram of built and pending agents (Mermaid, drawn by GitHub) under Build status in agent-design.md, with a status summary table; linked from the status section of design.md.

### 1.5 · Oct 26, 2026

- Step 15, wider coverage:
  - the Concall Analyst, and so the Promise Ledger, reads every watchlist stock, not only owned ones
  - order-win filings recognised by single-order wordings too ("Receipt of Work Order", "Letter of Award", "L1 bidder"), so smaller and SME companies' orders reach the Order Book Tracker
  - `sna orders coverage` shows per stock what was found, and why a company has no order book
  - status tables and the Concall Analyst cost line updated

### 1.4 · Oct 26, 2026

- Step 14, the Order Book Tracker:
  - agent 10 marked built
  - "As built" notes on orders, order books, metrics and peers
  - the `orders`, `order_filings` and `order_book_snapshots` tables mapped to the plan

### 1.3 · Oct 25, 2026

- Step 13, the rest of the Promise Ledger:
  - promises checked against later results and filings
  - a credibility score per company
  - the `promise_checks` table
  - agent 12 marked built

### 1.2 · Oct 25, 2026

- Step 12, the Earnings Call Analyst, recorded in both documents:
  - status tables updated: Concall Analyst built, Promise Ledger partly built
  - "As built" notes under the earnings call module and agents 11 and 12
  - the three new tables mapped to the plan
  - the cost estimate added
- The two open decisions answered: Earnings Call Analyst next; unusual-day threshold kept at 2.0σ.

### 1.1 · Oct 25, 2026

The design brought up to date with steps 1–11.

- Both files:
  - a status section: what is built, what is not, and which build step did it
  - "As built" notes under each module or agent that exists
- design.md:
  - data sources marked built or not started
  - a table mapping the tables built so far to the planned ones
  - the tech stack as used: curl_cffi, pypdf, APScheduler, Haiku/Sonnet, Streamlit
  - Phase 1 marked done and Phase 2 in progress
  - the open decisions answered; two new ones added (next agent, unusual-day threshold)
- agent-design.md:
  - the actual LLM costs next to the estimates
  - Sonnet 5.5 instead of Opus 5.5 for the Move Explainer
  - the actual schedule and hosting
  - the one change to the build order: the Move Explainer came before the Event Extractor

The original plan text is unchanged; differences are recorded beside it, so the plan and what was built can be read together.

### 1.0 · Oct 21, 2026

The original design, written before any code. Moved into the repo on Oct 23, 2026 unchanged except for:

- a version line at the top of each file, and links between the two files
- the three diagrams (architecture, roadmap, agent team) redrawn as text; the roadmap table was rebuilt from the data sources table
