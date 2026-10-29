@echo off
rem Starts Stock News Analyzer (database, dashboard and scheduler) in Docker and opens the
rem dashboard. Double-click this file. It opens Docker Desktop first if it isn't running,
rem and waits for the database.
cd /d "%~dp0"

docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  echo Opening Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
) else (
  echo Docker Desktop isn't installed. Install it from https://www.docker.com, then try again.
  pause
  exit /b 1
)
rem Docker Desktop takes up to a minute or two to start.
for /l %%i in (1,1,90) do (
  docker info >nul 2>&1 && goto docker_ready
  timeout /t 2 /nobreak >nul
)
echo Docker didn't start within 3 minutes. Open Docker Desktop, wait until it says it is
echo running, then try again.
pause
exit /b 1
:docker_ready

echo Starting Stock News Analyzer. The first time, getting the app ready takes a few minutes...
docker compose up -d
if errorlevel 1 (
  echo Something went wrong ^(see above^).
  pause
  exit /b 1
)

echo Waiting for the database...
for /l %%i in (1,1,30) do (
  docker compose exec -T db pg_isready -U sna -q >nul 2>&1 && goto db_ready
  timeout /t 2 /nobreak >nul
)
echo The database didn't start. See: docker compose logs db
pause
exit /b 1
:db_ready

echo Waiting for the dashboard...
for /l %%i in (1,1,90) do (
  curl -fsS http://localhost:8501/_stcore/health >nul 2>&1 && goto ready
  timeout /t 2 /nobreak >nul
)
echo The dashboard didn't start. See: docker compose logs ui
pause
exit /b 1
:ready
start "" http://localhost:8501
echo.
echo Stock News Analyzer is running at http://localhost:8501
echo You can close this window: it keeps running while Docker Desktop is open.
echo To stop it, double-click stop.bat.
pause
