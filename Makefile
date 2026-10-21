.PHONY: setup up down health migrate securities watchlist filings news prices test lint format docker-health

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

prices:         ## Load new NSE prices, update moves and labels
	uv run sna prices fetch
	uv run sna labels update

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
