@echo off
REM Backtest batch: loops scan-selection.yml, results land in results\<local-time>\.
REM Disabled pairs print one line; pairs without data print SKIP and continue.
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.backtest --batch %*
pause
