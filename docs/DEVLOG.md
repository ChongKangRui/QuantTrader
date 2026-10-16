# Dev Log

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

- New `quant.mkdata` (M1→H1, coverage report, no silent fills) and `quant.backtest` (shared core, funnel-first, S1/BE-then-T1, full costs, `results/<local-time>/` with params.json). `run-backtest.bat` loops `configs/scan-selection.yml` (only EURUSD on; missing data prints SKIP).
- Config consolidation: `_base.yaml` is the sole settings holder (strategy + new `limits`), pair files keep symbol/pip_size/notes, `.env` back to account details only (both env switches removed).
- First run EURUSD 2015-2025: 21 trades, +$3.9, +0.048R expectancy, PF 1.16, maxDD $14. Funnel killers: HR4 (9945→3595), extension cap (→1137), E1 setup/trigger (→142). 20 stops / 1 target. Far below acceptance (300 trades, +0.10R) — ablation next: relax HR4/ext, sep and ATR sweeps.

## Next

1. Define regime + entry rule (close `TODO_define` in STRATEGY.md and `_base.yaml`).
2. Build `quant.backtest` CLI (closed-bar execution, cost overrides, metrics report).
3. Export broker-aligned H1+H4 history CSVs into `data/`.
4. Backtest all 10 pairs, calibrate stops/sizing per pair.
5. Build `quant.live` loop (new-H1-bar wake, `order_check`, magic + idempotency, `--dry-run` default).
6. Demo 0.01 lots: EURUSD + one JPY pair, then all 10. Compare fills vs backtest.
7. Rotate demo password (appeared in chat).
