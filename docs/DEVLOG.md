# Dev Log (newest first)

## TODO (living checklist — strike the line when done; finished work goes into the dated log below)

### Now (housekeeping, no backtest needed)

- [ ] Lot-scale sweep (user runs): `--scale-lots` with `--balance-risk-pct` 1 / 3
  / 5 vs the fixed reference, one at a time. Headroom first: compounding
  crosses the scope ceiling once the balance grows, so the sweep also needs a
  widened `sizing_scope_usd.high` variant or it will refuse half the entries.
- [ ] H4->D1 variant (code done 2026-10-19): the active `_base.yaml` is already
  H4->D1. Still open on the user's calls: the D1 fence ceiling ([4,5.5] =
  5/9 pairs vs [4,8] = 9/9) and the two frequency knobs (max 2/pair/week,
  pair-day disable after a loss — NOT BUILT). Then: broker-exported
  `data/<SYM>_H4.csv` and `data/<SYM>_D1.csv` for every pair (none exist
  yet) -> write the TESTLOG pre-declaration ->
  `$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch`.
  Probes stay H1/H4-only until a D1 dice null is designed.
- [ ] Widened-stop mode (code done 2026-10-20, ships OFF): `risk.stop_sizing`
  trades a FIXED lot and widens the stop (and the target) until that lot
  reaches `sizing_scope_usd.low`, instead of trading more lots. Next: write
  the TESTLOG pre-declaration, then run the batch with `--widen-stop` and
  compare against the same run without it (one change per run).
- [x] ~~Optional lot increase when stop widening hits its cap~~ — implemented under
  `risk.stop_sizing.increase_lots_if_widening_fails` (default OFF).

### Verdict track (timebox: 2-3 more experiments, then decide)

- [ ] Write the variance-ratio / Hurst script (spec §11.3). Never done.
- [ ] Run both, record results in `docs/TESTLOG.md` (user runs them). Remaining
  after 2026-10-19: variance-ratio never run; dice re-run (`--real` parity,
  then D1-B 300 seeds) against the new pin `20261019_192501`.
- [ ] Decide from the results:
  - real result inside the random cloud AND variance ratio ≈ 1 → no edge from these entry rules / no trend to harvest on these pairs at H1/H4 → change market, timeframe or edge type — or stop.
  - real result clearly above the cloud, or gross > 0 but costs kill it → structural (spread/swap is a big share of 15-20 pip stops) → wider stops via a longer timeframe, or a cent account.
- Standing rules:
  - each hypothesis → `docs/TESTLOG.md` BEFORE running, one change per run
  - keep the last ~3 years unseen for any new idea
  - do NOT drop or keep pairs based on this run (about 200 trades per pair; the best/worst pairs are within noise)
  - stopping is a valid result; the tooling/engine/ledger/report are reusable; keep it demo-only

### Parked until the verdict is in

- [ ] Go-live demo smoke: 0.01 lots EURUSD + one JPY pair → all 10; compare fills vs backtest. Rotate the demo password (it appeared in chat).



## 2026-10-20

- **One base lot for every sizing mode.** `risk.default_lot` (0.01 by default)
  replaces the editable `stop_sizing.fixed_lot` in all three base configs.
  Normal sizing starts at this base, adds individual 0.01 lots until the scope
  floor is met, and skips if that size exceeds the ceiling. A 0.02 base can
  become 0.03, then 0.04; it does not jump in 0.02 blocks or shrink below base.
  Widening uses the same base; its optional lot fallback starts there too.
  Balance scaling respects the base as a minimum. Scope disabled on both sides
  means use the base unchanged (except in balance-scaling mode).
  `--default-lot` overrides it; `--stop-lot` remains a legacy alias, while
  `--lot` stays the exact diagnostic override. Older configs without the new
  key accept `stop_sizing.fixed_lot`; the new key wins if both exist.
  Invalid/non-finite/subminimum/non-0.01-step bases are refused. Shared rules
  feed backtest, dice and live planning; params/ledger record `default_lot`.
  Fixed an existing float-floor bug in `live.snap_volume`: exact 0.03 lots
  could become 0.02. Live rechecks the base and risk band after broker snapping.
  Tests: 258 passed (`$env:PYTHONPATH="python"; uv run pytest -q`).
  No backtest, live order or ledger rebuild run. Rebuild the ledger separately
  to expose its new column in existing headers.

