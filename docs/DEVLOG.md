# Dev Log

## 2026-10-17 — v0.9: no-trade windows + tick-like position checks

- `limits.no_trade_ranges` in `_base.yaml`: recurring yearly arrays of `{start, end}` MM-DD
  (wrap-safe). Shared helpers `parse_no_trade_ranges` / `md_in_ranges` in `quant/limits.py`.
  simulate blocks entries whose FILL day is inside a window (funnel `window` column);
  open positions stay managed. Recorded in `params.json`. `timeframes.position_checks: M1`.
- Position checks (stop/target/BE/trail, trigger-point arm) now walk the M1 feed row by row;
  signals, bias and fills stay on H1. An hour with no M1 rows falls back to H1 checks for
  that bar only. Stops/take-profits still model fixed spread/slippage per fill. Exit times
  are minute-precision when M1 exits, H1 bar time otherwise.
- BE/trail effect timing moves from "next H1 bar" to "next check row" (next M1 bar in M1 mode).
- `mkdata --m1-csv` writes consolidated `data/<SYM>_M1.csv` (user must run this per pair
  once; ~2 GB total). Without the file the backtest silently runs H1 checks.
- Tests 96 -> 101 (range parse/match/rejects, window entry block, M1-vs-H1 divergent exits).
- Data audit (read-only, all 11 pairs): prices/order/integrity clean, no famous-day anomalies,
  H1 CSV = exact rebuild from raw sources. Vendor stamps use HistData's own day-fill grid,
  not strict UTC — accepted as-is (rules never read hour-of-day; broker-vs-vendor grid shift
  is a live-day concern, not now). M1 slice anchor floors to the hour edge: H1 stamps can
  sit at :01 when the raw :00 minute is missing, and a :01 anchor double-counted one minute.
- Build orchestration: mkdata stays single-symbol; the 11 M1 builds are hand-parallelized
  with PowerShell Start-Job (snippet in RUNBOOK). No code change — one-time data chore.
- Next: user builds M1 CSVs for the 10 pairs, then reruns the batch. Results will move
  vs run `20261017_100407` (both M1 resolution and holiday windows change exits/entries).

## 2026-10-15 — Bootstrap + MT5 handshake

- Created repo layout: `python/quant/`, `configs/` (10 pairs + `_base.yaml`), `data/` (gitignored), `tests/fixtures/`.
- Locked cost model: spread 20 points, swap −0.08/0.01 lot/night both sides, triple Wed + weekend.
- Python 3.12 pinned (MT5 wheel has no 3.14 build); deps installed: `MetaTrader5 5.0.6231`, pandas, pyyaml, dotenv, pytest.
- `USE_DEMO`/`USE_REAL` independent flags in `config.py`; `smoke.py` checks every enabled account, sends no orders.
- Smoke OK on Pepperstone-Demo (margin_mode=2 hedging, symbols need no suffix).
- Wrote `docs/STRATEGY.md` (this session).

## 2026-10-15 — Spec v0.3 risk lock

- Locked risk rules in STRATEGY.md section 8: USD 3/trade, 1 open/pair, 1 entry/pair/day (server date), 5 open max.
- Parked body-EMA agreement to section 15 (not an active rule).

## 2026-10-16 — Bias panel + trade record

- Added `quant.bias` (shared H4 B1 core: EMA20/50 + HR1a + sep>=0.3*ATR14, closed bars only), `quant.monitor` (console + `panel_state/current.txt`, rewrite on new H1 close, `NONE DETECTED` empty state, sends no orders), `quant.journal` (journal schema + <=31ch comment builder for live/backtest).
- Spec: STRATEGY.md section 13 (comment format, journal columns, panel rule).

## 2026-10-16 — Console-only bias panel + config encoding fix

- All 10 pair yamls had a truncated em-dash byte in the line-1 comment; replaced with ASCII `-`. `load_pairs` now falls back encodings per file so one bad file can't blank the panel.
- Monitor is console-only (no `current.txt`): UP/DOWN/FLAT bias table, repaint on new H1 close, bias only until entries are defined.

## 2026-10-16 — HR1 variants + two-column panel

- `h4_bias` takes the spec's HR1a/b/c selector (default a, per-pair `strategy.hr1`); HR5 stays parked off.
- Panel cut to SYMBOL + BIAS (`*` = open position); header split into local-time (Malaysia UTC+8) and broker last-H1-close (UTC) rows.

## 2026-10-16 — ATR-separation switch + ablation reminder

