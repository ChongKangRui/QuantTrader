# Dev Log (newest first)

## TODO (living checklist — strike the line when done; finished work goes into the dated log below)


- [ ] Monday spreadcheck re-sample (peak + off-peak), then recalibrate the 3 JPY-pair yamls (USDJPY/EURJPY/GBPJPY swaps were ~1.5x wrong under the old /100 math).
- [ ] Portfolio pass runs: pre-declare pass lines in `docs/TESTLOG.md` FIRST (max_total_positions 4 / max_ccy_net 2 / weekly halt 15%), then rerun the batch as a new declared change-set (only on user instruction).
- [x] Build the live trading loop: `quant.monitor --trade` supervisor (new-H1 wake, magic-filtered adoption, per-pair open check before every send, caps/portfolio/weekly/no-trade gates, trail management, restart idempotency via bar-stamp memory). Demo only, dry-run default; `start-trader.bat`. Validation staircase on the terminal next.
- [ ] Go-live demo smoke: 0.01 lots EURUSD + one JPY pair → all 10; compare fills vs backtest. Rotate the demo password (it appeared in chat).
- [ ] Strategy-core redesign (open track): ladder shows nothing beats R0 and R2 verdict FAIL — design the next change-set with pass lines pre-declared in `docs/TESTLOG.md`.

### Verdict track (timebox: 2-3 more experiments, then decide)

- [ ] Zero-cost backtest: `run-backtest.bat --spread-points 0 --slippage-pips 0 --flat-swaps` — gross expectancy; expect ≈ 0.
- [ ] Random-entry null (spec §11.5): random entries in the bias direction, same exits and sizing; ≈ -0.05R would mean the entry rules add nothing.
- [ ] Variance-ratio / Hurst test per pair (spec §11.3): do these pairs trend at all on 1-5 day horizons? Never done.
- [ ] Write the two scripts above (random null + variance ratio) — waiting on user's "go ahead".
- [ ] Decide from the results:
  - gross ≈ 0 AND variance ratio ≈ 1 → no trend to harvest on these 10 pairs at H1/H4 in 2015-2025 → change market, timeframe or edge type — or stop.
  - gross > 0 but costs kill it → structural (spread is a big share of 15-20 pip stops) → wider stops via a longer timeframe, or a cent account.
- Standing rule: each hypothesis → `docs/TESTLOG.md` BEFORE running, one change per run; keep the last ~3 years unseen for any new idea. Stopping is a valid result — the pipeline caught it before real money; the tooling/engine/ledger/report are reusable for the next idea; keep it demo-only.

## 2026-10-18

- **yaml comments travel into params.json.** `_base.yaml` now has one short
  comment per knob (gate codes explained: HR1/HR2/HR3/HR4, EXT, E1-setup,
  E1-trigger, B1 — codes kept, meaning inline). One-line dicts were expanded
  to block style so each key holds its own comment; VALUES unchanged
  (asserted). `backtest.py` gains `yaml_notes()` — parses the inline comments
  and writes `params["notes"] = {"_source": ..., key: comment, ...}` into
  every new run's `params.json`, so run folders stay readable without the
  yaml open (ledger's empty `notes` CSV column is unrelated and untouched).
  Tests 168 → 169. Old run folders keep their original params.json.

- **live trading loop built (backtest==live shared math).**
  - `quant/rules.py`: the engine's entry math extracted to one source —
    `step_risk` (1R at 0.01 lot), `risk_usd`, `cost_ok` gate, `scope_lots`
    (scope band + fixed-lot + legacy target), `target_dist`, `activated`,
    `combine_stop` (BE + T1 trail overlays). `backtest.py` now calls these —
    funnel behavior unchanged (all prior tests pass untouched).
  - `quant/trader.py`: mechanics + orchestrators. `trade_on_bar` = full bar
    decision (pair-open, weekly halt, daily portfolio cap + structural
    1/pair/day, no-trade windows, `positions_breach` total/ccy caps, E1 gate
    on fresh closed bars, then cost/sizing via the shared rules). Bar stamped
    in the memory file only when the outcome is final (failed sends are
    retried next cycle); stamps ARE the restart double-send guard.
    `_send_or_plan` sends market orders with broker-side SL/TP; dry-run writes
    plan rows only. `sync_book`/`adopt_ctx` rebuild position context from
    broker IN-deal history + journal rows (position id captured on sends,
    initial SL/1R restored from the journal; orphan positions adopted with
    one loud row). `manage_book` trails via `TRADE_ACTION_SLTP` each cycle
    (~60s) using the monotonic best bid, one sub-tick-nudge minimum.
  - `monitor.py`: `--trade` turns the read-only panel into the supervisor
    (banner on the panel: TRADER ON, dry-run vs real, caps values). `--trade`
    refuses to run when demo AND real are enabled together; dry-run default
    comes from `live.dry_run_default`; magic from `live.magic` (CLI override).
    All knobs read the SAME `_base.yaml` keys the engine reads
    (`read_trade_cfg`). Journal gained `position` + `risk_usd` columns
    (legacy header auto-widens in place, data preserved).
  - `start-trader.bat` = the trading switch (dry-run default); `start-panel.bat`
    stays strictly read-only. Closing the trader window = no trading.
  - Tests 131 → 168 (`test_rules`, `test_trader` on a purpose-built fake; no
    terminal needed). NOT run against a live terminal — validation staircase
    (dry-run evening → 0.01-lot demo trade → kill/restart with open position →
    demo days) is the user's.
  - Tripped-up during build, caught by tests: guard sequencing bug (caps
    branch shadowed the E1 gate when `max_trades_per_day` > 0) and a falsy-0
    bug where `DEAL_ENTRY_IN` (=0) made our own IN deals invisible. Both fixed;
    worth remembering: never `getattr(x, -1) or -1` on a 0-valued field.

- **bias EMAs became config, naming split by chart family.**
  `_base.yaml` now has TWO key families: `h4_ema_fast/h4_ema_slow/h4_atr_n`
  (BIAS watchman; were hardcoded 20/50/14 in `bias.py`+`backtest.py`) and
  `h1_ema_fast/h1_ema_slow` (ENTRY; renamed from `ema_fast/ema_slow`). Old
  `ema_fast` names still accepted by the report for pre-rename run folders.
  `h4_bias()` takes period args defaulting to locked constants; `Bias` fields
  renamed (ema20/ema50/atr14 → ema_fast/ema_slow/atr_n). Report chart legends
  now show periods read from each run's `params.json` (`"emaH1"/"emaH4"`
  blocks, `efast/eslow` window keys) — the chart displays what the engine used.
  Values preserved from the user's own edits: warmup_bars 100, use_hr2 true,
  trail_r 1.5 (any R-run with these is a NEW declared change-set vs R2 pass
  lines). Tests 125 → 128 passed.
