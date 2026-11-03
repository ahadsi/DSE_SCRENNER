@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" db_tools.py check
pause
