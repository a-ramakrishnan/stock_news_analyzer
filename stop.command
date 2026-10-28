#!/bin/bash
# Stops Stock News Analyzer. Your data is kept; start.command starts it again.
cd "$(dirname "$0")" || exit 1
docker compose stop && echo "Stopped. Your data is kept."
read -r -p "Press Enter to close. " _
