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

rem The database first and on its own: "docker compose up" builds the app image before it
rem starts any container, so a slow or failed build would otherwise leave Postgres stopped.
echo Starting the database...
docker compose up -d db
if errorlevel 1 (
  echo The database didn't start ^(see above^).
  pause
  exit /b 1
)
for /l %%i in (1,1,30) do (
  docker compose exec -T db pg_isready -U sna -q >nul 2>&1 && goto db_ready
  timeout /t 2 /nobreak >nul
)
echo The database didn't start. See: docker compose logs db
pause
exit /b 1
:db_ready
echo The database is ready.

rem A git checkout (a developer's copy, kept up to date with git pull) runs its own code: the
rem app is built from this folder, not downloaded, unless .env chooses with SNA_PULL_POLICY.
rem The published image only changes with a release, so it can be older than the code here.
if not defined SNA_PULL_POLICY if exist .git (
  findstr /b "SNA_PULL_POLICY=" .env >nul 2>&1 || set SNA_PULL_POLICY=build
)
if "%SNA_PULL_POLICY%"=="build" (
  echo Starting the dashboard and the scheduler, built from this folder's code ^(a few minutes the first time^)...
) else (
  echo Starting the dashboard and the scheduler. The first time, downloading the app takes a few minutes...
)
rem The newest prebuilt image (or a build, as above); if that fails, the image already here;
rem if none, a build.
docker compose up -d
if not errorlevel 1 goto app_started
if "%SNA_PULL_POLICY%"=="build" (
  echo The build didn't work; trying the version already on this computer...
) else (
  echo Couldn't download the newest version; trying the one already on this computer...
)
set SNA_PULL_POLICY=missing
docker compose up -d
if not errorlevel 1 goto app_started
echo Building the app from this folder instead ^(a few minutes^)...
set SNA_PULL_POLICY=build
docker compose up -d
if errorlevel 1 (
  echo The dashboard and scheduler didn't start ^(see above^). The database is running.
  pause
  exit /b 1
)
:app_started

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