- **run ledger.** `backtest_results/_ledger.csv`: one row per run
  (summary.csv TOTAL + params.json + trades swap sum). Appended automatically
  after every backtest; `uv run python -m quant.ledger --rebuild` rebuilds all
  folders. Off gates = blank cells. Current ledger: 6 runs incl. 5 previously
  unledgered 10-18 runs (no_trail, trail_1R/1.5R, +2); all verdict FAIL. Note:
  R2 params.json records lookback 12 — TESTLOG said 5; ledger reads
  params.json as source of truth. Tests 128 → 131. (`workers` column removed
  in a later same-day sweep; CSV schema is now 50 columns.)
- **review fixes (panel bias, records watermark, swap mode, portfolio pass).**
  `monitor.py` now passes `h4_ema_fast/h4_ema_slow/h4_atr_n` to `h4_bias` — the
  panel follows config (was locked 20/50 while yaml said 20/100). `records.py`
  groups the FULL deal history per position_id and keeps whole groups whose OUT
  is above the watermark (entry data of early-opened positions no longer lost;
  commission sums IN+OUT deals). `spreadcheck.py` reads `swap_mode` (verified
  Pepperstone-Demo = POINTS): converts via the point value of a 0.01 lot and the
  broker's own quote for non-USD profit currencies — the plain /100 was wrong for
  JPY pairs (~1.5x) by luck right for EURUSD/XAUUSD. BACKTEST ENGINE now runs a
  portfolio pass after the daily cap: max_total_positions (4), max_ccy_net (2),
  weekly loss halt (limits.weekly_loss_pct) — new knobs live in `_base.yaml`,
  CLI-overridable, 0 = rule off; any run with the pass ON is a NEW declared
  change-set vs R2. Dead yaml keys removed (regime_rule, risk_pct,
  max_positions_per_pair, triple_swap_days, contract_size). Tests 131 → 142.

## 2026-10-17 — v0.9.4: honest costs, scope sizing, R1b probe, MTM drawdown

- **spreadcheck fixed**: `symbol_select(sym, True)` adds symbols to Market Watch
  (with False, only already-listed pairs returned info — 9/10 pairs "refused").
  Added a closed-market hint when spread reads 0.
- **Per-pair costs wired**: pair yamls now accept a `costs:` block
  (spread/swaps); `load_pairs` carries it, backtest + edge_probe merge it over
  base costs, CLI sweep flags still win on top. All 10 pair yamls calibrated
  from the 2026-10-17 Friday-close sample (EURUSD 0.2 pips ... GBPJPY 2.2).
  `params.json` records `pair_costs`. Monday re-sample may refine.
