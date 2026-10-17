# Runbook — commands you can run manually (PowerShell, from repo root)

Terminal must be open and logged in for anything that reads MT5.
Monitor and smoke send no orders.

## First time

```powershell
uv sync
```

## Connection check (no orders)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.smoke
```

## Bias panel — one snapshot, then exit

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor --once
```

## Bias panel — live loop (repaints only on a new H1 close)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor
```

Or double-click `start-panel.bat`. Stop with Ctrl+C or by closing the window.
Each cycle covers every enabled account (`USE_DEMO`/`USE_REAL`, demo+real at
once); the header shows `DEMO`, `REAL`, or `DEMO+REAL`.

Faster polling (still repaints only on a new H1 close):

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor --interval 30
```

`NONE DETECTED` means every readable pair is FLAT on H4. `DATA ERROR`
names pairs that could not be read. The panel shows bias only;
entries are not defined yet.

FLAT means no trade bias: the last completed H4 bar failed at least one of
EMA20/50 stack, HR1a close-vs-EMA50, or separation >= 0.3 x ATR14.

## Closed-position records (demo + real)

Each loop cycle appends newly closed positions of `--magic` (default 100001)
to `trades/demo.csv` and `trades/real.csv`:
```text
local_time,broker_open,broker_close,symbol,side,volume,entry_price,close_price,profit,commission,swap,magic,ticket,entry_condition,account
```

Closed positions only (open ones appear when they close). `entry_condition`
comes from `trades/journal.csv` matched on ticket, blank if unknown.
Restart-safe: only tickets above the file's max are appended; manual trades
(other magic numbers) are ignored. Real account is read with history calls
only — the panel can never send orders.

Sample screen:

```text
QuantTrader H4 bias panel (H4 B1, bias only)
local time : 2026-10-16 18:05:12 (Malaysia, UTC+8)
broker time: 2026-10-16 10:00:00 (last H1 close, UTC)
account=DEMO  rule=repaint-on-new-H1-close-only
week DEMO: -2.10% (halt at -15%)

SYMBOL   BIAS ENTRY
EURUSD   UP   GO
USDJPY   FLAT -
```

ENTRY is `GO` or the first failing section-5 rule (`HR2`, `HR3`, `HR4`,
`HR4-guard`, `EXT`, `E1-setup`, `E1-trigger`, `warmup`); `-` when FLAT.

## Weekly loss halt

- `.env`: `WEEKLY_LOSS_PCT=15` — halt new entries once this UTC week's
  realized loss (our magic only) reaches 15% of week-start equity.
- State lives in `memory/weekly_demo.json` + `memory/weekly_real.json`
  (gitignored, per account). A new week snapshots fresh equity and clears halt.
- The panel shows a `week <ACCT>: %` line always and a `HALTED` banner when
  tripped. Halt gates the future live executor; panel and records keep running.
