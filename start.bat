@echo off
rem Starts Stock News Analyzer (database, dashboard and scheduler) in Docker and opens the
rem dashboard. Double-click this file.
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker is not running. Open Docker Desktop, wait until it says it is running,
  echo then try again.
  pause
  exit /b 1
)

echo Starting Stock News Analyzer. The first time, getting the app ready takes a few minutes...
docker compose up -d
if errorlevel 1 (
  echo Something went wrong ^(see above^).
  pause
  exit /b 1
)

echo Waiting for the dashboard...
for /l %%i in (1,1,90) do (
  curl -fsS http://localhost:8501/_stcore/health >nul 2>&1 && goto ready
  timeout /t 2 /nobreak >nul
)
:ready
start "" http://localhost:8501
echo.
echo Stock News Analyzer is running at http://localhost:8501
echo You can close this window: it keeps running while Docker Desktop is open.
echo To stop it, double-click stop.bat.
pause
