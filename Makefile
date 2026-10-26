.PHONY: setup up down health migrate securities watchlist filings news triage explain concalls promises orders prices digest backfill run-all scheduler scheduler-logs scheduler-stop ui ui-docker ui-stop test lint format docker-health

setup:          ## Install Python dependencies and create .env
	uv sync
	@test -f .env || cp .env.example .env

up:             ## Start Postgres + pgvector in Docker
	docker compose up -d db

down:           ## Stop Docker services (data is kept)
	docker compose down

health:         ## Check config, data folder and database from the laptop
	uv run sna health

migrate:        ## Create or update database tables
	uv run sna db upgrade

securities:     ## Download the NSE/BSE lists of listed companies
	uv run sna securities refresh

watchlist:      ## Load config/watchlist.yaml and show the watchlist
	uv run sna watchlist load
	uv run sna watchlist list

filings:        ## Fetch new BSE/NSE announcements for the watchlist
	uv run sna filings fetch

news:           ## Read news feeds + Google News for the watchlist
	uv run sna news fetch

triage:         ## LLM triage of new articles: relevance, topic, sentiment, importance
	uv run sna triage run

explain:        ## LLM explanation of unusual days not explained yet (up to yesterday)
	uv run sna explain run

concalls:       ## LLM reading of earnings call transcripts of stocks you own (last 400 days)
	uv run sna concalls run

orders:         ## LLM reading of order wins and order books, then the peer table
	uv run sna orders run
	uv run sna orders peers

promises:       ## LLM check of promises past their date, then credibility scores
	uv run sna promises check
	uv run sna promises scores

prices:         ## Load new NSE prices, update moves and labels
	uv run sna prices fetch
	uv run sna labels update

digest:         ## Print the digest (everything since the last scheduled digest)
	uv run sna digest

SINCE ?= 2023-10-01

# A part that reports errors does not stop the rest ("-"); re-run to retry what failed.
backfill:       ## Load history since SINCE (default 2023-10-01): prices, filings, news, deals, labels
	-uv run sna prices backfill --since $(SINCE)
	-uv run sna filings backfill --since $(SINCE)
	-uv run sna news backfill --since $(SINCE)
	-uv run sna deals backfill --since $(SINCE)
	uv run sna labels update

run-all:        ## Run every job once, now, in order (collect, judge, measure, report)
	uv run sna run all

scheduler:      ## Start the orchestrator in Docker (keeps running while Docker is up)
	docker compose --profile scheduler up -d --build scheduler

scheduler-logs: ## Follow the orchestrator's output
	docker compose logs -f scheduler

scheduler-stop: ## Stop the orchestrator
	docker compose stop scheduler

ui:             ## Open the dashboard at http://localhost:8501 (Ctrl+C to stop)
	uv run sna ui

ui-docker:      ## Run the dashboard in Docker instead, at http://localhost:8501
	docker compose --profile ui up -d --build ui

ui-stop:        ## Stop the Docker dashboard
	docker compose stop ui

docker-health:  ## Run the same check inside the app container
	docker compose run --rm --build app

test:           ## Run tests in a separate sna_test database (DB tests skip if Postgres is down)
	uv run pytest

lint:           ## Check style
	uv run ruff check .
	uv run ruff format --check .

format:         ## Fix style
	uv run ruff check --fix .
	uv run ruff format .
