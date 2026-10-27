# Stock News Analyzer

A set of small agents that track news, exchange filings and earnings calls for Indian stocks and bullion. They explain why stocks move, track order wins and management promises, and build a point-in-time database that can train a model later. No technical analysis: prices are only used to measure what each piece of news did to a stock.

- Design: [system design](docs/design/design.md) (architecture, data sources, database) and [agent design](docs/design/agent-design.md) (models, costs, agent-by-agent plan); versions and changes in [`docs/design/README.md`](docs/design/README.md)
- Build log, one file per step: [`docs/build-log/`](docs/build-log/)

Every command block below can be pasted into Terminal as is; explanations are in the tables.

## Status

| Step | What | Status |
| --- | --- | --- |
| 1 | Project skeleton: Python package, Postgres + pgvector in Docker, config, health check, CI | done |
| 2 | Database tables + Watchlist Manager agent | done |
| 3 | Filings Collector (BSE + NSE announcements) | done |
| 4 | News Collector (RSS feeds + Google News) | done |
| 5 | Price & Label (NSE daily prices, moves, labels) | done |
| 6 | Orchestrator + first daily digest | done |
| 7 | Dashboard: Phase 1 output in the browser | done |
| 8 | History since Oct 2023: news backfill + `make backfill` | done |
| 9 | Phase 2 starts: News Triage agent (Claude Haiku), LLM cost log and budget | done |
| 10 | Move Explainer agent (Claude Sonnet): the likely cause of each unusual day | done |
| 11 | Bulk/block deals and peer moves, fed to the Move Explainer | done |
| 12 | Earnings Call Analyst (Claude Sonnet) and the promise ledger | done |
| 13 | Promise Ledger (Claude Sonnet): promises checked against later results; credibility per company | done |
| 14 | Order Book Tracker: orders from filings (Claude Haiku), quarterly order books (Claude Sonnet), book-to-bill and peers | done |
| 15 | Wider coverage: earnings calls for every watchlist stock, single-order filings, `sna orders coverage` | done |
| 16 | Results Reader (Claude Haiku): revenue, profit and margins from quarterly and half-yearly results; fills order-book revenue gaps; XBRL first | done |
| 17 | Event Extractor (Claude Haiku) and QA Checker (code checks + Claude Sonnet): capex, ratings, management changes, legal matters, deals, fundraises, promoter actions, disruptions | done |
| 18 | Red-flag Monitor: auditor and CFO exits, downgrades, pledges, penalties, late results; in the digest and dashboard | this PR |

## Run it on a Mac

