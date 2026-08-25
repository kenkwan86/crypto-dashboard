@echo off
rem Double-click to generate a fresh Claude market briefing (uses your Max plan).
cd /d "C:\01. Coding\Crypto-Dashboard"
git pull --rebase origin main
python -m briefing.generate
start "" "briefing\reports"
pause
