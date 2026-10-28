@echo off
rem Stops Stock News Analyzer. Your data is kept; start.bat starts it again.
cd /d "%~dp0"
docker compose stop
echo Stopped. Your data is kept.
pause
