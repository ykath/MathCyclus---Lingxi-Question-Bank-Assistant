@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m streamlit run mathex_app.py --server.headless true
