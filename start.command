#!/bin/bash
# Starts Stock News Analyzer (database, dashboard and scheduler) in Docker and opens the
# dashboard. On a Mac, double-click this file, or run ./start.command or make start.
# It opens Docker Desktop first if it isn't running, and waits for the database.
cd "$(dirname "$0")" || exit 1

fail() {
  echo "$1"
  read -r -p "Press Enter to close. " _
  exit 1
}

if ! docker info >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ] && open -g -a Docker 2>/dev/null; then
    echo "Opening Docker Desktop..."
  elif ! command -v docker >/dev/null 2>&1; then
    fail "Docker isn't installed. Install Docker Desktop from https://www.docker.com, then try again."
  else
    echo "Waiting for Docker to start..."
  fi
  # Docker Desktop takes up to a minute or two to start.
  for _ in $(seq 90); do
    docker info >/dev/null 2>&1 && break
    sleep 2
  done
  docker info >/dev/null 2>&1 || fail "Docker didn't start within 3 minutes. Open Docker Desktop, wait until it says it is running, then try again."
  echo "Docker is running."
fi

# The database first and on its own: `docker compose up` builds the app image before it
# starts any container, so a slow or failed build would otherwise leave Postgres stopped.
echo "Starting the database..."
docker compose up -d db || fail "The database didn't start (see above)."
for _ in $(seq 30); do
  docker compose exec -T db pg_isready -U sna -q 2>/dev/null && break
  sleep 2
done
docker compose exec -T db pg_isready -U sna -q 2>/dev/null || fail "The database didn't start. See: docker compose logs db"
echo "The database is ready."

echo "Starting the dashboard and the scheduler. The first time, getting the app ready takes a few minutes..."
docker compose up -d || fail "The dashboard and scheduler didn't start (see above). The database is running, so uv run sna commands still work."

echo "Waiting for the dashboard..."
for _ in $(seq 90); do
  curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1 || fail "The dashboard didn't start. See: docker compose logs ui"
open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null
echo
echo "Stock News Analyzer is running at http://localhost:8501"
echo "The database is ready for uv run sna commands, and the scheduler is running."
echo "You can close this window: it keeps running while Docker Desktop is open."
echo "To stop it, double-click stop.command."
