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

# A git checkout (a developer's copy, kept up to date with git pull) runs its own code: the
# app is built from this folder, not downloaded, unless .env chooses with SNA_PULL_POLICY.
# The published image only changes with a release, so it can be older than the code here.
if [ -z "${SNA_PULL_POLICY:-}" ] && [ -d .git ] && ! grep -qs '^SNA_PULL_POLICY=' .env; then
  export SNA_PULL_POLICY=build
  echo "Starting the dashboard and the scheduler, built from this folder's code (a few minutes the first time)..."
else
  echo "Starting the dashboard and the scheduler. The first time, downloading the app takes a few minutes..."
fi
# The newest prebuilt image (or a build, as above or if .env says SNA_PULL_POLICY=build); if
# that fails, the image already here; if there is none, a build from this folder's code.
if ! docker compose up -d; then
  if [ "${SNA_PULL_POLICY:-}" = build ]; then
    echo "The build didn't work; trying the version already on this computer..."
  else
    echo "Couldn't download the newest version; trying the one already on this computer..."
  fi
  if ! SNA_PULL_POLICY=missing docker compose up -d; then
    echo "Building the app from this folder instead (a few minutes)..."
    SNA_PULL_POLICY=build docker compose up -d || fail "The dashboard and scheduler didn't start (see above). The database is running, so uv run sna commands still work."
  fi
fi

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
