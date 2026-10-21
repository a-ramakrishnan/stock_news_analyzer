# Step 1: Project skeleton

**Goal:** a runnable, tested base that every agent will build on. No agents yet.

## What was added

| Piece | Why |
| --- | --- |
| Python package `stock_news_analyzer` managed with `uv` | One place for all agents; `uv.lock` pins exact versions |
| `docker-compose.yml` with Postgres 16 + pgvector | The shared database every agent reads from and writes to; pgvector for searching transcripts later |
| `config.py` (pydantic-settings) and `.env.example` | Settings come from the environment; secrets stay out of git |
| `sna health` command | One command to confirm config, data folder and database all work |
| `Dockerfile` | The same code can run in a container, ready for a server later |
| Tests + GitHub Actions CI | Every pull request runs lint and tests against a real Postgres |
| `Makefile` | Short commands: `make setup`, `make up`, `make health`, `make test` |

## Decisions

- **Postgres on port 5433** on the laptop, so it doesn't clash with any Postgres already installed.
- **All times in IST** (`Asia/Kolkata`), because filings and market hours are Indian.
- **Database tests skip** when Postgres isn't running, so `make test` always works; CI always runs them.

## How to check it

```bash
make setup && make up && make health && make test
```

Expected: four `ok` lines from `make health`, and all tests passing.

## Starter watchlist (used from step 2)

1. Larsen & Toubro
2. Karur Vysya Bank
3. Motherson Sumi Wiring

## Tweet draft

> Day 1 of building an AI research desk for Indian stocks: news, filings and concalls, not charts. Step 1 is the boring part: Python + Postgres/pgvector in Docker, config, a health check and CI. One command says everything is wired up. Agents start next. #BuildInPublic
