@echo off
REM REAL-MONEY orders ON. USE_REAL must already be enabled; this file never enables it.
REM Never run another trader/panel on this terminal. Verify demo execution first.
REM Pass --dry-run to plan only. Stop with Ctrl+C or close this window.
cd /d "%~dp0"
set PYTHONPATH=python
echo WARNING: This launcher places REAL-MONEY orders when USE_REAL is enabled.
uv run python -m quant.monitor --trade --no-dry-run %* --account real --journal trades/real_journal.csv
set "TRADER_EXIT=%ERRORLEVEL%"
pause
exit /b %TRADER_EXIT%
