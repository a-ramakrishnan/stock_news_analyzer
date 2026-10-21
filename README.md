# Stock News Analyzer

A set of small agents that track news, exchange filings and earnings calls for Indian stocks and bullion. They explain why stocks move, track order wins and management promises, and build a point-in-time database that can train a model later. No technical analysis: prices are only used to measure what each piece of news did to a stock.

- Design doc: [Indian Market News Intelligence System](https://claude.ai/artifact/2rcGGrRLaCoqDkBeg2nwxJ) (architecture, data sources, agent-by-agent plan)
- Build log, one file per step: [`docs/build-log/`](docs/build-log/)

## Status

| Step | What | Status |
| --- | --- | --- |
| 1 | Project skeleton: Python package, Postgres + pgvector in Docker, config, health check, CI | done |
| 2 | Database tables + Watchlist Manager agent | done |
| 3 | Filings Collector (BSE + NSE announcements) | this PR |
| 4 | News Collector (RSS) | planned |
| 5 | Price & Label (NSE bhavcopy) | planned |
| 6 | Orchestrator + first daily digest | planned |

## Run it on a Mac

You need [Homebrew](https://brew.sh), then:

```bash
brew install uv                       # Python package manager (installs Python for you)
brew install --cask docker            # Docker Desktop; open it once so it starts
git clone https://github.com/a-ramakrishnan/stock_news_analyzer.git
cd stock_news_analyzer

make setup    # install dependencies, create .env from .env.example
make up       # start Postgres + pgvector in Docker (port 5433)
make health   # check everything is connected
```

`make health` should print:

```
data dir     ok  /…/stock_news_analyzer/data
timezone     ok  Asia/Kolkata
postgres     ok  16.x
pgvector     ok  0.8.x
```

Then set up your watchlist (edit [`config/watchlist.yaml`](config/watchlist.yaml) first):

```bash
make migrate      # create the database tables
make securities   # download the NSE + BSE lists of listed companies
make watchlist    # load config/watchlist.yaml and show it
```

If NSE blocks the download, open the link it prints in a browser, save the file, and run
`uv run sna securities refresh --nse-file ~/Downloads/EQUITY_L.csv`.

Watchlist commands:

| Command | What it does |
| --- | --- |
| `uv run sna watchlist add "Karur Vysya Bank" --owned` | Add or update a stock by name, NSE symbol, BSE code or ISIN |
| `uv run sna watchlist add gold` | Track bullion (gold or silver) |
| `uv run sna watchlist list` | Show the watchlist with NSE/BSE codes and industry |
| `uv run sna watchlist remove LT` | Stop tracking |
| `uv run sna watchlist peers LT` | Suggest same-industry peers; save with `--approve SYMBOL` |

Filings (exchange announcements) for every company on the watchlist:

```bash
make filings                                        # new filings since the last run (first run: last 7 days)
uv run sna filings backfill --since 2023-10-01      # one-off history; PDFs only for important filings
uv run sna filings list LT                          # latest filings for one company
uv run sna filings list --type order_win            # filter by type: results, concall_transcript, credit_rating, ...
uv run sna filings show 42                          # details + extracted text of filing 42
uv run sna filings attachments --pdf all            # download PDFs skipped earlier
uv run sna filings attachments --retry-failed       # re-download PDFs that failed to read
uv run sna filings reclassify                       # re-apply filing-type rules to stored filings
```

PDFs are saved under `data/filings/<ISIN>/<bse|nse>/<YYYY-MM>/` and their text is stored in the database.

Other commands:

| Command | What it does |
| --- | --- |
| `make test` | Run the tests in a separate `sna_test` database (skipped if Postgres is not running) |
| `make lint` / `make format` | Check or fix code style |
| `make docker-health` | Run the health check inside the app's Docker container |
| `make down` | Stop Docker (your data is kept in a Docker volume) |

## Layout

```
src/stock_news_analyzer/   Python package (agents will live here)
  config.py                settings from environment / .env
  db.py                    database connection, migrations, health check
  models.py                database tables
  migrations/              Alembic migrations (one per schema change)
  sources/securities.py    NSE/BSE security list download + parsing
  sources/exchange_http.py BSE/NSE web access (browser-like, gets past bot protection)
  sources/announcements.py BSE/NSE announcement parsing + filing types
  agents/watchlist.py      Watchlist Manager (agent 1)
  agents/filings.py        Filings Collector (agent 2)
  cli.py                   `sna` command-line tool
config/watchlist.yaml      your stocks and bullion
tests/                     pytest tests
docker/postgres/init.sql   enables pgvector when the database is created
docs/build-log/            what each step added and how to check it
```

Not investment advice. This is a personal research tool.
