@echo off
REM Trader: SAME panel plus the trading loop (--trade). Launch this bat and the
REM system trades; close it and nothing trades. Dry-run by default (plans +
REM journal rows only, nothing is sent).
REM When YOU trust it, add --no-dry-run to the line below (one enabled demo
REM account in .env required; never on live without your own explicit action).
REM Stop with Ctrl+C or by closing this window.
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.monitor --trade %*
pause
