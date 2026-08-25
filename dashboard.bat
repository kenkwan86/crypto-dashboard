@echo off
rem Double-click to open the crypto dashboard. Pulls the latest collected data first.
cd /d "C:\01. Coding\Crypto-Dashboard"
git pull --rebase origin main
start "" http://localhost:8501
python -m streamlit run dashboard/app.py --server.headless true --server.port 8501
