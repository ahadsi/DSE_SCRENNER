@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" selftest.py
pause