- **Optional lot fallback after a widening-cap refusal (default OFF).**
  `risk.stop_sizing.increase_lots_if_widening_fails` only acts while
  `widen_stop_to_scope` is ON. Try the fixed-lot widening first; if it exceeds
  `max_stop_atr`, use the original strategy stop and the smallest 0.01-lot
  multiple that reaches the scope floor without breaking its ceiling.
  Scope failures, bad tick data, cost failures and broker-stop failures remain
  refusals. The target follows the final stop; compounding remains incompatible.
  Shared math serves backtest, dice and live planning. Params and ledger record
  the switch; `funnel.csv` counts sized fallback candidates as `lot_fallback`
  (before portfolio filters), and the live plan identifies fallback use.
  Removed the account-size, swap-timing and redesign TODOs at the user's request;
  H4/Daily is the new design. These removals are not validation claims.
  Tests: 234 passed (`$env:PYTHONPATH="python"; uv run pytest -q`), including
  fallback on/off, widening-first precedence, ceiling/tick refusals, final-stop
  cost checks, both live directions, broker constraints and config/ledger wiring.
  No backtest or live order run for this change. Existing ledger headers need
  `uv run python -m quant.ledger --rebuild` to show the new switch column
  (not run).

- **Widened-stop mode (`risk.stop_sizing`) — the alternative to trading more
  lots, ships OFF.** New config block in `_base.yaml` (and both presets):
  `widen_stop_to_scope` (bool), `fixed_lot` (0.01), `max_stop_atr` (3.0).
  OFF = today's behaviour: the lot grows until 1R reaches
  `sizing_scope_usd.low`. ON = the lot is FIXED and the stop is widened until
  that lot risks `low`; the take profit is placed from the widened stop with
  the same `tp_mult`, so the R:R is unchanged — only the distance to both
  levels grows. The stop is only ever widened, never narrowed.
  - Refusals (both named in the funnel): `stopcap` = the widening needs more
    than `max_stop_atr` x ATR from price (a stop that far away is not the
    trade the rules described); `scope` = the fixed lot already risks more
    than `sizing_scope_usd.high`, or the resulting 1R would leave the band.
    The cost gate (`max_cost_ratio`) now judges the FINAL stop distance.
  - One shared implementation: `rules.fit_stop_to_scope` is called by the
    engine (`backtest.simulate`) and by the live planner
    (`trader.plan_entry`), so a backtest and a live order cannot drift. The
    live path also refuses a stop closer than the broker's
    `trade_stops_level` ("stops-level") instead of letting the order bounce.
  - `rules.stop_sizing_conflict` is the single guard used by the backtest and
    the live loop: the mode cannot run together with
    `scale_lot_with_balance` (fixed lot vs compounding lot), the fixed lot
    must be >= 0.01 and `max_stop_atr` must be > 0.
  - CLI: `--widen-stop` (force on), `--stop-lot`, `--stop-max-atr`. The mode
    is recorded in `params.json` (`stop_sizing`) and in the run ledger
    (new columns `widen_stop`, `stop_lot`, `stop_max_atr` — run
    `python -m quant.ledger --rebuild` once, appends keep the old header
    until then). The dice probe reads the same block, so the null model
    stays comparable with the engine.
  - Tests: 224 passed (+11: shared widen math, the ATR cap refusal, the
    ceiling refusal, the engine path (stop + target + fixed lot), the live
    planner path, the broker minimum stop distance, the conflict guard, the
    preset/config wiring, the ledger columns). NOT run: any backtest, any
    live order.

