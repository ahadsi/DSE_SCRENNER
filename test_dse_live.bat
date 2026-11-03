@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "from bdshare import get_current_trade_data; df=get_current_trade_data(); print('LIVE DSE OK:',len(df),'symbols'); print(df.head().to_string(index=False))"
pause
