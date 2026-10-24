@echo off
setlocal
REM Frozen four-pair evaluation: 2019 preparation only, results scored over 2020-2025.
REM Use the isolated selection; never change configs\scan-selection.yml for this run.
REM No argument forwarding: overrides would change the frozen experiment.
cd /d "%~dp0"
set "PYTHONPATH=python"
set "EVAL_CONFIG=data\four_pair_evaluation_20261024\configs"
for %%F in (_base.yaml scan-selection.yml EURAUD.yaml GBPCAD.yaml AUDCAD.yaml CADJPY.yaml) do (
    if not exist "%EVAL_CONFIG%\%%F" (
        echo ERROR: Missing isolated evaluation file: %EVAL_CONFIG%\%%F
        echo No backtest started. Restore the prepared local profile first.
        pause
        exit /b 1
    )
)
uv run python -m quant.backtest --batch --config-dir "%EVAL_CONFIG%" --results-dir "backtest_results\four_pair_evaluation_20261024"
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
