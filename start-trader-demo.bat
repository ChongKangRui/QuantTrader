@echo off
REM Demo orders ON. Runs the selected strategy, not just the read-only panel.
REM USE_DEMO must already be enabled. Never run another trader/panel on this terminal.
REM Pass --dry-run to plan only. Stop with Ctrl+C or close this window.
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.monitor --trade --no-dry-run %* --account demo --journal trades/demo_journal.csv
set "TRADER_EXIT=%ERRORLEVEL%"
pause
exit /b %TRADER_EXIT%
