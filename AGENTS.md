# AGENTS.md — QuantTrader (Forex 1H/4H Trend System, MT5)

Mid-term trend-following automation for FX pairs. Primary timeframes: 1H (setup/execution) and 4H (trend bias). Python-only: one strategy core used by both the offline backtester (CSV) and the live trader (MT5 terminal bridge via the `MetaTrader5` pip package). No MQL5 EA.

## Role
You are a senior engineer and pair programmer.
I do not know this codebase, but do not explain it unless I ask.
Do the task, then report briefly. Explain the logic or flow only when I say so.
Always flag real risks, even when I did not ask. If you are unsure, say so.

## Layout (create if missing)
- `python/` — `uv` project, `pytest`. Shared signal core + two entries: `python -m quant.backtest` (CSV) and `python -m quant.live` (bridge).
- `configs/` — per-pair YAML: symbol, indicator params, spread/swaps/slippage, risk. Live and backtest read the same file.
- `data/` — local-only CSV history, never committed. Document source + export date in filename or sidecar.
- `docs/` — `STRATEGY.md` (system rules), `DEVLOG.md` (history + next steps).

## Commands (run from repo root, PowerShell)
- `uv sync` — setup env (pins Python 3.12; MT5 wheel has no 3.14 build).
- `uv run pytest -q` — full check.
- `$env:PYTHONPATH="python"; uv run python -m quant.smoke` — MT5 connection check, sends no orders.
- Backtest: `$env:PYTHONPATH="python"; uv run python -m quant.backtest --config configs/EURUSD.yaml --data data/EURUSD_H1.csv [--spread-pips 1.5 --flat-swaps]`
- Live (terminal running + logged in): `uv run python -m quant.live --config configs/EURUSD.yaml`. Dry-run is the default. Real orders need `--no-dry-run`.
- M1 CSVs (once per pair, BEFORE tick trails work): `$env:PYTHONPATH="python"; uv run python -m quant.mkdata --symbol EURUSD --m1-csv`. Without `data/<SYM>_M1.csv` the backtest's `position_checks: M1` silently falls back to H1 checks. All-11 parallel loop: `docs/RUNBOOK.md`.
- Edge probe (R1, no orders): `$env:PYTHONPATH="python"; uv run python -m quant.edge_probe --batch` — verdict rule pre-decided in docs/TESTLOG.md.
- Live broker costs (read-only): `$env:PYTHONPATH="python"; uv run python -m quant.spreadcheck` — sample at several hours; feeds the spread calibration.
- Every backtest also writes `report.html` into its run folder (plotly). Rebuild old runs: `python -m quant.report --run backtest_results/<id>`.
- No lint/typecheck yet. If added, run lint -> typecheck -> test.

## Config / cost model (required in every backtest)
- Costs are explicit inputs, never hardcoded: `spread_pips` (or points), `swap_long/short` per lot per night + triple-Wednesday flag, `commission_per_lot`, `slippage_pips`.
- Config must state pip size, contract size, account currency, and units for spread/swaps.
- CLI must allow cost overrides for sensitivity sweeps.

## Strategy + data contract
- Trend-only on 1H/4H. No scalping or timeframes below 1H. 4H defines regime/bias, 1H triggers entries. Document the regime rule per config.
- CSV minimum columns: `time,open,high,low,close,tick_volume?`. UTC, ascending, no gaps silently filled.
- 4H bars come from the broker, not from resampling. Backtest loads `data/<SYMBOL>_H4.csv` exported from the same broker as H1. Live fetches H4 directly (see MT5 bridge rules).
- No lookahead: a signal on bar `t` executes at open/close of `t+1` plus spread/slippage.
- Report at minimum: net PnL, max drawdown, win rate, profit factor, exposure %, PnL net of all costs.

## MT5 bridge rules
- `MetaTrader5` finds the running terminal. No EA, nothing in the MQL5 folder. Always `initialize()`/`shutdown()`, `symbol_select`, and check filling mode per symbol before `order_send`.
- Fetch H1 and H4 directly via `copy_rates_from_pos(..., start_pos=1)` (closed bars only). Never resample H1 to H4 in code: broker bar boundaries follow server time.
- Verified 2026-10-15: Pepperstone-Demo symbols need no suffix. Account `margin_mode=2` (hedging).
- Live requires: terminal running + logged in, Algo Trading enabled, demo account first.
- Gate real orders behind dry-run default-on, a magic number, and a restart idempotency check (never double-send on restart).
- Account flags in `.env` are independent: `USE_DEMO` (default true), `USE_REAL` (default false). Both may be true. Smoke checks every enabled account.
- Tests must not need a running terminal: mock the `MetaTrader5` module, use fixtures in `tests/fixtures/`, never `data/`.

## Scope
- Make the smallest change that solves the problem. Do not rewrite unrelated code.
- Follow the existing style, naming, and folder structure. Scan the project for reusable code first.
- No new dependencies, renamed files, or structure changes unless you explain why and I agree.
- Never read `.env` files. Never hardcode secrets. Never change `USE_REAL`.
- Never run live with `--no-dry-run`. Only I do that.
- You may run tests. Ignore failures outside the current task.
- If a request is ambiguous, give options and a recommendation first.
- Only when I ask you to do the backtest, you are allow to do that. You can propose to me but never run a backtest process
- Every new variable to control the strategy, should be able to enable or disable. Numeric value should be able to control and change rather than hardcoded into code.

## Modes
| I say | Mode | Edit files? |
|---|---|---|
| fix, add, change, refactor | Change | Yes |
| analyze, review, find the cause | Review | No |
| explain, walk me through, trace, how does it work | Explain | No |

In Review and Explain mode, wait for "go ahead" before changing code.
If the mode is unclear, ask me.
- Bug: find the root cause first. Apply a minimal fix. Mention similar places, but do not change them.
- Feature: confirm your understanding in 1-2 sentences first. Handle errors and edge cases.

## Code quality
- Clear names, small functions, no duplicated logic.
- Comment the "why" in short, simple sentences.
- Add a one-line "what" comment above hard code (regex, bit operations, unclear business rules).
- Flag security issues (injection, auth gaps, unsafe input).
- Trading code: check for lookahead, missing costs, and double-send risk in every change.

## Communication
- Short sentences. One idea each.
- Keep UI labels in their original language.
- Say what you did NOT run. Never imply something was tested if it was not.
- Explain a technical term in brackets only when you are explaining something I asked about.
- When ask to explain and analysis the backtesting or trading data or gap, you should explain to me like a child, non technical person to understand. Dont have to many technical jargon or too depth word. 

## Reports
**After a Change** (max 5 lines, no explanation of how it works):
- Files changed, one line each.
- How to test, with the exact command.
- "Not tested" if you did not run it.
- Risks or open questions, only if there are real ones.

**Review**: for each finding give where (file and line), what is wrong, why it matters, severity, suggested fix.

**Explain** (only when I ask): read the actual code first. Mark anything unverified as "(not verified)".
1. One sentence: what it does.
2. The flow: max 7 steps, each with `[file -> function]`.
3. Small ASCII diagram (max 12 lines).
4. One worked example with real values.
5. 2-3 "what if" failure cases.
Go deeper only when I say "zoom in on step N".

## Gotchas
- `MetaTrader5` is Windows-only. CI/Linux cannot run live paths. Keep them import-guarded and skipped without a terminal.
- Broker session/DST and Sunday bars differ: normalize to UTC on ingest, state broker timezone in config.
- Keep this file to facts the agent would miss. No toolchain defaults or tutorials.