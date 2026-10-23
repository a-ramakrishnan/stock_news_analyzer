# Design documents

| File | Covers |
| --- | --- |
| [design.md](design.md) | Goal and principles, data sources, architecture, core modules, extended ideas, database, tech stack and roadmap, existing products, risks |
| [agent-design.md](agent-design.md) | The agent team, LLMs and costs, tools, data requirements, hosting, the agent-by-agent build guide, the build-in-public plan |

These files are the reference for the design. Change them in a pull request like code: edit the text, bump the version line at the top of each changed file, and add an entry below.

Versions: a minor bump (1.1) for corrections and decisions that fit the existing plan, a major bump (2.0) when the plan itself changes, such as agents added, dropped or reordered.

## Changes

### 1.0 · Oct 21, 2026

The original design, written before any code. Moved into the repo on Oct 23, 2026 unchanged except for:

- a version line at the top of each file, and links between the two files
- the three diagrams (architecture, roadmap, agent team) redrawn as text; the roadmap table was rebuilt from the data sources table

## Where the build differs so far

Decisions made while building steps 0–11, not yet folded into the documents. They become version 1.1 when the documents are next revised.

| Design says | Built | Why |
| --- | --- | --- |
| Opus 5.5 for move explanations and the digest | Haiku 5.5 for triage, Sonnet 5.5 for move explanations; the digest has no LLM | Cost: 562 explanations cost $2.42, triage of 4,230 articles $0.29; budget capped at $20 a month |
| Dashboard later, digest first | Streamlit dashboard built in step 7, alongside the digest | Easier to check the data while building |
| Event Extractor (7) before Move Explainer (9) | Move Explainer reads filings and triaged news directly | Explanations were useful without typed events |
| Bulk and block deals in Phase 4 (Market Signals) | Collected now from NSE's CSV download | Needed to explain flow-driven moves |
| Peers suggested by the Watchlist Manager | Peers from the same industry, editable on the Manage stocks page; used by the Move Explainer | Same |
| NSE main board only | NSE SME list added | Watchlist includes SME stocks |
| Triage clusters duplicates by text similarity | Headline matching plus the model linking reports of the same story | Different outlets rarely share wording |
| "No news found" is rare | About 55% of unusual days stay unexplained | The 2σ threshold flags about 1 day in 20 by design; many are noise |

Still to build: Event Extractor, QA Checker, Order Book Tracker, Concall Analyst, Promise Ledger, Bullion Analyst, Theme & Peer Analyst, Red-flag Monitor, Telegram/email delivery, Analyst Q&A.
