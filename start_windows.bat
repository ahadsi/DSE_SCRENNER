@echo off
cd /d "%~dp0"
title DSE Smart Scanner - Live
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
 echo Package installation failed. Check internet/error above.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" run_live.py
pause
