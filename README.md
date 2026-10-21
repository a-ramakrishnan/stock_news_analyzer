# Stock News Analyzer

A set of small agents that track news, exchange filings and earnings calls for Indian stocks and bullion. They explain why stocks move, track order wins and management promises, and build a point-in-time database that can train a model later. No technical analysis: prices are only used to measure what each piece of news did to a stock.

- Design doc: [Indian Market News Intelligence System](https://claude.ai/artifact/2rcGGrRLaCoqDkBeg2nwxJ) (architecture, data sources, agent-by-agent plan)
- Build log, one file per step: [`docs/build-log/`](docs/build-log/)

## Status

| Step | What | Status |
| --- | --- | --- |
| 1 | Project skeleton: Python package, Postgres + pgvector in Docker, config, health check, CI | this PR |
| 2 | Database tables + Watchlist Manager agent | next |
| 3 | Filings Collector (BSE) | planned |
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

Other commands:

| Command | What it does |
| --- | --- |
| `make test` | Run the tests (database tests skip if Postgres is not running) |
| `make lint` / `make format` | Check or fix code style |
| `make docker-health` | Run the health check inside the app's Docker container |
| `make down` | Stop Docker (your data is kept in a Docker volume) |

## Layout

```
src/stock_news_analyzer/   Python package (agents will live here)
  config.py                settings from environment / .env
  db.py                    database connection and health check
  cli.py                   `sna` command-line tool
tests/                     pytest tests
docker/postgres/init.sql   enables pgvector when the database is created
docs/build-log/            what each step added and how to check it
```

Not investment advice. This is a personal research tool.