- Week = UTC Monday 00:00 for now (spec 8A says broker-server week; that needs
  a broker GMT-offset setting we don't have yet).

## ATR separation switch

Three places, top one wins:

1. `.env`: `USE_ATR_SEP=false` — flips every pair on this machine.
   Unset (default) = YAML decides. Add the line yourself; `.env` is never committed.
2. `configs/_base.yaml`: `strategy: {use_atr_sep: ...}` — global default, currently `true`.
3. Per-pair file, e.g. `configs/EURUSD.yaml`: `strategy: {use_atr_sep: false}` — overrides the base.

`false` = MA-only: UP if EMA20 >= EMA50 else DOWN, no HR1, no FLAT
(except warmup). Panel title shows `MA-only`, or `MA-only (env)` when the
`.env` override is active.

## Tests

```powershell
$env:PYTHONPATH="python"; uv run pytest -q
```

## Round-trip plumbing test (opens + closes a real 0.01)

`quant.live --roundtrip` is the only command that can send orders, and only
with `--no-dry-run`. Steps, in this order:

1. Terminal open, logged in. In `.env`, enable **exactly one** account
   (demo for this test — the command refuses to run if both are on).
2. Dry run first (sends nothing, plans only):
```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --roundtrip
```
3. Only you, only on demo — opens 0.01 and closes it seconds later:
```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --roundtrip --no-dry-run
```
4. Confirm: `trades/journal.csv` gains `roundtrip-open` + `roundtrip-close`
   rows; next panel cycle appends the closed position to `trades/demo.csv`.
   If CLOSE ever fails, the console prints the position id — close it by hand.

No signal entries exist yet: without `--roundtrip` the command does nothing.

## SL/TP touch test (broker closes the trade)

`--touch-close` opens 0.01 with close SL+TP attached; first touch wins:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --touch-close
```

Dry run first (prints planned SL/TP, sends nothing). Real run (add
`--no-dry-run`, exactly one account enabled) waits up to `--timeout` seconds
(default 180) for the broker to close it, then reports `via TP` or `via SL`.
`--distance-points` sets the bracket width (default 10 points ≈ $0.10);
distances below the broker `stops_level` are clamped up and reported.
No touch in time → market-closes like roundtrip and says so. Same manual-close
warning applies if anything fails mid-flight.

## Backtest batch (offline, no terminal needed)

Build H1 once per symbol from the M1 files (plain CSV or HistData zips;
coverage report included). Add `--m1-csv` the first time (writes
`data/<SYM>_M1.csv`, ~200 MB per pair, gitignored): the backtest needs it for
tick-like position checks, and every hour without M1 rows falls back to H1
checks for that bar.

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --symbol EURUSD --m1-csv
```

Build all 11 in parallel (same single-symbol command per job; ~1 GB peak RAM per
job; builds also rewrite H1 byte-identical, audit-verified):

```powershell
foreach ($s in "EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","EURGBP","EURJPY","GBPJPY","AUDJPY") {
  Start-Job -Name "mk_$s" -ScriptBlock {
    param($sym)
    Set-Location "C:\Users\SCSM11\Desktop\Dev Folder\FullStack\Project\QuantTrader"
    $env:PYTHONPATH = "python"; uv run python -m quant.mkdata --symbol $sym --m1-csv
  } -ArgumentList $s | Out-Null
}
Get-Job -Name "mk_*" | Wait-Job | Out-Null
Get-Job -Name "mk_*" | Where-Object State -ne "Completed"   # anything here: rerun singly
Get-Job -Name "mk_*" | Sort-Object Name | Receive-Job -Keep
Get-Job -Name "mk_*" | Remove-Job
(Get-ChildItem data\*_M1.csv).Count                          # expect 11
```

Run the batch (double-click `run-backtest.bat` does the same). Tick pairs on/off
in `configs/scan-selection.yml`. Results land in `backtest_results/<local-time>/`:
`summary.csv`, `funnel.csv` (survivors per rule, spec section 2 order),
`trades_<SYM>.csv`, `params.json` (effective settings for reproducibility).
Enabled pairs without `data/<SYM>_H1.csv` print `SKIP` and the batch continues.
`configs/_base.yaml` `limits.no_trade_ranges` lists recurring no-trade windows
(default: `12-15` to `01-01`); entries whose fill day falls inside are skipped
(funnel `window` column) and open positions keep their stop/trail.

Sweeps (one factor at a time):

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --atr-n 14
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --sep-atr 0.0
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --ma-only
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --spread-pips 3.0
```

Gate toggles (ablation, spec 11.4): `use_hr2/hr3/hr4/ext/e1_setup/e1_trigger`
in `_base.yaml` (all default true; false = gate auto-passes, own funnel effect).
Size is fixed `--lot` (default 0.01); `--lot 0` sizes from `--risk-usd` instead.
R always divides by actual risk. Pip math reference: `docs/PIP_VALUES.md`
(1 pip = 10 points; 300 points = 30 pips = $3.00 at 0.01 on EURUSD).

Single pair: `--config configs/EURUSD.yaml --data data/EURUSD_H1.csv`.
Known deviations (strategy testing only, not go-live calibration): H4 blocks
anchor at 00:00 UTC, spread fixed 20 points, 5/3-digit tick math, UTC weeks.
Quote-foreign pairs size through converter feeds auto-loaded from `data/`
(JPY via USDJPY, GBP via GBPUSD, ...); SKIP with notice when absent.

## Not built yet

`quant.live` signal entries (only `--roundtrip` / `--touch-close` exist).
Journal rows (`trades/journal.csv`) appear on fills.