- **R1b probe run** (`edge_probe_R1b_20261017.csv`): NOT CONFIRMED again — cost
  line halved (0.164 -> 0.085 ATR) yet pooled onset drift unchanged
  (+0.030 / -0.027). The gap is the missing signal, not costs.
- **Sizing scope** (per user decision): `risk.sizing_scope_usd {low 2.5,
  high 3.6}` replaces the risk_usd target and the USD3 cap gate. Engine sizes
  up in 0.01-lot steps to reach `low`, refuses when nothing fits the band
  (funnel gate `scope`); `--lot` stays as diagnostic override; `--scope-low/
  --scope-high` CLI overrides. Known holes: EURUSD stops 18-25 pips, USDJPY
  ~27-37.5 pips.
- **MTM portfolio drawdown**: hourly mark-to-market account curve
  (`equity_curve.csv`; open positions marked as R-multiple x recorded 1R at
  each pair's close; swap accrual ignored intraday). TOTAL drawdown bands now
  grade the MTM curve; `max_dd_mtm`/`max_dd_mtm_pct` columns + report MTM USD
  overlay + glossary. Runs without risk_usd degrade to the closed-trade curve.
- run_all jobs are 3-tuples (symbol, path, per-pair costs) — internal change.
- Tests 116 -> 123. NOT run: weekday spread re-sample; live anything.
- **R2 baseline captured after the above landed** (`20261017_191201`, deterministic
  re-run of the deleted `20261017_183837` — identical figures): 7274 trades,
  −1379.19 USD (−449.29R), MTM DD 1479.8%, verdict FAIL — ledgered in TESTLOG with
  the no-edge takeaway. Ladder status: nothing beats R0; strategy core rethink is
  the open track, not parameter tuning.

## Addendum (same day, after user review of the R2 report)

- Trade list and chart titles now show P/L in USD next to R (user request:
  dollars, not R-only); rows with no embedded window are dimmed in the list.
- Chart embedding cap removed entirely (user-approved size): **all 7274 windows
  embed, report 53 MB**, every trade of every pair clickable. History: the 600-cap
  first zeroed winners (negative fill budget), then a fair 300/300 split still
  starved 8/10 pairs because the global bundle is pair-ordered — only full
  embedding removes the class of bug. Click path verified programmatically over
  every id (fields resolve for all 7274; 10/10 pairs have win+loss windows).
- Trade-chart UX (user request): charts open in a **separate popup window**
  (one reused window per browser); 1H/4H toggle inside the popup with EMA20/50
  on both — 4H windows use the broker H4 CSV when present, else the engine's
  `build_h4` resample (same bars the backtest traded on; no broker H4 files
  exist yet). Entry marker is yellow now, not green. Report 73 MB; tests 125.
- Second UX pass: windows doubled (1H 120 before/40 after, 4H 60/20; caps 800/400)
  and the popup's y zoom is pinned to candles + stop + target + entry/exit marks
  (15% pad) — before, 4216/7274 trades had stop or target outside the candle span
  and Plotly's auto-zoom cut the levels out of the picture. USD labels kept.
  Report now 125 MB; embed-all + doubled windows = user-approved size.
- Popup root cause found (user-visible bug: stop/target lines never shown): the
  first popup drew candles with the MAIN page's plotly into the popup's foreign
  document — candles rendered but layout directives (axis ranges, shapes) were
  silently mis-applied. Fix: the popup now writes its own copy of the embedded
  plotly-lib script at popup-open (one copy per window, no static duplicate) and
  draws natively inside its own document. Level lines also get a null guard for
  pre-sl/tp runs. Both fixes render-only; confirmed via embedded-JS checks.
- `_base.yaml` strategy block reorganized: every knob now sits directly under
  its owning gate and is tagged `[use_x]` (dead while false), always-live knobs
  marked `(always live)`; values untouched (parsed dict identical, 31 keys).

## 2026-10-17 — v0.9.3: DD baseline fix, named funnel gates, visible cost gate, spreadcheck

- **DD fix** (`metrics()` + `total_row()`): equity now starts at 0, so a first-trade
  loss counts as drawdown (EURGBP was shown 0.0, really 2.86; GBPJPY 27.43 -> 29.51).
- **Per-pair drawdown bands removed** (user decision): per-pair DD% treats each pair as
  owning the whole 100 USD account — misleading with a shared account. `max_dd_pct` stays
  informational per pair; PASS/WARN/FAIL DD banding now happens only on the TOTAL row.
- **Funnel gates named** (`simulate()` returns per-gate counts; funnel.csv gains columns):
  `open` (position open/overlap), `day` (1 entry/day), `tick`, `usd3` (stop > USD3 cap
  distance — blocks stops > ~30 pips = ATR > ~20), `cost` (round-trip cost share of stop),
  `lot` (risk lot < 0.01). The old `sized` lump can no longer hide why EURGBP lost 171
  of 172 candidates.
- **`max_cost_ratio` surfaced**: now a visible `limits.max_cost_ratio` in _base.yaml
  (CLI `--max-cost-ratio` overrides; 0 disables the gate). It was an engine-side default
  (0.10) only recorded in params.json — the user never saw it, and it silently forced
  entry ATR into a ~15.3–20 pip band on majors (together with the USD3 cap).
- Trades CSV gains `risk_usd` (1R at the initial stop) and `tp_usd` (take-profit amount);
  report trade list shows both + an exit-type filter; SL/TP chart lines are labelled
  with their USD values. Summary/report headers now use readable names
  (Avg P/L per trade (R), Trades per month, Max drawdown (% of account), ...), and a
  glossary line states the shared-account rule.
- `quant/spreadcheck.py` (`python -m quant.spreadcheck`, read-only): live spread/swap
  per enabled symbol from the terminal, for cost calibration (demo spreads vary by
  session; sample at different hours). No orders, no settings changes.
- Tests 112 -> 116 (DD-first-loss, gate contract, per-pair band removal, spreadcheck
  formatting). Report re-rendered on the real run: old CSVs (no risk_usd) render "-",
  all checks pass. NOT run: spreadcheck against a live terminal; any backtest.

## 2026-10-17 — v0.9.2: edge probe + auto HTML report (R1 tooling)

- `quant/edge_probe.py` (`python -m quant.edge_probe --batch`): bias-only measurement, opens no trades.
  Onset flips (verdict set), all bias-on bars (state), random bars with random direction (null). Move =
  direction-aligned close-to-close over 24/48/72 H1 bars ÷ ATR(atr_n). Cost line per pair = spread +
  2×slippage in that pair's mean-ATR units. Pooled verdict (rule fixed in docs/TESTLOG.md before results):
  onset edge ≥ 0 beyond 2 SE at 48 AND 72; per-pair rows and the 24-bar horizon are information only.
  `--csv` writes the table (per-pair + pooled rows).
- `quant/report.py` + `uv add plotly` (7.1.0): every backtest now also writes `report.html` into its own
  run folder (call is import-guarded; report problems never kill the run). plotly.js embedded exactly
  once; overview figs (equity R/USD + drawdown R, net R/year) render on load; each trade's candle window
  (60 H1 bars before entry -> 20 after exit) is a compact JSON blob drawn on row click; EMA20/50 computed
  on the full H1 series then sliced. Standalone rebuild for old runs: `python -m quant.report --run <id>`.
- `_base.yaml`: R2 simple baseline — use_hr2/hr3/hr4, hl_guard, use_ext OFF; use_trail OFF;
  max_trades_per_day 5 -> 20. E1-setup + E1-trigger stay on. Ladder + revert values in docs/TESTLOG.md.
- `docs/TESTLOG.md` (new ledger): pass line + run ladder fixed before any probe/backtest result;
  R0 row = real numbers of `20261017_153137` (282 trades, −98.36 USD, −40.91R, PF 0.737, DD 110.9%,
  benchmark verdict FAIL), bars avg/med 9.6/7.5. R1/R2 rows pending until the user runs them.
- Tests: 103 -> 112 (probe events/alignment/cost/pooling/verdict gating; report lazy plotly embed,
  per-trade blobs, missing-data skips). Report smoke-rendered on the real `20261017_153137` run:
  6.5 MB, 282/282 windows embedded, JSON clean. NOT run: edge_probe against real data, any backtest.
- R1 probe executed 2026-10-17 (user approved): pooled onset edge −0.13/−0.19 ATR at 48/72 bars,
  move ≈ 0 before costs, null ≈ +0.10/+0.14 -> NOT CONFIRMED. Per ladder: R2 paused; result ledgered.

## 2026-10-17 — v0.9.1: benchmark grading in the backtest

- `benchmarks:` block in `_base.yaml`: declared account 100 USD (user's planned size — aggressive),
  max-dd bands 30/50 %, PF 1.50/1.00, net expectancy 0.10R/0.00R, portfolio trades/month
  2.0/0.2, worst calendar year −20R. Numbers only, no code edits to retune.
- `grade_benchmarks()` grades every `summary.csv` row: `max_dd_pct` + PASS/WARN/FAIL band
  columns, overall `verdict` per row (0 trades = NA). `TOTAL` also gets trades/month
  (fixes the old NaN) and a worst-year band; console prints one TOTAL line.
- Win rate deliberately not benchmarked — PF/expectancy already encode it.
- Tests 101 M1-math + 1 new grading test -> 103 passing.

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
