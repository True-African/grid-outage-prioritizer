@echo off
cd /d "%~dp0"
set MPLBACKEND=Agg
echo Starting KTT Power Dashboard...
echo.
echo If this is the first run, dependencies may install now.
python -m pip install -r requirements.txt
echo.
echo Opening http://127.0.0.1:8000
start "" "http://127.0.0.1:8000"
python dashboard.py --port 8000
pause
