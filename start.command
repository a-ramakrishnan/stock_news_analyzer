#!/bin/bash
# Starts Stock News Analyzer (database, dashboard and scheduler) in Docker and opens the
# dashboard. On a Mac, double-click this file; elsewhere run ./start.command.
cd "$(dirname "$0")" || exit 1

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Open Docker Desktop, wait until it says it is running,"
  echo "then try again."
  read -r -p "Press Enter to close. " _
  exit 1
fi

echo "Starting Stock News Analyzer. The first time, building the app takes a few minutes..."
if ! docker compose up -d --build; then
  echo "Something went wrong (see above)."
  read -r -p "Press Enter to close. " _
  exit 1
fi

echo "Waiting for the dashboard..."
for _ in $(seq 90); do
  curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1 && break
  sleep 2
done
open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null
echo
echo "Stock News Analyzer is running at http://localhost:8501"
echo "You can close this window: it keeps running while Docker Desktop is open."
echo "To stop it, double-click stop.command."