- **Config keys renamed by ROLE, not by timeframe.** `bias.h4_ema_fast` /
  `h4_ema_slow` / `h4_atr_n` -> `bias_ema_fast_period` / `bias_ema_slow_period`
  / `bias_atr_period`; `entry.h1_ema_fast` / `h1_ema_slow` / `atr_n` ->
  `entry_ema_fast_period` / `entry_ema_slow_period` / `entry_atr_period`. The
  names now describe the CHART ROLE (bias chart vs entry chart) and stay the
  same if the timeframes change. The `bias_`/`entry_` prefixes stay because
  `flatten_strategy` merges both sections into ONE flat dict — a plain
  `ema_fast_period` in both would overwrite one with the other.
  Old key names are still accepted (older configs, older run folders), with
  the new names winning when both are present. The ledger and journal CSV
  headers keep their old column names; only the values follow the new keys.
  `warmup_bars` stays shared by bias and entry (splitting it would change the
  strategy, not just the names). The `execution:` block in `_base.yaml` is
  documentation only — no code reads `signal_bar` / `fill_bar` / `fill`; the
  comments now say so.

- **H4->D1 backtest no longer resamples broker candles.** The engine built
  its H4 and Daily grids from the H1 CSV at 00:00 UTC, so the Daily bias could
  see a day that the broker had not closed yet, and the entry scan mapped
  the bias with a 4-hour regime length regardless of the configured combo.
  Now: H4->D1 runs need broker-exported `data/<SYM>_H4.csv` and
  `data/<SYM>_D1.csv` beside the H1 CSV (missing files stop the run), and the
  bias map uses the next regime bar's open as the proof that the previous one
  closed. H1->H4 keeps its old resampled grid.

- **H4/Daily entry: two candle patterns, both for buys and sells.** The W1
  gate now requires the CLOSED H4 candle to end on the trend side of the
  EMA20, with two separate switches: `w1_touch_from_trend_side` (open on the
  trend side, wick touches across EMA20) and `w1_cross_from_other_side`
  (open on the other side, close back on the trend side). Either pattern
  enters; each can be switched off on its own.

## 2026-10-19

- **Report rebuilt combo-driven; Daily regime view + bias shading shipped**
  (`quant/report.py`, `quant/backtest.py`, `tests/test_report.py`). The popup
  now follows the RUN's own timeframes from `params.json`: execution chart
  first (default view), regime chart second (4H baseline / Daily for H4->D1),
  plus the raw H1 tape whenever execution != H1. New per-run artifact
  `bias_<SYM>.csv` (time, direction, hr1 per regime bar — captured from the
  same `bias_frames` the scan used, `backtest.py:write_bias_maps`) shades the
  regime view: LONG green / SHORT red / NEUTRAL grey, regime chart only,
  clipped to the window; old runs without the file show no shading. EMA
  periods follow the run (entry EMAs on exec, regime EMAs on the regime
  view; payload keys `emaH1/emaH4` -> `emaExec/emaRegime`, old params still
  read). "Held (N bars)" header counts execution-TF bars. Old runs without
  a `timeframes` key fall back to H1->H4 — validated by rebuilding
  `backtest_results/20261019_200214` (3790 trades, fallback keys correct,
  no raw/spans keys). Tests: 198 passed (+2: `_bias_spans` merge/pad, D1
  combo embed with shading). Not verified in a browser (static HTML/JS
  checks only); no real H4->D1 run exists yet, its report shape is covered
  by the unit test only.

- **Sizing-switch comment expanded in both active copies** (`_base.yaml`,
  `_base_h4d1.yaml`): `scale_lot_with_balance` now documents the two engines —
  OFF = fence sizing (floor is the target; SCOPE path), ON = percent sizing
  (target = balance_risk_pct % x the balance at entry; backtest walk starts at
  benchmarks.account_usd; live = MT5 balance; fence only guards). The stale
  fence NOTE (old 2.5/3.6 numbers) was replaced with the measured facts: H4
  bricks ~2.2-4.9 USD, the (2.75, 4.00)-brick dead band refuses EURUSD/USDJPY/
  USDCHF/EURJPY at [4, 5.5], high ~=8 revives all nine.