- New boolean `strategy.use_atr_sep` (default true = spec B1). `false` = MA-only comparison leg (pure EMA20/50 UP/DOWN, no HR1, no FLAT). Set once in `configs/_base.yaml` to flip all pairs; per-pair files override.
- Backtest must answer: does the `sep >= sep_min x ATR14` gate earn its keep? Run B1 sep 0.3 vs 0.0 (plus 0.2/0.4) and MA-only, all else equal; judge on after-cost expectancy + trade count (spec 11.4). Do not promote MA-only to baseline on panel eyeballing alone.

## 2026-10-16 — Boolean made visible: _base.yaml + .env

- The switch previously existed only in code. Now: `strategy.use_atr_sep: true` written in `configs/_base.yaml`, plus `USE_ATR_SEP` in `.env` (documented in `.env.example`, unset by default) overriding all pairs. Panel title shows `MA-only (env)` when the env override is active.

## 2026-10-16 — Closed-position records (demo + real)

- New `quant.records`: one row per closed position into `trades/demo.csv` + `trades/real.csv` (local/broker times, side, entry/close, profit, commission, swap, entry condition joined from journal on ticket). Panel loop syncs every enabled account each cycle; history calls only, never orders. Watermark = max ticket, so restarts never duplicate. Only our `--magic` (default 100001) is recorded.
- Backtest must compare ATR(7) vs ATR(14) for the bias separation gate (and any ATR stop/trail): same data, all else equal, judge on after-cost expectancy, not signal count.

## 2026-10-16 — E1 entry core + weekly loss halt

- New `quant.signals`: pure H1 E1 + hard rules (HR2/HR3/HR4 + stale-HL guard/extension cap), per-bar EMA50/ATR, window includes signal bar, two-sided touch zone, strict pivots, `warmup_bars: 300`. Section-5 table lives in `_base.yaml` strategy; panel ENTRY column shows `GO` or the first failing rule.
- New `quant.limits` + `WEEKLY_LOSS_PCT` (default 15): halt new entries at 15% week-start-equity realized loss; state in `memory/weekly_<demo|real>.json`; panel week line + `HALTED` banner. Week = UTC Monday for now, not broker-server week.

## 2026-10-16 — Hands: live executor round-trip test
- New `quant.live --roundtrip`: opens `--volume` (default 0.01) at market and closes it immediately. Dry-run default (plans only); `--no-dry-run` needs exactly one enabled account. Filling-mode check, volume snap, magic on both legs, journal rows for open + close, loud manual-close warning if the close leg fails. No signal entries yet.
- Bug caught live: `symbol_tick` is not a real API name (correct: `symbol_info_tick`). Fixed both call sites, guarded the close-leg tick against None, added a Ctrl+C warning, and added an API-surface regression test against the real wheel. Audited all other `mt5.*` uses: correct.
- New `quant.live --touch-close`: opens with close SL+TP attached (clamped to `trade_stops_level`), waits for the broker touch (TP/SL inferred from the OUT deal), timeout falls back to market close. Shared close/position helpers with roundtrip.

## 2026-10-16 — Backtester + first EURUSD result

- New `quant.mkdata` (M1→H1, coverage report, no silent fills) and `quant.backtest` (shared core, funnel-first, S1/BE-then-T1, full costs, `backtest_results/<local-time>/` with params.json). `run-backtest.bat` loops `configs/scan-selection.yml` (only EURUSD on; missing data prints SKIP).
- Config consolidation: `_base.yaml` is the sole settings holder (strategy + new `limits`), pair files keep symbol/pip_size/notes, `.env` back to account details only (both env switches removed).
- First run EURUSD 2015-2025: 21 trades, +$3.9, +0.048R expectancy, PF 1.16, maxDD $14. Funnel killers: HR4 (9945→3595), extension cap (→1137), E1 setup/trigger (→142). 20 stops / 1 target. Far below acceptance (300 trades, +0.10R) — ablation next: relax HR4/ext, sep and ATR sweeps.

## 2026-10-16 — Gate toggles + fixed lots + pip table
- `_base.yaml`: one-line comment on every variable; six `use_*` ablation switches (default true) honored by `check_entry` and visible in the funnel.
- Backtest defaults to fixed `--lot 0.01` (`--lot 0` restores USD3 sizing); cap-distance skip and cost filter stay, R divides by actual risk.
- `docs/PIP_VALUES.md` records the broker pip table (1 pip = 10 points; USD-measured; crosses need a second feed). Engine math asserted against it in tests.

