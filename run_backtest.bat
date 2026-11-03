@echo off
cd /d %~dp0
call .venv\Scripts\activate
python backtest_action_engine.py --days 365
pause