- **STRATEGY.md v1.0: variant strategy V-D1 recorded as section 16**
  (Daily EMA20/100 bias + flat rule, W1 sweep vs the H4 EMA20 with OPEN-side
  on, RR 1:2.5, trailing = separate exit model later). The spec's frequency
  rules (max 2/pair/week, pair-day disable after a loss) are recorded as NOT
  BUILT; open decisions list fence choice [4,5.5] vs [4,8], sep 0.0 literal
  flat rule, warmup, and the RR comparison. Version bumped v0.9 -> v1.0
  ("Changes from v0.9" block added).

- **Two config presets written, both INERT** (`configs/_base_h1h4.yaml`,
  `configs/_base_h4d1.yaml`). `_base_*` filenames are skipped by the pair
  loader, so applying = `Copy-Item` over `_base.yaml`, revert =
  `configs/_base_h1h4.yaml` back over it. The H4->D1 preset encodes the new
  strategy per spec: D1 bias (B1 + HR1 ≈ the "flat beyond EMA100" rule), W1
  sweep ON with `w1_open_side: true` and `w1_pen_atr: 0.0` (wick vs the H4
  EMA20, EMA100 ignored), E1-setup/E1-trigger/HR2 off (not in the spec),
  `h1_ema_fast/slow` = 20/100 (the H4 alignment pair), `tp_mult: 2.5`, trail
  off. The spec's per-pair weekly cap (2) and daily loss-disable are marked
  NOT BUILT inside the file. Active `_base.yaml` untouched (default combo
  verified after the edit: H1->H4).
