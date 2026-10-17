@echo off
REM Backtest batch: loops scan-selection.yml, results land in backtest_results\<local-time>\.
REM Disabled pairs print one line; pairs without data print SKIP and continue.
REM Pairs run in parallel (default 10 at once). Extra args pass through, e.g. run-backtest.bat --jobs 4
REM (--jobs 1 = one pair at a time, --jobs 0 = one worker per CPU core).
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.backtest --batch %*
pause
