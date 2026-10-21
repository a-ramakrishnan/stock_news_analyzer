# Stock News Analyzer

A set of small agents that track news, exchange filings and earnings calls for Indian stocks and bullion. They explain why stocks move, track order wins and management promises, and build a point-in-time database that can train a model later. No technical analysis: prices are only used to measure what each piece of news did to a stock.

- Design doc: [Indian Market News Intelligence System](https://claude.ai/artifact/2rcGGrRLaCoqDkBeg2nwxJ) (architecture, data sources, agent-by-agent plan)
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
| 6 | Orchestrator + first daily digest | this PR |

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

Edit [`config/watchlist.yaml`](config/watchlist.yaml) first, then:

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

If NSE blocks the download, open the link `make securities` prints in a browser, save the file, and run `uv run sna securities refresh --nse-file ~/Downloads/EQUITY_L.csv`.

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
| `uv run sna news relink` | Re-match stored articles after editing `aliases` or `exclude` |

Articles are matched by company name (without "Limited") and the `aliases` in `config/watchlist.yaml`; `exclude` phrases there (e.g. "L&T Technology") stop look-alike companies from matching.

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
| `make run-all` | Run filings, news, prices and digest once, now |
| `uv run sna run news` | Run one job now: `filings`, `news`, `prices`, `securities` or `digest` |
| `uv run sna runs` | Recent runs: when, how long, result, errors |
| `make digest` | Print the digest covering everything since the last scheduled digest (`--hours 24` for a fixed window) |
| `make scheduler` | Start the orchestrator in Docker; it keeps running while Docker Desktop is open |
| `make scheduler-logs` / `make scheduler-stop` | Follow its output / stop it |
| `uv run sna orchestrator start` | Run the orchestrator in this terminal instead (Ctrl+C to stop) |

Scheduled digests are saved as Markdown under `data/digests/`. While the Mac sleeps nothing runs; a run missed by up to 3 hours happens on wake.

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
  cli.py                   `sna` command-line tool
config/watchlist.yaml      your stocks, bullion and their news aliases
config/news_feeds.yaml     news feeds to read
config/schedule.yaml       when each job runs
tests/                     pytest tests
docker/postgres/init.sql   enables pgvector when the database is created
docs/build-log/            what each step added and how to check it
```

Not investment advice. This is a personal research tool.