- **W1 gate ("wick swept the fast EMA") — optional entry gate, OFF by default.**
  The closed candle's wick pokes through the entry-chart fast EMA AGAINST the
  trade (high above it for SHORT / low below it for LONG) while the entry
  chart's fast/slow EMA relation agrees with the regime bias (H4->D1: H4
  20/100 must point the same way the Daily 20/100 does). One shared rule in
  `signals.check_entry` -> backtest, live loop and panel all get it from the
  same code, zero live-specific lines. New keys in `strategy.entry` (all
  switchable in yaml, none hardcoded): `use_w1` (default false = today
  byte-identical), `w1_open_side` (candle must OPEN on the trade side of the
  fast EMA), `w1_pen_atr` (min sweep depth, 0 = any touch). Funnel gets a
  `w1` counter (first-failure code W1 sits after EXT, before E1-setup);
  ledger gains a `use_w1` gate column — run `python -m quant.ledger
  --rebuild` once (appends keep the old header until then). Deliberately NOT
  here (user's strategy list, later knobs): max 2 per pair per week, a loss
  disabling the pair for the day.
- Tests: 196 passed (was 191; +5 W1: SHORT sweep + alignment block, LONG
  mirror, open-side flag both sides, depth knob, off = auto-pass). Real-config
  smoke: flatten reads the keys; a no-sweep frame blocks at exactly W1 when
  forced on, passes untouched when off.
- **Lot scaling switch (`scale_lot_with_balance`) — compounding sizing, OFF
  by default.** OFF is byte-identical to before (1R aims at the scope floor).
  ON = each entry re-aims its 1R at `balance_risk_pct` % of the account
  balance at entry (account-global, backtest + live use ONE rule:
  `rules.scaled_lots`), snapped UP to 0.01 lots, then the SAME
  `sizing_scope_usd` fence checks the snapped 1R (in-band kept; refused as
  `scale-low` / `scale-high` / `scale-empty` on aim <= 0, i.e. account gone).
  Compounding only — wins grow it, drawdown shrinks it, never doubles after a
  loss (not martingale). Backtest: one forward walk over all pairs by
  timestamp AFTER daily cap + portfolio pass (`scale_lots_to_balance`) so the
  balance timeline sees only trades that happened; exits book realized pnl,
  kept trades keep their `pnl_R` exactly, USD rescales (pnl_usd = R x new 1R,
  swap/risk_usd/tp_usd x lot ratio — MTM marks open trades at R x risk_usd,
  stale risk would corrupt max_dd_mtm); drops recorded in params.json. Live: aim = pct x
  `account_info().equity` in the sizing path (`plan_entry(..., risk_target=)`);
  no equity/pct <= 0 -> unstamped DATA ERROR, retried next cycle. CLI:
  `--scale-lots` force ON + `--balance-risk-pct` override; mode + pct into
  params.json (`dice_probe`/parity compare summary+trades, params extras safe).
- Tests: 191 passed (was 186; +5: scaled_lots snap/fence table, shrink walk,
  fence refusal after growth, scratch-row inheritance, live plan_entry scaled
  aim + cfg keys). Defaults verified on configs: scale False, pct 3.0.
- Gaps (accepted): backtest aim uses REALIZED balance, live aim uses equity
  incl. floating PnL — documented divergence; when ON, a wiped account refuses
  further trades (fixed sizing today would keep trading the floor); 0.01-step
  snapping makes the corridor hysteretic, not smooth.
- **Timeframe upscale switch (`H4->D1`) — same logic, one TF up.** `timeframes.execution`
  and `timeframes.regime` in `_base.yaml` are now real keys: locked combos
  `H1->H4` (default, unchanged) and `H4->D1` (new); anything else fails the
  config check (`monitor.read_timeframes`, used by backtest + panel). Backtest
  derives both grids from the H1 CSV at 00:00 UTC (`build_htf`, `map_bias`
  reg_hours, `simulate(bar_hours=)` so M1 checks span the whole 4h bar);
  combo recorded in params.json. Panel/trader fetch the configured pair from
  the broker (poll accepts TF attribute names); smoke prints H1/H4/D1 counts.
- **Bug fix found on the way (live, latent):** `trader.py` hardcoded
  `TIMEFRAME_H1 = 16397` — not a valid MT5 timeframe (wheel: H1=16385, H4=16388,
  D1=16408). Live `_gate_check` would fetch garbage/None every bar (masked by
  dry-run default + mocked tests). Fixed; `_gate_check` now reads the execution
  TF from config.
- Tests: 186 passed (was 180; +6: D1 blocks, D1 completed-bar mapping, M1 span
  on the H4 grid, TF config validation, poll TF name resolution).
- Gaps (known): report.html chart windows stay H1/H4-shaped; dice_probe and
  edge_probe are H1/H4-only — the H4->D1 variant has no random-entry null yet.
- **Monday spreadcheck re-sample + JPY swap recalibration.** London-session
  sample 09:19 UTC with the fixed points-mode math; all three JPY yamls
  re-calibrated (old numbers were ~1.6x too big under the old /100 math —
  fresh reads 0.63x: USDJPY +0.0191/−0.0998, EURJPY −0.0230/−0.0690,
  GBPJPY −0.0017/−0.1261). `spread_points` kept on the wider 2026-10-17
  Friday-close sample (conservative); Monday London reads were 0.3/0.5/0.4
  pips. Off-peak sample still open (see TODO).
- **Weekly-halt equity bug fixed (user found it; engine only — live untouched).**
  `backtest.py::portfolio_filter` halted a week when closed P&L reached
  `-weekly_pct/100 * week-start equity`; at week-start equity <= 0 the
  threshold turned POSITIVE so the first exit of any week (even a win) tripped
  it. Verified from saved runs + direct function test: reference `20261018_173936`
  had 4,430/5,134 portfolio drops = `weekly_halt`; closed equity crossed <= 0 on
  2015-11-16 ( −1.30 USD) and 1,732/2,064 trades sat after that; weeks starting
  at <= 0 equity averaged 2.5 entries vs 4.8. Live `limits.assess` guards
  (`start_equity <= 0` -> never halts), so backtest and live DISAGREED.
  - Fix: the halt is R-based per spec 8A — `_base.yaml` gains
    `limits.weekly_loss_r: 5.0` (0 = off), `--weekly-loss-r` CLI replaces
    `--weekly-loss-pct`; the filter sums `pnl_R` per week (trades frames
    already carry `risk_usd`/`pnl_R`) and no longer sees ANY equity path —
    account state cannot reach the rule. `weekly_loss_pct` stays for the
    live/panel halt (its >= 0 guard is already correct there); moving live to
    R is a parked change-set.
  - Consequence for recorded verdicts: every prior backtest and BOTH dice
    variants (D1-A/D1-B) ran through the broken filter (`dice_probe.py` same
    call), so the D1 "WITHIN DICE NOISE" verdict compares through a distorted
    funnel — PROVISIONAL. Re-run the reference batch + dice with `weekly_loss_r`
    (user runs); treat re-run numbers as the declared change-set.
  - Tests 169 → 178, all pass (focused weekly-halt set + existing dice/base tests
    untouched by the swap); new regression `test_portfolio_filter_week_of_winners_never_halts`
    locks the winners-week case at any week-start state.
- **Week-booking flaw fixed, same day (second review pass; user repro).** The
  week rolled over on ENTRIES only: an exit closing early in a NEW week was
  booked into the discarded previous-week bucket and erased by the next
  entry — an exit that should halt a week never did (user's case: previous-
  Friday trade, Tue-13 exit −6R, Thursday entry let in). Fix: the rollover
  moved to the top of the event loop and fires on EVERY event by its own
  timestamp — deal-time booking, same as live counting deals >= monday_ts.
 Tests 178 → 180 (`..._exit_books_its_own_week` = user repro,
  `..._friday_entry_monday_exit_blocks_the_new_week` = cross-week case).
- **Reference labelled pre-fix.** Batch folder `20261018_173936` renamed to
  `20261018_173936_prefix` (ledger rebuild re-keyed, 12 runs). Dice
  `--reference` default follows the new name — parity against it fails BY
  DESIGN until a post-fix batch run becomes the new pin.
- **Cost-model decisions (2026-10-19, user):** `commission_per_lot` stays 0.0
  (Standard account — the spread compensates; Razor would be ~3.5 USD/lot/side,
  each side charged by the engine) and `slippage_pips` stays 0.0. Noted gap:
  the engine charges slip on exits only (entries fill at the observed
  open) — harmless at 0, revisit only if slip is ever raised.

## 2026-10-18

- **D1 dice probe (random-entry null) — verdict: WITHIN DICE NOISE.** New module
  `quant/dice_probe.py` + tests. Parity gate passed exactly against reference
  `20261018_173936` (2064 trades / −54.84 / −0.013R) before any dice. 300 seeds
  per variant, base 42; B's run split across 3 fragments, merged deterministically
  (overlapping seeds byte-identical). Verdict metric as pre-declared: pooled
  post-cap+portfolio-pass mean R per trade.
  - D1-B (random bias-ON bar + H4-bias direction): real −0.013R = **P90.3**;
    dice mean −0.045R, P95 −0.0079R — bar missed by ~0.005R; 6/300 dice seeds positive.
  - D1-A (random bar + random direction, placebo): real = **P92.0**; dice mean −0.0513R.
  - A ≈ B (Δ mean 0.006R) → the H4 bias direction adds almost nothing on top of
    entry timing — consistent with R1b, now confirmed through the full trade
    machinery (same exits, costs, caps, filter order).
  - The rules lose ~3x less per trade than dice (−0.013R vs −0.045/−0.051R) but
    neither pre-declared P95 bar is cleared; §12 money bar (≥ +0.10R) NOT MET.
  - Per the decision tree: real inside the random cloud → next check is the
    variance-ratio / Hurst script (still to run), then decide.

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
  portfolio pass after the daily cap: max_total_positions (5), max_ccy_net (2),
  weekly loss halt (limits.weekly_loss_pct) — new knobs live in `_base.yaml`,
  CLI-overridable, 0 = rule off; any run with the pass ON is a NEW declared
  change-set vs R2. Dead yaml keys removed (regime_rule, risk_pct,
  max_positions_per_pair, triple_swap_days, contract_size). Tests 131 → 142.
- **`max_total_positions` mismatch fixed:** `_base.yaml` (= 5) confirmed the
  single source; STRATEGY.md sections 8 + 8A and this log now say 5. RUNBOOK
  and TESTLOG never carried a number — nothing to align there.

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
