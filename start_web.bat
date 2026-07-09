@echo off
cd /d %~dp0
python -m uvicorn web_app:app --port 8010
pause