You need [Homebrew](https://brew.sh). Install uv (Python package manager) and Docker Desktop, then open Docker Desktop once so it starts:

```bash
brew install uv
brew install --cask docker
git clone https://github.com/a-ramakrishnan/stock_news_analyzer.git
cd stock_news_analyzer
make setup
make up
make health
```

| Command | What it does |
| --- | --- |
| `make setup` | Install dependencies; create `.env` from `.env.example` |
| `make up` | Start Postgres + pgvector in Docker (port 5433) |
| `make health` | Check everything is connected |

`make health` should print:

```
data dir     ok  /…/stock_news_analyzer/data
timezone     ok  Asia/Kolkata
postgres     ok  16.x
pgvector     ok  0.8.x
```

## Watchlist

Add stocks on the dashboard's **Manage stocks** page, or edit [`config/watchlist.yaml`](config/watchlist.yaml) and load it. Running `make watchlist` re-applies the file, so a stock listed there comes back as the file says.

```bash
make migrate
make securities
make watchlist
```

| Command | What it does |
| --- | --- |
| `make migrate` | Create or update the database tables |
| `make securities` | Download the NSE + BSE lists of listed companies |
| `make watchlist` | Load `config/watchlist.yaml` and show the watchlist |
| `uv run sna watchlist add "Karur Vysya Bank" --owned --alias KVB` | Add or update a stock by name, NSE symbol, BSE code or ISIN |
| `uv run sna watchlist add gold` | Track bullion (gold or silver) |
| `uv run sna watchlist list` | Show the watchlist with NSE/BSE codes and industry |
| `uv run sna watchlist remove LT` | Stop tracking |
| `uv run sna watchlist peers LT` | Suggest same-industry peers; save with `--approve SYMBOL` |

`make securities` also reads NSE's SME (Emerge) list, so SME stocks such as Sathlokhar can be tracked. If NSE blocks a download, open the link `make securities` prints in a browser, save the file, and pass it with `--nse-file ~/Downloads/EQUITY_L.csv` or `--nse-sme-file ~/Downloads/SME_EQUITY_L.csv`.

## Filings (exchange announcements)

```bash
make filings
uv run sna filings list
```

| Command | What it does |
| --- | --- |
| `make filings` | New BSE + NSE filings since the last run (first run: last 7 days) |
| `uv run sna filings backfill --since 2023-10-01` | One-off history; PDFs only for important filings |
| `uv run sna filings list LT` | Latest filings for one company |
| `uv run sna filings list --type order_win` | Filter by type: `results`, `concall_transcript`, `credit_rating`, ... |
| `uv run sna filings show 42` | Details and extracted text of filing 42 |
| `uv run sna filings attachments --pdf all` | Download PDFs skipped earlier |
| `uv run sna filings attachments --retry-failed` | Re-download PDFs that failed to read |
| `uv run sna filings reclassify` | Re-apply filing-type rules to stored filings |

PDFs are saved under `data/filings/<ISIN>/<bse|nse>/<YYYY-MM>/` and their text is stored in the database.

## News

Feeds are listed in [`config/news_feeds.yaml`](config/news_feeds.yaml). Check them once, then fetch:

```bash
uv run sna news check-feeds
make news
uv run sna news list
```

| Command | What it does |
| --- | --- |
| `uv run sna news check-feeds` | Fetch every feed once; report which work |
| `make news` | Read all feeds + a Google News search per company; keep articles that mention a watchlist company |
| `uv run sna news fetch --no-google` | Feeds only, no Google News |
| `uv run sna news list KARURVYSYA` | Latest articles for one company |
| `uv run sna news backfill --since 2023-10-01` | One-off: older articles from Google News, a month per search per company (feeds only carry recent news) |
| `uv run sna news relink` | Re-match stored articles after editing `aliases` or `exclude` |

Articles are matched by company name (without "Limited") and the `aliases` in `config/watchlist.yaml`; `exclude` phrases there (e.g. "L&T Technology") stop look-alike companies from matching.

## News triage (Phase 2, LLM)

Claude Haiku reads each new article about a watchlist stock and records whether it is really about that company, its topic (results, order win, guidance, management, corporate action, deal, capacity, regulatory, rating, market, sector), the sentiment for a shareholder, an importance from 1 (noise) to 5 (could move the stock) and a one-line summary. Several papers report the same event in different words: near-identical headlines are caught without the LLM, and Claude links the rest to the first report of the same event. Repeats reuse the first report's triage and are hidden from the digest and dashboard.

Put your key from [console.anthropic.com](https://console.anthropic.com) in `.env` as `ANTHROPIC_API_KEY=...` (never commit it), then:

```bash
make migrate
make triage
uv run sna triage list
uv run sna llm usage
```

| Command | What it does |
| --- | --- |
| `make triage` | Triage every article not triaged yet (the first run also covers the history, about $1 for a few thousand articles) |
| `uv run sna triage run --symbol LT --since 2026-10-01` | Only one stock, or only recent articles |
| `uv run sna triage list LT` | Last 7 days, importance 3 and up, most important first (`--min-importance 1 --all` shows everything) |
| `uv run sna triage reset --symbol LT` | Forget triage results (one stock, or all without `--symbol`) so the next run judges them again |
| `uv run sna llm usage` | This month's LLM calls and cost by task and model, against the budget |

The scheduler runs the triage every hour at :25, ten minutes after the news. The digest, the News page and the Stock page then hide off-topic articles and repeats and sort the rest by importance.

| Setting in `.env` | Default | Meaning |
| --- | --- | --- |
| `LLM_MODEL_TRIAGE` | `claude-haiku-5-5` | Model for high-volume work such as triage |
| `LLM_MODEL_ANALYSIS` | `claude-sonnet-5-5` | Model for judgement work: move explanations, earnings calls |
| `LLM_MONTHLY_BUDGET_USD` | `20` | LLM calls stop for the rest of the month (India time) once this much is spent |

Every call is logged with its tokens and cost (the `llm_calls` table, `sna llm usage`, and the dashboard's System page).

## Bulk and block deals

NSE's daily lists of large trades: bulk deals (one client trading more than 0.5% of a company's shares in a day) and block deals (Rs 10 crore or more in the block window). All stocks are stored, linked to companies by NSE symbol.

```bash
uv run sna deals probe
uv run sna deals backfill --since 2023-10-01
uv run sna deals list KMEW --days 365
```

| Command | What it does |
| --- | --- |
| `uv run sna deals probe` | Fetch the last week and show NSE's raw format and what was read from it |
| `uv run sna deals backfill --since 2023-10-01` | History, a month per request (part of `make backfill`) |
| `uv run sna deals fetch` | New deals since the last stored day (the scheduler does this at 19:00 and 22:00 on weekdays) |
| `uv run sna deals list KMEW` | A watchlist stock's deals: who bought or sold how many shares at what price |
| `uv run sna deals load ~/Downloads/bulk.csv --kind bulk` | Load a file saved from NSE's bulk/block deals page, if the automatic fetch is blocked |

## Peers

The Move Explainer compares each unusual day with how a few peers moved. Set them on the dashboard's **Manage stocks** page (the Peers column, NSE symbols separated by commas). Without them it uses the largest companies in the stock's NSE industry, which small companies outside the Nifty 500 often do not have.

## Move explainer (Phase 2, LLM)

For each unusual day, Claude Sonnet reads the day's numbers (stock, Nifty 50, sector index, z-score, the days before), corporate actions with that ex-date, bulk and block deals with their share of the day's volume, how its peers moved, and the filings and triaged news from two sessions before to the next morning. It records the likely cause (results, order, company news, sector, market, corporate action, flows, or unexplained), its confidence, two or three sentences, and the documents it relied on.

```bash
uv run sna explain run --since 2025-10-01
uv run sna explain list LT
```

| Command | What it does |
| --- | --- |
| `uv run sna explain run --since 2025-10-01` | Explain unusual days not explained yet, from a date (prints the count and a rough cost first, about $0.02 a day) |
| `make explain` | All unusual days not explained yet, up to yesterday |
| `uv run sna explain list LT --days 365` | Explanations with their cause, confidence and the documents behind them |
| `uv run sna explain run --since 2023-10-01 --redo-unexplained` | Try again the days answered "unexplained" (after adding deals or peers) |
| `uv run sna explain reset --symbol LT` | Forget explanations so they are written again |

The scheduler explains the last two weeks' unusual days at 07:45, before the 08:00 digest: a day is explained the morning after, once the papers have said why it moved. Explanations appear in the digest, on the Stock page (chart hover and an **Unusual days** tab) and on the Today cards.

## Earnings calls (Phase 2, LLM)

For every watchlist stock, owned or not, Claude Sonnet reads the earnings call transcript the company files with the exchanges:

- **The call:** a summary, management's tone, and 3-5 points to watch.
- **What management said:** 6-15 key points (guidance, demand, margins, capex, order book, risks, new initiatives), each with the speaker's own words.
- **What analysts pressed on,** and whether management answered directly, partially or evasively.
- **Since the previous call:** what is new, what management stopped mentioning, tone changes, revised targets.
- **The promise ledger:** every commitment with a target and a time ("Plant 2 by Q3 FY27", "EBITDA margin 18-20% in FY27"), with its due date. Each later call marks earlier promises on track, kept, delayed, revised or dropped when management mentions them.

Calls are read oldest first, so each one is compared with the one before. A transcript filed on both BSE and NSE is read once. Some companies file only a letter with a link to the transcript on their website: the link is followed and the transcript saved under `data/concalls/`. Each quote is checked against the transcript, and a quote that is not found is not shown.

```bash
make migrate
uv run sna concalls run
uv run sna concalls list
uv run sna concalls show LT
uv run sna concalls promises --open
```

| Command | What it does |
| --- | --- |
| `uv run sna concalls run` | Read transcripts of the last 400 days not read yet. It prints how many calls and a rough cost first, and asks before spending more than $2 |
| `uv run sna concalls run --since 2023-10-01` | Go further back (about $0.10 a call) |
| `uv run sna concalls run --symbol BECTORFOOD` | One stock only |
| `uv run sna concalls list LT --all` | Calls read, newest first; `--all` also shows transcripts not read and why (copies, scanned PDFs, AGMs) |
| `uv run sna concalls show LT --quarter "Q2 FY27"` | One call in full (default: the latest) |
| `uv run sna concalls promises LT` | The promise ledger, soonest due first, with each promise's target and how management put the deadline; open promises past their date are marked OVERDUE. Deadlines like "within 12 months" or "next 3 years" are counted from the call date |
| `uv run sna concalls reset --symbol LT` | Forget calls (with their points and promises) so they are read again; `--unread-only` retries only those with no text |

The scheduler reads new transcripts at 07:30, before the 08:00 digest. New calls appear in the digest and on the Stock page's **Earnings calls** tab, along with the promise ledger and the transcripts that could not be read.

## Promise ledger (Phase 2, LLM)

The Earnings Call Analyst records each promise with a due date, and later calls update the ones management mentions again. Once a promise's date has passed, the Promise Ledger settles it. Claude Sonnet reads what the company published around and after that date: results, investor presentations, filings about commissioning, capacity, approvals or launches, and later calls. It decides whether the promise was **kept**, **kept late**, **partly** kept or **missed**, with a one-sentence finding and the documents it rests on. When the documents don't say yet, the promise is checked again once new results or filings arrive. A promise can't be marked missed until its results are due out (75 days after the due date). An earlier "missed" is held, and applied then if nothing newer arrives. News doesn't count as a new document.

Each company gets a credibility score: kept counts 1, kept late or partly 0.5, and missed, dropped or long overdue 0, over the promises settled so far. It is shown once 3 promises are settled.

```bash
make migrate
uv run sna promises check
uv run sna promises scores
uv run sna promises list GRAVITA
```

| Command | What it does |
| --- | --- |
| `uv run sna promises check` | Check promises past their date, one LLM call per company (about $0.05). Already-checked ones are skipped until new documents arrive |
| `uv run sna promises scores` | Credibility per company: the score and how many promises were kept, kept late, partly kept, missed, dropped, long overdue, or are still to come |
| `uv run sna promises list GRAVITA` | The ledger with each promise's status and latest finding (same as `sna concalls promises`) |
| `uv run sna promises reset --symbol GRAVITA` | Forget the checks; promises go back to what the calls last said |
| `make promises` | Check, then show the scores |

The scheduler checks promises at 07:40, after reading new calls. Settled promises and those due in the next 30 days appear in the digest. The Stock page's **Earnings calls** tab shows the score and how each promise was checked.

## Order book (Phase 2, LLM)

For order-driven companies (EPC, capital goods, defence, marine, power T&D):

- **Orders:** Claude Haiku reads each order-win filing and records the client, client type (government, PSU, private, export), value in Rs crore, segment, domestic or export, and execution period. When only a range is given (L&T's "large": Rs 2,500-5,000 crore), the midpoint is used. When a filing only says "large", the range comes from the company's own filings that define it. An announcement filed on both BSE and NSE is stored once, and filings that aren't order wins are dropped.
- **Order book:** once a company has 2 or more orders, Claude Sonnet reads its order book, the quarter's order inflow and revenue, one document per quarter. It tries the investor presentation first, then the call transcript, then results.

Banks, consumer and off-the-shelf manufacturing companies have no order book, so they don't appear here. `sna orders coverage` shows, for every watchlist stock, what was found.

From those, in code:

| Measure | What it is |
| --- | --- |
| Announced vs reported inflow | A gap means orders that weren't announced (often many small ones) or orders with no value given |
| Book-to-bill | Orders won ÷ revenue, last four quarters; above 1 means the order book is growing |
| Years of revenue | Latest order book ÷ last four quarters' revenue |
| Execution | Last four quarters' revenue ÷ the order book a year earlier |
| Unexplained change | Closing book − (opening book + inflow − revenue). Negative suggests cancellations or revenue from outside the book |
| Concentration | Share of the last year's orders from government/PSU clients, and from the largest client |
| Peers | The order-driven stocks on your watchlist side by side, ranked |

```bash
make migrate
uv run sna orders run
uv run sna orders book LT
uv run sna orders peers
```

| Command | What it does |
| --- | --- |
| `uv run sna orders run` | Read order-win filings not read yet (Haiku, a fraction of a cent each), then order books (Sonnet, about $0.03 a quarter) |
| `uv run sna orders list KMEW` | A company's orders, newest first, with value, client and what they are for |
| `uv run sna orders book LT` | Quarter by quarter: orders announced, inflow, revenue, order book, book-to-bill, unexplained change; then the four-quarter summary |
| `uv run sna orders peers` | Order-driven stocks side by side, ranked on book-to-bill, years of revenue and order growth |
| `uv run sna orders coverage` | Every watchlist stock: order-win filings found, read, copies, not order wins, waiting for a PDF; orders; order books; whether its order book is tracked |
| `uv run sna orders reset --symbol LT` | Forget orders and order books so they are read again (`--orders-only` or `--books-only` for one of them) |

The scheduler reads new orders and order books at 07:50. New orders appear in the digest, and the Stock page has an **Order book** tab: the measures, a chart of announced vs reported inflow, the quarterly table, the orders, and the peers.

## Results (Phase 2, LLM)

**XBRL first.** Most results come from the exchange's XBRL files: every figure tagged, in rupees, no LLM. `sna results xbrl` (daily at 07:15) reads NSE's results listing (filings up to January 2025) and its Integrated Filing (Financial) listing (from February 2025), consolidated where filed. The figures are checked too, since companies fill the tags themselves: profit must fit EPS × shares (paid-up capital ÷ face value), and a "quarter" far above the company's nearby quarters (an SME half year under a quarter's label) is rejected. Figures that fail keep the PDF reading below. `sna results list` marks periods from XBRL.

**The PDF reader** fills what XBRL doesn't cover. Claude Haiku reads each results filing of every watchlist stock and copies the headline figures from the results statement: revenue from operations, other income, finance costs, depreciation, profit before and after tax, and EPS. It copies each figure as written plus the statement's unit (lakh, crore, million); the conversion to Rs crore is done in code, and each figure is checked against the filing's text.

- **One filing, three periods:** a results statement also gives the previous quarter and the same quarter a year earlier, so those fill in at once. A period's own filing wins over a later filing's comparative column.
- **Quarters or half years:** main-board companies report quarterly; SME companies report half-yearly, and their half years are stored as H1 and H2.
- **Consolidated first:** the consolidated statement is used where the filing has one, else standalone. Profit is the profit attributable to the company's owners (the one EPS is based on), not the total including minority interests.
- **Copies:** the BSE and NSE copies, the board meeting outcome and the newspaper advertisement of the same results are read once.
- **Order books:** where an order-book document left out a quarter's revenue, the results' revenue is used (marked `*` in `sna orders book`). For a company without four quarters of figures (a half-yearly SME reporter), revenue is the 12 months to the latest order book from its results, and book-to-bill uses the orders it announced if it didn't report its inflow.

```bash
uv run sna results run
uv run sna results list LT
uv run sna results coverage
```

| Command | What it does |
| --- | --- |
| `uv run sna results run` | Read results filings of the last 800 days not read yet (Haiku, about $0.002 a quarter); shows the cost first and asks above $1 |
| `uv run sna results list LT` | Period by period: revenue and its change on a year earlier, EBITDA and margin, profit and its change, EPS |
| `uv run sna results coverage` | Every watchlist stock: results filings found, read, copies, without a statement, without text, waiting for a PDF; periods stored; the latest period |
| `uv run sna results xbrl` | Take results from NSE's XBRL files: exact tagged figures, no LLM. Replaces the PDF reading of the same period. Covers the results listing (to January 2025) and the integrated filings (from February 2025); runs daily at 07:15 |
| `uv run sna results probe LT` | Show NSE's results listing and one XBRL file for a stock, to check their format |
| `uv run sna results reset --symbol LT` | Forget results so they are read again |

EBITDA here is profit before tax + finance costs + depreciation − other income. The scheduler reads new results at 07:20, before the order books. New results appear in a "Results" section of the digest, and the Stock page has a **Results** tab: the latest revenue, profit and margin, a revenue chart and the table.

## Events and QA (Phase 2, LLM)

**Event Extractor.** Results, order wins and earnings calls have their own agents. This one reads the rest of a watchlist stock's filings whose title names an event, and records typed events: capex and capacity, guidance, management changes (directors, MD, CEO, CFO, auditor), credit ratings, legal and regulatory matters, acquisitions and other deals, fundraises, promoters' buying, selling and pledges, disruptions (fire, strike, shutdown), agreements and approvals. Routine filings (trading window, certificates, newspaper copies) are skipped by their title before any LLM call. Claude Haiku reads six filings a call; each event gets a headline, date, sentiment, importance (1-5), its main amount as written and in Rs crore, the parties, and the sentence it came from. The PDFs of these filings weren't downloaded before; the run downloads them first (up to 300 a run), and the collector now downloads them as they come.

**QA Checker.** Every new event is checked in code:

- the quote is in the filing
- the amount, as written, is in the filing, and its unit gives the value recorded: the code converts "Rs 75 lakh" or "INR 1,200 million" itself and corrects the model's arithmetic
- the amount against the company's revenue for the 12 months before: shown as a share of revenue, and flagged above a year's revenue
- the fields a type needs (a rating action's agency and new rating, a management change's person, role and action)
- the date is near the filing's; a stake is a percentage
- not the same event as an earlier filing's (an intimation and its outcome)

Events a check flagged, and every event of importance 4 or 5, then get a second pass with Claude Sonnet: is the filing about this company, is it a real event, is the type right, is the amount right. It can correct the type or the amount (when the right amount is in the filing). Events it can't confirm wait in the review queue; your decisions are kept with the events as training data.

```bash
uv run sna events run
uv run sna events coverage
uv run sna events list
uv run sna events review
```

| Command | What it does |
| --- | --- |
| `uv run sna events run` | Download missing PDFs, read filings of the last 400 days not read yet (Haiku), check the new events (QA); shows the cost first and asks above $1 |
| `uv run sna events list LT` | Events, newest first: type, importance, sentiment, headline, amount and share of revenue; `--type credit_rating`, `--importance 3`, `--days 365`, `--all` for hidden ones |
| `uv run sna events show 12` | One event in full: its fields, quote, QA notes and the filing's link |
| `uv run sna events review` | The review queue: events the QA Checker flagged or failed, with the reasons |
| `uv run sna events accept 12` / `reject 12` | Your decision (`--note` to say why); accepted events are shown, rejected ones hidden |
| `uv run sna events coverage` | Every watchlist stock: candidate filings, read, with no event, copies, failed, waiting; events passed, flagged, failed, repeated |
| `uv run sna events reset --symbol LT` | Forget events (and reviews) so they are read again |

The scheduler reads new filings at 07:25. Events of importance 3 or more appear in an "Events" section of the digest, flagged ones marked *unchecked*, and the Stock page has an **Events** tab.

## Red flags

The Red-flag Monitor reads the checked events and raises warnings about governance and balance-sheet risk. It is plain code, with no LLM: the events are already typed and checked, so it only picks out the ones that warn of trouble and grades them.

| Flag | Severity |
| --- | --- |
| Statutory auditor resigns or is removed | high (internal or secretarial auditor: medium) |
| CEO, MD or CFO resigns or retires early | high; leaves any other way: medium |
| Independent director resigns mid-term | medium |
| Rating downgrade | high; negative outlook or watch: medium |
| Promoter pledge invoked | high; pledge created: medium |
| Promoter sells shares | medium; a fund or other large holder selling 1% or more: low |
| Penalty, tax demand, court or regulator's order | by size against a year's revenue: 1%+ high, 0.1%+ medium, smaller low; any SEBI order at least medium; a mixed outcome (hearing adjourned, stay continuing) one step lower |
| Fire, strike, shutdown or other disruption | high when important (4-5), else medium |
| Results not filed by the deadline (45 days; 60 for the year) | medium; 30 days late: high |

```bash
uv run sna flags run
uv run sna flags list
```

| Command | What it does |
| --- | --- |
| `uv run sna flags run` | Raise the flags not raised yet; each is raised once, and open ones are re-graded if the rules change |
| `uv run sna flags list LT` | Flags of the last year, most serious first; `--low` for low ones, `--dismissed` for those you dismissed |
| `uv run sna flags dismiss 7 --note "..."` | Dismiss a flag once dealt with; it stays on record with your note |

The scheduler raises new flags at 07:55. High and medium flags about recent filings open the digest. The Today page lists those from the last 30 days, and the Stock page's **Events** tab shows the stock's flags from the last year.

## Prices, moves and labels

```bash
uv run sna prices backfill --since 2023-10-01
make prices
uv run sna prices moves LT
uv run sna labels list LT
```

| Command | What it does |
| --- | --- |
| `uv run sna prices backfill --since 2023-10-01` | One-off: load NSE daily prices and index closes for every listed stock (about 2 requests per trading day, progress shown; re-running skips stored days) |
| `make prices` | Load new trading days, update daily moves and labels |
| `uv run sna prices moves LT` | Daily return vs Nifty 50 and the sector index; `!!` marks unusual days |
| `uv run sna prices moves --unusual --days 250` | Only the unusual days of the last year |
| `uv run sna prices indices bank` | NSE index names, for `sector_index` in `config/watchlist.yaml` |
| `uv run sna prices actions` | Bonus issues, splits and dividends used to adjust returns |
| `uv run sna labels list LT --type order_win` | Each filing or article with the stock's return vs Nifty 50 after 1, 5 and 20 trading days |

Returns are adjusted for bonus issues, splits and dividends using NSE's corporate actions. A day is unusual when the stock's return minus the Nifty 50's is more than `UNUSUAL_THRESHOLD` (default 2.0, set in `.env`) standard deviations of the previous 60 days. Labels start from the first trading day whose close could reflect the news (same day if published before 15:30 IST).

## History in one go

```bash
make scheduler-stop
make backfill
make scheduler
```

| Command | What it does |
| --- | --- |
| `make backfill` | Prices, filings (PDFs for important ones), news and labels since 1 Oct 2023; safe to stop and re-run, stored items are skipped |
| `make backfill SINCE=2024-04-01` | The same from another date |

Stopping the scheduler first keeps the two from fetching from the exchanges at the same time.

## Orchestrator and daily digest

The orchestrator runs every job on the schedule in [`config/schedule.yaml`](config/schedule.yaml) (India time) and logs each run.

```bash
uv run sna orchestrator show
make run-all
make digest
make scheduler
```

| Command | What it does |
| --- | --- |
| `uv run sna orchestrator show` | The schedule and when each job runs next |
| `make run-all` | Run every job once, now, in order: collect, triage, measure, explain, read calls, digest |
| `uv run sna run news` | Run one job now: `filings`, `news`, `triage`, `deals`, `prices`, `xbrl`, `results`, `events`, `explain`, `concalls`, `promises`, `orders`, `flags`, `securities` or `digest` |
| `uv run sna runs` | Recent runs: when, how long, result, errors |
| `make digest` | Print the digest covering everything since the last scheduled digest (`--hours 24` for a fixed window) |
| `make scheduler` | Start the orchestrator in Docker; it keeps running while Docker Desktop is open |
| `make scheduler-logs` / `make scheduler-stop` | Follow its output / stop it |
| `uv run sna orchestrator start` | Run the orchestrator in this terminal instead (Ctrl+C to stop) |

Scheduled digests are saved as Markdown under `data/digests/`. While the Mac sleeps nothing runs; a run missed by up to 3 hours happens on wake.

## Dashboard

A local web page over everything collected. Every page only reads, except **Manage stocks**, where you add, edit and remove stocks.

```bash
make ui
```

| Command | What it does |
| --- | --- |
| `make ui` | Open the dashboard at http://localhost:8501 (Ctrl+C in the terminal stops it) |
| `make ui-docker` / `make ui-stop` | Run it in Docker instead, next to the scheduler / stop it |

| Page | What it shows |
| --- | --- |
| Today | Indices, then **Stocks I own** and **Watchlist** as separate groups of cards (move vs Nifty 50 and sector, unusual badge, 3-month sparkline), the latest digest, job health |
| Stock | Stock vs sector vs Nifty 50 indexed to 100, key filings and unusual days marked; unusual days with their likely cause, results, earnings calls and the promise ledger, the order book, filings, news, deals, reactions and corporate actions |
| Filings | Search by stock, type, words and date; read a filing's extracted text |
| News | Search headlines; links to the articles |
| What moves the stock | Average return vs Nifty 50 after each kind of filing, 1, 5 and 20 trading days later |
| Manage stocks | Search any listed company and add it to Stocks I own or Watchlist, with news aliases and a sector benchmark; edit or remove stocks; **Load history now** fetches a new stock's filings, news and moves since Oct 2023 |
| System | Schedule, stored data, recent runs and errors |

## Other commands

| Command | What it does |
| --- | --- |
| `make test` | Run the tests in a separate `sna_test` database (skipped if Postgres is not running) |
| `make lint` / `make format` | Check or fix code style |
| `make docker-health` | Run the health check inside the app's Docker container |
| `make down` | Stop Docker (your data is kept in a Docker volume) |

## Layout

```
src/stock_news_analyzer/   Python package
  config.py                settings from environment / .env
  db.py                    database connection, migrations, health check
  models.py                database tables
  migrations/              Alembic migrations (one per schema change)
  text.py                  shared text cleaning
  sources/securities.py    NSE/BSE security list download + parsing
  sources/exchange_http.py BSE/NSE web access (browser-like, gets past bot protection)
  sources/announcements.py BSE/NSE announcement parsing + filing types
  sources/news.py          RSS/Atom + Google News fetching and parsing
  agents/watchlist.py      Watchlist Manager (agent 1)
  agents/filings.py        Filings Collector (agent 2)
  agents/news.py           News Collector (agent 3)
  sources/prices.py        NSE bhavcopy + index close parsing
  agents/prices.py         Price & Label (agent 5): prices, moves, labels
  sources/corporate_actions.py  NSE bonus/split/dividend parsing
  agents/orchestrator.py   Orchestrator (agent 0): jobs, schedule, run log
  agents/digest.py         Reporter, basic (agent 16): the daily digest
  llm.py                   the one place that calls Claude: structured answers, cost log, budget
  agents/triage.py         News Triage (agent 6): relevance, topic, sentiment, importance
  agents/explain.py        Move Explainer (agent 7): likely cause of each unusual day
  sources/deals.py         NSE bulk/block deals parsing (JSON API and CSV downloads)
  agents/deals.py          Deals Collector: bulk and block deals for every stock
  agents/concalls.py       Concall Analyst (agent 11): earnings calls and the promise ledger
  agents/promises.py       Promise Ledger (agent 12): promises checked against results, credibility
  agents/orders.py         Order Book Tracker (agent 10): orders, order books, book-to-bill, peers
  agents/results.py        Results Reader: revenue, profit, margins from results filings
  ui/queries.py            dashboard: read-only queries
  ui/charts.py             dashboard: charts
  ui/app.py                dashboard: the Streamlit pages
  cli.py                   `sna` command-line tool
config/watchlist.yaml      your stocks, bullion and their news aliases
config/news_feeds.yaml     news feeds to read
config/schedule.yaml       when each job runs
tests/                     pytest tests
.streamlit/config.toml     dashboard settings
docker/postgres/init.sql   enables pgvector when the database is created
docs/build-log/            what each step added and how to check it
```

Not investment advice. This is a personal research tool.
