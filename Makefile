.PHONY: setup up down health test lint format docker-health

setup:          ## Install Python dependencies and create .env
	uv sync
	@test -f .env || cp .env.example .env

up:             ## Start Postgres + pgvector in Docker
	docker compose up -d db

down:           ## Stop Docker services (data is kept)
	docker compose down

health:         ## Check config, data folder and database from the laptop
	uv run sna health

docker-health:  ## Run the same check inside the app container
	docker compose run --rm --build app

test:           ## Run tests (database tests are skipped if Postgres is not running)
	uv run pytest

lint:           ## Check style
	uv run ruff check .
	uv run ruff format --check .

format:         ## Fix style
	uv run ruff check --fix .
	uv run ruff format .