## 2026-10-17 — Multi-pair intake (CSVs + zips)

- All 10 present pairs have full 2015-2025 file coverage, zero missing years (2023 thin everywhere, vendor-wide). CSV: AUDUSD/EURUSD/GBPUSD/USDCAD/USDCHF/USDJPY. ZIP (HistData, same minute format inside): AUDJPY/EURJPY/GBPJPY/NZDUSD. EURGBP/AUDNZD have no data and no sizing path — stay off.
- `quant/mkdata` reads zip members directly; H1 built for all 9 (~67.6k bars each).
- JPY crosses (AUDJPY/EURJPY/GBPJPY) convert tick values through the USDJPY feed, auto-loaded by the batch (SKIP with notice when absent). True crosses (EURGBP/AUDNZD) still unsupported.

## 2026-10-17 — v0.8: no time cap, one profit-trail rule, config reorg

- `_base.yaml` strategy split into BIAS / ENTRY / RISK MANAGEMENT; `flatten_strategy` (monitor.py) reads nested and flat layouts. New toggles `use_trail`, `use_be`; `bias_flip_exit` / `weekend_flat` now live in config (CLI flags still force them on).
- T1: initial stop holds until best profit >= `trail_r`, then stop = best-since-entry - `trail_r` x risk. BE is optional (`use_be`, off; redundant while `be_trigger_r == trail_r`). Peak now counts from entry (was: from the BE trigger bar).
- 120-bar time stop removed. Trades still open at the end of the data are not recorded (not new, but with no time stop it can touch more trades).
- Shorts now pay the fixed spread on exit (they paid none before). Short stop/target triggers still use bid highs/lows.
- `limits.max_trades_per_day: 5` (0 = off): portfolio post-filter, dropped entries listed in `params.json`.
- Tests: 96 passed. Baseline numbers from run `20261017_100407` are not comparable to the next run.

## 2026-10-17 — Parallel backtest batch

- `--jobs N` (default 10, capped at pair count; 1 = linear; 0 = all cores). One process per pair via `ProcessPoolExecutor`; workers pin BLAS/OpenMP to 1 thread. A failing pair is recorded (`failed` in `params.json`, `FAILED:` line) and does not lose the others. Output files are written in input order, so they do not depend on finish order.
- Acceptance still open: run `--jobs 1` and `--jobs 10` and diff the two result folders (must match). Check peak memory on the first parallel run.
- `run-backtest.bat` passes args through (`run-backtest.bat --jobs 4`).

## 2026-10-17 — Profit-based trail (T1 revised)

- `trail_atr` (ATR chandelier) replaced by `trail_r` (default 1.0): after the +1R BE trigger, the stop trails the best price by `trail_r` x initial risk. ATR no longer used in exits. Spec §7 updated.
- Baseline to compare against: run `20261017_002605` (ATR trail, 296 trades, -0.167R, PF 0.70, 4 target exits).

## 2026-10-17 — EURGBP data + general converter feeds

- `data/EURGBP/` zips were present after all; H1 built (~67.6k bars).
- Sizing now converts any quote currency through auto-loaded feeds (JPY via USDJPY, GBP via GBPUSD, AUD/NZD/CAD/CHF likewise); pairs without a path still SKIP with notice. EURGBP enabled in scan (AUDNZD: no data, stays off).

## 2026-10-17 — Scan list fixed to 10, NZDUSD parked

- `scan-selection.yml` now lists exactly the candidate 10 (AUDJPY in, EURGBP off without data). `NZDUSD.yaml` renamed to `NZDUSD_untrade.yml`; the loader skips `*_untrade` stems. `EURGBP.yaml` created (symbol + pip_size, off).
- Correction same day: AUDJPY out, NZDUSD in (`AUDJPY_untrade.yml` parked, `NZDUSD.yaml` restored). Final 10: EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD EURJPY GBPJPY EURGBP NZDUSD.

## Next

1. Define regime + entry rule (close `TODO_define` in STRATEGY.md and `_base.yaml`).
2. Build `quant.backtest` CLI (closed-bar execution, cost overrides, metrics report).
3. Export broker-aligned H1+H4 history CSVs into `data/`.
4. Backtest all 10 pairs, calibrate stops/sizing per pair.
5. Build `quant.live` loop (new-H1-bar wake, `order_check`, magic + idempotency, `--dry-run` default).
6. Demo 0.01 lots: EURUSD + one JPY pair, then all 10. Compare fills vs backtest.
7. Rotate demo password (appeared in chat).
