@echo off
rem Double-click to open the crypto dashboard using local data. Sync GitHub separately.
cd /d "%~dp0"
start "" http://localhost:8501
python -m streamlit run dashboard/app.py --server.headless true --server.port 8501
