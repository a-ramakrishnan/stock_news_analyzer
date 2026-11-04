# Step 29: The dashboard redesigned

**Goal:** a dashboard that looks finished and is easy to read, without leaving Streamlit. Part of the "better interface" in the [sharing plan](../design/sharing.md).

## How it was designed

The design was made in Lovable, as clickable mock-ups with made-up companies, and then rebuilt in the Streamlit dashboard page by page:
- [ui-brief.md](../design/ui-brief.md) describes every page, what it shows and its actions, written from the dashboard's code.
- [lovable-prompts.md](../design/lovable-prompts.md) splits the brief into project rules and eight prompts to paste in order.
- Lovable built the mock-ups in their own repository (`morning-market-compass`), read here only. No data of the author's went to it.

Lovable can only build React apps, so a full React front end was weighed and turned down: it would need an API and would double the code. Lovable was used for the design only.

## In five pull requests

| Step | What |
| --- | --- |
| 1. Look and feel | Light and dark themes from the design's colours (warm off-white or charcoal, deep teal accents, green up and red down); IBM Plex Sans and Mono, bundled with the app and served by Streamlit, so nothing is fetched from the internet; the chart palette; shared styles for cards, tiles, tags and severity dots |
| 2. Today | A page header with "How to use this page"; stock cards with the symbol in mono, the price and change beside a 3-month sparkline, the moves against the Nifty 50 and the sector, an Unusual badge and the likely cause; red flags as rows; bullion with unusual days shaded |
| 3. Stock | Number tiles for the range; charts in titled cards; tables whose text wraps (cards on a phone) for unusual days, events, call points, analysts' questions and the promise ledger, with tags for confidence, status and AI-written text; tiles and coloured tables for results and shareholding |
| 4. Red flags and Ask | Severity as coloured toggle buttons, a flag count, the chosen flag in a card with Dismiss; the answer in a card with an AI tag and numbered, linked sources |
| 5. The rest | The same header on every page; Themes with rising and falling themes, a monthly chart by month and read-across marked as AI; What moves the stock with signed, coloured averages; System with tiles for AI spend and tables for the schedule and stored data; Settings' sources as a table |

## Decisions along the way

- **Chart colours:** the design's teal sector line was too close to the blue stock line. A palette check gave a difference of ΔE 10, below the 15 needed to tell two lines apart. The sector index is ochre instead, which passes the checks for colour-blind readers too, and key-filing diamonds take the stock's colour.
- **Wrapped tables, not Streamlit's:** Streamlit's tables cut long text off to one line. The text-heavy tables are now HTML (`html_table`): text wraps, and on a phone each row becomes a card. Tables where you select a row or tick a box (Filings, News, Red flags, recent runs, the job switches) stay Streamlit's.
- **Sparklines as images:** `st.html` leaves out inline SVG, so the sparklines are small SVG images.
- **Cards:** Streamlit 1.66 gives bordered containers no attribute to style, so cards are containers with a key starting `card`.
- **Mock-up only parts left out:** for example the design's "Example empty state" switch.

## Found and fixed

- Empty cells from a table arrive as NaN, which counts as a value, so a missing quote crashed a tab. `blank()` treats NaN as nothing.
- The first-run setup said only owned stocks get their earnings calls read. That has been wrong since step 15.
- The bullion table showed "None" for days without a note, and the digest's title was its file name.
- The theme chart drew its months as thin weekly bars on a date axis.

## Checked

Each step was run on a demo database built from the test data, with sample results, shareholding, events, an earnings call with promises, red flags, gold days, a saved question and themes added. Every page was screenshotted in the light and dark themes, and the main ones at phone width. Three dashboard tests that read the old layout now read the new tiles and headings; 354 tests pass.

## Also since step 28

- `sna watchlist history SYMBOL...` loads several new stocks' history in one go, like "Load history now" on Manage stocks. It was used to bring the ten largest Nifty 50 stocks up to date.
- `make start` opens Docker Desktop if needed, starts the database first and waits for it, then the dashboard and the scheduler (build log 27).

## Then: the Agent map

A new page under Set up shows the whole system as an agent's anatomy, after a common diagram of how AI agents work, and live:

| Part | In this system |
| --- | --- |
| Input | NSE and BSE websites, news feeds and Google News, Yahoo Finance, the schedule, your questions |
| Perceive | The collectors (filings, news, prices, deals, XBRL results, shareholding, bullion, company lists): no AI |
| Plan | The scheduler: what is running now, what runs next, in a fixed order (collect, judge, measure, report) |
| Think | The AI agents, each with its model: triage, results, events and the QA checker, the move explainer, earnings calls, promises, order books, themes, Ask; and the red-flag rules (no AI) |
| Remember | Short-term: each run's working set. Long-term: the Postgres archive, with counts |
| Act | Tools: the Anthropic API (calls and cost today), exchange downloads, the database (Ask reads only), the data folder |
| Output | The morning digest, the dashboard, open red flags |
| Guardrails | The monthly budget, the API key, job switches, the QA checker, Ask's read-only SQL, your decisions on flags and doubtful events, polite fetching |
| Observe | Runs and errors in the last 24 hours, the average run time, AI calls and failures, the month's spend |

Each box shows its job's state: running (pulsing), last run ok, failed, turned off or not run yet, plus its last run, its next run, and its AI calls and cost today. Hovering shows the last result or error. The page refreshes every 30 seconds (`st.fragment`). It is one HTML page in an iframe (`ui/agent_map.py`, styles in `agent_map.css`), fed by `queries.agent_status`. A test checks a running job, a failed one and today's AI calls on it.

The sidebar now always shows every page: with thirteen, Streamlit had started folding the last ones under "View 3 more".

### Live and replay

The map moved to the Today group, under Red flags, and became a way to learn how an agentic system is built. A switch at the top chooses:
- **Today, live:** the map's state now, refreshed every 30 seconds. Dots loop along the path of each job running now, and a feed explains each of today's runs in plain words, e.g. "Think · the News triage agent took its working set from memory, asked Claude (Haiku) 3 times for $0.006, and wrote its answer back to memory. Result: 10 articles triaged."
- **Replay the last 7 days:** today's or the week's runs (`queries.agent_events`: each run with the AI calls made during it, and each question asked) played back on the map.
  - Play and pause, a speed (10 minutes, an hour or six hours a second), "skip quiet hours", and a time slider that jumps to any moment.
  - As each run starts, the scheduler pulses, its box lights up and shows what that run did, and a dot carries the information along its path: source → collector → memory for a collector; memory → agent → Claude → agent → memory for an AI agent; you → Ask → database → Claude → dashboard for a question.
  - The budget pulses before AI calls and the QA checker with the events agent; a failed run flashes Observe.
  - A tally counts the replayed runs, errors, AI calls and cost.
- **Teaching:** every layer carries one line on what it does in any agentic system, e.g. "Guardrails: limits on what agents may do, checked at every step, not only at the start."

The script is `ui/agent_map.js`, inlined into the page with the run data as JSON.

## On the Mac

```
git checkout main
git pull
make ui
```

The theme follows the Mac's light or dark setting. To switch it by hand, open the ⋮ menu at the top right, then Settings.
