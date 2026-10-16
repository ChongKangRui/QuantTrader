@echo off
REM Bias panel loop: console only, repaint on new H1 close. Sends no orders.
REM Stop with Ctrl+C or by closing this window.
cd /d "%~dp0"
set PYTHONPATH=python
uv run python -m quant.monitor %*
pause
