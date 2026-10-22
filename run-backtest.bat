@echo off
REM Backtest batch: loops scan-selection.yml, results land in backtest_results\<local-time>\.
REM Data source follows configs/_base.yaml backtest_data (broker H4/D1 by default).
REM Disabled pairs stay excluded; missing enabled broker files fail instead of mixing vendor data.
REM Pairs run in parallel (default 10 at once). Extra args pass through, e.g. run-backtest.bat --jobs 4
REM (--jobs 1 = one pair at a time, --jobs 0 = one worker per CPU core).
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.backtest --batch %*
pause
