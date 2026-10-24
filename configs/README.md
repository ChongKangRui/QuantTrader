# Configs — `_base.yaml` and the pair files

## Active broker position checks

### Optional offline preparation/evaluation window

`backtest_evaluation` is absent/off by default; it never changes live trading:

```yaml
backtest_evaluation:
  enabled: true
  start: "2020-01-01T00:00:00Z"  # inclusive fills; earlier bars prepare indicators only
  end: "2026-01-01T00:00:00Z"    # exclusive fills; no prices after this boundary
  require_preparation: true     # require configured closed warmup on BOTH chart roles
```

Indicator warmup guards remain active. Preparation cannot create positions, fees,
loss/quota state or scored equity/exposure. The enabled window records calendar
boundaries in params and comparison/parity identities. Terminal valuation may occur
at the end boundary; yearly attribution belongs to the interval just ended.
Dates are configurable and normalized to UTC. An end cutting an execution candle
is rejected rather than inventing a partial candle. CLI overrides:
`--evaluation-start`, `--evaluation-end`, `--evaluation-window` /
`--no-evaluation-window`. Setting either date enables the window unless explicitly
disabled. Insufficient preparation fails when required; turning off that extra
validation does not disable the strategy's ordinary indicator warmup.

The isolated four-pair setup is local-only under
`data/four_pair_evaluation_20261024/configs/`, selected explicitly with
`--config-dir`; it is NOT the active config directory. See `docs/TESTLOG.md` for
the frozen universe/costs/verdict rules. No actual-history experiment has run.

### Broker source clocks and offline bundles

`backtest_data.broker_api_clock` controls history export only: `auto` (default)
normalizes verified Pepperstone server labels using New York + 7h and US DST;
other servers retain the UTC assumption. Explicit `utc` / `new_york_plus_7`, or
exporter `--broker-clock`, override it. Date queries, warmup, closed-candle checks
and exported CSVs use the same conversion; metadata records both clocks. This does
not modify live candle/quote/deal consumers or rewrite any existing dataset.

`quant.mkdata --bundle-broker <source-dir> [...] --out-dir <fresh-dir>` assembles
verified imported/API candles offline. It verifies source checksums, retains
warnings, removes only identical overlaps and refuses conflicting OHLC/volume.
It never fills/resamples bars or overwrites source files. A separate bundle
manifest pins H1/H4/D1 and converter inputs to the same dataset.

### Existing position-check behavior

`configs/_base.yaml` defaults `backtest_data.position_checks` to `H1` for every
selected pair. Entry and bias charts stay independently configured (currently
H4 entries / D1 bias). Stops, targets, breakeven and trailing walk the actual
broker H1 candles; each candle's extremes can tighten only the next candle's stop.
Both protective levels touched within an hour still count as a stop.

The H1 extension manifest and each required pair/converter file must validate.
Missing H1 files or execution intervals without any H1 observations fail, never
fall back to H4 or vendor data. Existing partial-session warnings remain; absent
hours are not invented. Use the execution timeframe explicitly to restore coarse
checks. Inert presets retain their own settings. Legacy/research M1 is unchanged.

New runs pin the H1 source identity; old H4-only references are not interchangeable.
Converters use available closed H1 prices. Equity marks still use the execution
tape (H4 here), which reports label separately. Live quote-based trailing is unchanged;
H1 checks are an approximation, not exact broker fill reproduction.

New accounting records `exposure_seconds`: held time inside observed execution
candles, divided by the same tape's available seconds. Weekend/data gaps are
excluded from both sides; short sessions are clipped at the next candle open.
`bars_held` remains a chart-context count, not the exposure calculation. Old
reports retain a labelled bar-count estimate; filtering trades retains the full
observation denominator.

Swap accrues at observed UTC date changes in the position-check timeline,
including the recorded exit boundary. Thursday's date change carries the
Wednesday triple; entry exactly at midnight is not charged for the prior night.
This retains the existing approximate date/gap model, not a broker rollover/DST
calendar. Old accounting references require a new baseline before comparison.

## Presets (kept inert next to `_base.yaml`)

`_base_*` filenames are skipped by the pair loader, so full copies can sit
here safely. By default the engine reads `configs/_base.yaml`:

- `configs/_base_h1h4.yaml` — the older H1->H4 preset; copy it to
  `_base.yaml` to switch back.
- `configs/_base_h4d1.yaml` — the "Daily bias / H4 entry" strategy: W1 gate
  on with both `w1_touch_from_trend_side` and `w1_cross_from_other_side` on,
  E1-setup/trigger + HR2 off, `tp_mult: 2.5`,
  trail off. NOTE inside: the spec's "max 2 per pair per week" and "a loss
  disables the pair for the day" are not built — no knobs exist yet.
- Apply one: `Copy-Item configs/_base_h4d1.yaml configs/_base.yaml -Force`
- Revert:    `Copy-Item configs/_base_h1h4.yaml configs/_base.yaml -Force`

### Opt-in H4 crossover preset

`configs/_base_crossover.yaml` is selected with `--base-config`; do not copy it
over the active base. Both `quant.backtest` and `quant.monitor` accept this flag.
Pair symbols, selection and sampled costs still come from `--config-dir configs`.
The chosen preset supplies all strategy, risk, costs and limits defaults; it is
not an overlay on `_base.yaml`. Explicit missing/invalid presets fail closed.

- Crossover memory uses execution-chart EMAs; trend bias and its price/ATR-separation
  guards use only the regime chart. All supported timeframe pairs work with crossover.
- `use_crossover_memory: false` disables the crossover gate/allowance. When enabled,
  `use_recovery_entry` must be true. Execution and regime timeframes and EMA periods
  are independently configurable; neither has to match.
- `crossover_max_entries: 2` counts accepted fills, not recovery signals/plans.
  Change it to `3` for three attempts. Both attempts need a fresh recovery setup.
- No same-pair overlap, even with a position from another magic/manual trade live.
  Weekly/daily entry and portfolio/currency caps are off in this preset. Hours,
  blackout dates, daily-loss block, weekly loss halts, costs and sizing remain.
- Initial stop `1.5 x ATR7`, trailing `1.5R`, take profit `10R`; trail may exit first.
- Startup searches `crossover_history_bars: 6000` closed candles for a genuine
  post-warmup reversal. Initial EMA alignment alone grants no allowance. Increase
  this value if the cross is older or an outage exceeds saved history overlap.
- Persisted EMA/ATR, pullback and crossover state survive a rolling bar window.
  Live reconciles distinct opened positions from broker history since the cross,
  including already closed trades. Missing history or an unresolved send blocks
  entries. Indicator/recovery setting changes require matching saved memory;
  do not delete memory to bypass an unresolved order.
- Separate `magic: 100002` and magic-suffixed live/weekly memory isolate this preset
  from the active strategy. The trading panel shows cross time and entries used.
- Offline admission considers all sized recovery candidates together, so rejected
  candidates neither use attempts nor hide later ones. Positions still open at
  tape end are marked at the final close as `end-of-data`, not a strategy exit.
  H4-only trailing remains coarse, not tick-accurate. Balance scaling with
  crossover admission is refused until a unified sizing/admission pass exists.

User-run commands (no backtest is started by selecting a preset):

```powershell
$env:PYTHONPATH="python"
uv run python -m quant.backtest --batch --base-config configs/_base_crossover.yaml
uv run python -m quant.monitor --trade --dry-run --account demo --base-config configs/_base_crossover.yaml
```

`_base.yaml` = shared defaults, the single source of truth for strategy
and risk. The engine and the live trader read the SAME keys from it.

Pair files (e.g. `configs/EURUSD.yaml`) set `symbol`, `pip_size` and a
`costs:` block with SAMPLED values from `quant.spreadcheck`.
Pair-level `strategy:` / `risk:` blocks are IGNORED by design (locked by
`test_load_pairs_strategy_comes_only_from_base`). A pair's `base:` /
comment lines are informational only.

## Override order (last wins)

1. `_base.yaml strategy:` — only source of strategy truth (pair copies ignored)
2. `_base.yaml risk:` / `limits:` — engine portfolio pass + live enforce the same keys
3. pair yaml `costs:` — sampled live-cost values
4. backtest CLI flags (`--spread-pips`, `--flat-swaps`, `--scope-low/--scope-high`,
   `--weekly-loss-r`, `--max-cost-ratio`, `--ma-only`, ...) — sensitivity sweeps

## Opposite-crossover exit

`strategy.open_trade.use_crossover_exit` enables an exit when the configured entry
EMAs cross against an open position on a closed execution candle. It is enabled
in the active base and crossover preset, but defaults off when absent. It requires
the crossover-memory mode. It uses the raw crossover, even if bias is temporarily
neutral; it does not wait for EMA separation or a recovery entry.

Backtests fill at the next candle's open with normal exit costs. Earlier SL/TP/trail
exits take priority, including protective levels already crossed at the exit open.
There is no invented next-open fill when the final candle has no following bar.
Live closes only the matching magic/ticket at the next available market quote,
even outside entry hours, blackout dates or weekly entry halts. Dry-run plans
send nothing. No reverse entry is attempted in the same management pass; later
entries still need a fresh recovery and the normal guards.

Confirmed partial closes retry only the refreshed remaining volume. Unknown close
outcomes are persisted and block another close send until broker reconciliation;
existing broker SL/TP remain. Do not delete memory to bypass an unknown order.
This exit needs Python/MT5 online; existing broker-side stops remain the fallback.

## Automatic backtest comparison

Every new completed backtest compares its final portfolio results with the
previous comparable run and the previous best comparable run. Console output
and the HTML report show differences in net profit, MTM drawdown, win rate and
profit factor; `comparison.json` saves the snapshot.

`BEST.txt` inside the winning folder marks the highest net profit after costs
within the configured MTM drawdown ceiling. One current marker is kept per
comparison group; folders are never renamed. Profit ties prefer lower drawdown,
then the earlier completion. Reports remain snapshots, so an older report may
say "best at comparison time" after its marker has moved to a newer winner.

```yaml
backtest_comparison:
  enabled: true
  max_drawdown_pct: null  # inherit benchmarks.max_dd_pct.ok, or good if ok is absent
```

The active ceiling is currently **50% of starting balance**, inherited from the
existing benchmark; this is not a recommendation to accept a 50% loss. Set an
explicit value to tighten it. CLI overrides: `--no-compare-results` disables
comparison/marker updates; `--compare-results` enables them;
`--comparison-max-dd-pct 25` selects a 25% ceiling for that run.

Comparable runs must match actual source-price fingerprints/dates, pairs,
timeframes, position-check feeds, starting balance, effective pair costs, sizing
budget and drawdown ceiling. Strategy entry/exit/admission settings may differ.
Paths alone are never trusted as evidence of unchanged prices. Input hashes are
recorded from frames already loaded by the worker; no extra historical download
or terminal connection is needed.

Only explicitly completed runs with all requested pairs, intact trade/summary
artifacts and MTM drawdown can win. Failed/incomplete/old unverified folders are
excluded, not guessed. The first new comparable run establishes the baseline;
zero-trade runs cannot win. Missing drawdown ceilings or MTM metrics cannot earn
a marker. Infinite profit factors remain valid, with undefined deltas shown N/A.
User-authored `BEST.txt` files are not overwritten. Publication is serialized
across simultaneous backtests; comparison failures never discard trading results.

This is offline reporting only. It changes no signals, fills, costs or live
behavior. A best marker is relative to the tested group, not proof of future
profitability; it can still be a losing result if all qualifying runs lost.

## Gate codes

These codes appear in the panel ENTRY column and in journal/trades rows.
Funnel order = `signals.FAIL_ORDER` (first gate that fails writes the skip
reason). The yaml lists gates in reading order, not funnel order.

| Code | In the yaml | Meaning |
|---|---|---|
| B1 | `strategy.bias` | bias chart fast EMA above/below slow EMA; HR1 and optional EMA separation can veto it |
| HR1 | `strategy.bias` (`hr1: a/b/c`) | price on the trend side of the bias chart's slow EMA (a = close / b = body / c = whole candle) |
| HR2 | `strategy.entry` | signal candle conviction: right color AND body >= `min_body_ratio` of the range |
| HR3 | `strategy.entry` | signal candle not too big (never chase a giant bar) |
| HR4 (+guard) | `strategy.entry` | swing structure intact: recent higher-low (LONG) / lower-high (SHORT); guard = no NEW lower-low since the swing |
| EXT | `strategy.entry` | not stretched: close stays close to the entry chart's fast EMA |
| E1-setup | `strategy.entry` | pullback happened: within `lookback` entry bars price touched the entry chart's slow EMA without breaking down |
| E1-trigger | `strategy.entry` | the fire button: the bar closed beyond the fast EMA AND beyond the previous bar's high (LONG) / low (SHORT) |
| W1 | `strategy.entry` | entry EMA20/EMA100 must agree with Daily bias. Any enabled pattern qualifies: trend-side wick touch (`w1_touch_from_trend_side`), cross back to trend side (`w1_cross_from_other_side`), or optional pullback cross into the EMA gap (`w1_cross_into_gap`, default false). Pullback cross opens strictly on the trend side and closes strictly between the configured entry EMAs; trade direction still follows the bias. `w1_pen_atr` applies only to the original patterns. HR2 must be off for pullback crosses; other enabled gates still apply. All patterns off blocks W1; `use_w1: false` bypasses W1 entirely. Older configs retain `w1_open_side` when no modern patterns are selected. |

`timeframes.position_checks: M1` selects the feed for open-trade checks.

`timeframes.execution` / `timeframes.regime` choose the timeframe pair.
Supported execution->bias combos: `H1->H4`, `H4->D1`, `H1->D1`,
`H1->H1`, `H4->H4`, and `D1->D1`.
For same-timeframe mode, set both keys to the same value. Bias and entry use
the same closed candle, with their own configured indicator periods. There is
no separate higher-timeframe trend filter. Same-timeframe H4/D1 modes require
the corresponding broker export even with broker CSV mode disabled.
In broker CSV mode, `backtest_data.position_checks: H1` uses hourly checks
independently of execution/bias. Select the execution timeframe (`H1`, `H4`,
or `D1`) explicitly for coarse checks instead. Intrahour order remains unknown.
Broker CSV mode loads the actual exported execution and bias charts, without
resampling. H1/D1 uses H1 entries and Daily bias; only Daily bars proven closed
by a following broker Daily open are available at the H1 signal close.
Live fetches both configured charts directly with closed bars only.
With broker CSV mode disabled, legacy H1/H4 still derives H4 from H1. Both
Daily-bias combos require an exported `<SYM>_D1.csv` beside H1; H4 entries also
require `<SYM>_H4.csv`. Missing files stop the run, never fabricate Daily prices.
Anything else fails the config check.

## Remembered-pullback entry (separate optional mode)

In `strategy.entry`, set `use_recovery_entry: true` to replace the W1/E1/HR/EXT
candle gates with a remembered setup. It ships false, preserving the old gates.
The configured entry EMAs determine alignment (20/100 in the active H4 config).
The older H1 preset still has entry EMA20/50: choose `entry_ema_slow_period: 100`
if using that preset for this new 20/100 experiment.

### Zone-memory mode

Set `recovery_use_zone_memory: true` (enabled in the active base config).
Set false to restore the timed rules below; omitted keys default false so saved
runs keep their original behavior.

- A close between the configured entry EMAs, including equality, arms the setup.
  Wick-only touches do not arm it. Entry EMAs must still align with the trade.
- Inside closes keep the setup alive without a candle-count limit.
- The first later close strictly above the previous candle's high (LONG), or
  below its low (SHORT), triggers and consumes the setup, even if entry is blocked
  by hours, risk, costs, bias or another execution guard. It cannot re-arm itself.
- That recovery close may stay inside the gap or exit past the fast EMA toward
  the trend. If the first outside close does not recover, the chance is lost;
  later outside candles cannot chase it. A fresh inside close is needed to re-arm.
- An EMA crossover/tie always cancels. `recovery_cancel_beyond_slow: true` also
  cancels on a close beyond the slow EMA against the trade. Set false to keep an
  already armed setup alive there until its first recovery; outside closes still
  cannot arm a fresh setup. That recovery can trigger even beyond the slow EMA,
  so disabling this guard permits buys below both EMAs or sells above both EMAs.
  Exiting toward the trend without recovery still loses the opportunity.
  `recovery_expiry_bars` and `recovery_use_wick` do not control zone mode.
- State is replayed from the supplied closed-bar history (normally 400 candles),
  not stored separately. No new order-sending path is introduced.

### Timed mode (`recovery_use_zone_memory: false`)

- LONG: close below fast EMA or wick touching/crossing it arms the setup, whatever
  the candle's opening side. SHORT mirrors this (close above fast EMA or touch).
- `recovery_use_wick: true` enables wick-touch setups and refreshes. Set false
  for close-based setups only; a qualifying close still counts even if that
  candle also touches the EMA. Defaults true to preserve existing behavior.
- A later close strictly above the immediately previous candle's high (LONG),
  or below its low (SHORT), triggers. No EMA-position/body requirement is added.
  The next candle may trigger; a wick-only break or equality does not.
- `recovery_expiry_bars: 4` allows the next through fourth closed candle. Must
  be a positive integer smaller than available entry history (400 bars in normal
  callers). Each fresh qualifying close/touch resets expiry.
- Entry-EMA crossover/tie clears the setup. Realignment needs a fresh setup.
  `recovery_cancel_beyond_slow: true` also cancels on a close strictly beyond
  the slow EMA against the trade; false disables only that cancellation.
- A trigger consumes its setup, even if later execution guards refuse entry;
  signals are not queued. Pending state is reconstructed from closed history,
  so restarts cannot revive an already consumed signal within that history.
- Higher-timeframe bias, next-open execution, ATR SL/TP, costs, sizing, entry
  hours, trade limits and restart order stamps remain in force. Pending setup
  cancellation does not close existing positions. Reports label `recovery_break`.

## The OFF-gate rule

Every `use_x: false` = that gate auto-passes and its knobs are ignored.
The keys STAY in `_base.yaml` even for off gates — never comment them out:
the engine's code defaults (`signals.py: DEFAULTS`) differ from the yaml
values (`use_ext/use_hr3/use_hr4 = True`, `use_trail = True`,
`lookback = 12`, `warmup_bars = 300`, `trail_r = 1.0`).

The `bias_ema_*_period` / `bias_atr_period` values belong to the regime chart;
`entry_ema_*_period` / `entry_atr_period` belong to the execution chart. These
keys stay the same if you switch timeframes. `warmup_bars` applies to both.
The `execution` section in `_base.yaml` describes timing; its keys are not
runtime switches. The backtest's `--atr-n` overrides `entry_atr_period`.
Old run reports still accept the older H1/H4-named keys. Existing ledger and
journal CSV headers keep their old names; their values follow the configured
entry and bias chart periods.

## Stop sizing (widen the stop instead of adding lots)

`risk.default_lot` is the base size for every trade (default 0.01). Normal
sizing adds 0.01 lots at a time: a 0.02 base can become 0.03, then 0.04,
until risk reaches the scope floor. If that size exceeds the ceiling, skip.
Never reduce below the base to squeeze a trade into the band. With both scope
sides disabled, use the base unchanged. Balance scaling also respects the base.

`risk.stop_sizing` in `_base.yaml` decides how a trade reaches the minimum
risk (`risk.sizing_scope_usd.low`):

| Mode | What happens |
|---|---|
| `widen_stop_to_scope: false` (default) | trade MORE lots on the ATR stop until 1R reaches `low`; the stop stays `stop_atr x ATR` |
| `widen_stop_to_scope: true` | use `risk.default_lot` and widen the stop until that lot risks `low`; the take profit moves out with it, so the R:R is unchanged |

In the widened mode a trade is refused when the needed stop is more than
`max_stop_atr` x ATR away from price (funnel gate `stopcap`) or when the fixed
lot already risks more than `sizing_scope_usd.high` (gate `scope`). The mode
cannot run together with `scale_lot_with_balance` (fixed lot vs compounding
lot): both the backtest and the live loop refuse that combination.

With `increase_lots_if_widening_fails: true`, a widening-cap refusal tries
more lots at the original stop, starting at the same base. All risk and cost
checks still apply.

CLI overrides: `--default-lot` (base size in all modes), `--widen-stop`
(force the mode on), `--stop-max-atr`. `--stop-lot` is a legacy alias for
`--default-lot`; `--lot` remains an exact diagnostic override. Older configs
without `risk.default_lot` may still use `stop_sizing.fixed_lot` as the base.

## Units cheat-sheet

| Keys | Unit |
|---|---|
| `bias_ema_*_period`, `entry_ema_*_period`, `bias_atr_period`, `entry_atr_period` | periods (bars on their own chart) |
| `sep_atr` | bias chart ATR multiples |
| `touch_atr`, `breakdown_atr`, `ext_atr`, `max_body_atr`, `edge_atr`, `stop_atr` | entry chart ATR multiples |
| `tp_mult`, `trail_r`, `be_trigger_r` | R multiples (share of the stop distance) |
| `min_body_ratio` | body / range share (0-1) |
| `spread_points` | POINTS (20 pts = 2.0 pips) |
| `slippage_pips`, `be_buffer` | PIPS |
| `swap_long_per_0_01`, `swap_short_per_0_01` | account-ccy per 0.01 lot per night |
| `commission_per_lot` | USD per 1.0 lot |
| `sizing_scope_usd.low/high` | USD — every trade's 1R must land inside |
| `default_lot` | base lots, at least 0.01 and in 0.01-lot steps |
| `scale_lot_with_balance` | OFF = fixed sizing (rents the scope floor as the aim). ON = compounding: 1R aims at `balance_risk_pct` % of the account balance at entry, then the SAME scope fence checks it. Wins grow the lot, drawdown shrinks it — never doubles after a loss (not martingale) |
| `balance_risk_pct` | % of the account balance per trade; read only when `scale_lot_with_balance: true` (must be > 0 then) |
| `weekly_loss_r` | R — backtest weekly halt (week's CLOSED R total) |
| `weekly_loss_pct` | % of week-start equity (live/panel halt only) |
| `max_cost_ratio` | round-trip cost as a share of the stop distance |
| `max_total_positions`, `max_ccy_net`, `max_trades_per_day` | counts |
| `max_trades_per_pair_per_week` | actual entries per pair per UTC Monday-start week; 0 disables |
| `max_trades_per_week` | actual entries across ALL pairs per UTC Monday-start week; 5 in active config and presets, 0 disables |
| `disable_pair_after_daily_loss` | true blocks new entries for a pair after a fully closed net loss, until the next UTC day; false disables |
| `lookback`, `pivot_n`, `warmup_bars` | bars |

Cost currency: the swaps/commission unit is `account.currency` (USD).
Entry limits count accepted entries only, not signals, rejected orders or dry-run
plans. Partial fills of one live position count once. Losses include entry/exit
costs and are booked on the closing day, even if opened in a previous week.
Existing positions keep their protection; unrelated pairs may still enter.
Live state is recovered from broker deals after restart; unavailable history
blocks new entries without stamping the bar, so it can retry. Today's closing
positions use full position history, including entry fees and manual closes.
The portfolio weekly cap blocks all new entries after the quota, but does not
close or stop managing existing positions. Live uses our magic number on the
selected account, recovering from broker deals and a saved confirmed-entry count;
same-cycle fills count immediately, even before the next history refresh.
The week resets Monday 00:00 UTC (08:00 Malaysia), not local Monday midnight.
In backtests with a weekly cap or either pair guard enabled, daily and portfolio caps run in one
time-ordered pass: rejected trades consume no daily/weekly quota and their
exits cannot trigger a loss block. Omitted entry-limit keys default to disabled.
Balance-scaling backtests with a weekly cap or either pair guard enabled are refused for now:
their later scaling pass can reject trades, which would invalidate guard state.
Fixed-dollar sizing is the active plan; unified percentage sizing is deferred.
Triple swap is 3x on the Wednesday-night rollover; the engine approximates
it as the first bar after Wed 21:xx UTC.

## Sampling live costs (pair `costs:` blocks)

Read-only: `uv run python -m quant.spreadcheck` — sample at several hours,
then write the result into the pair yaml with the sample date in a comment.
Demo spreads move; re-sample per session.

## M1 data

### Active broker CSV source (offline only)

`backtest_data.use_broker_csv: true` selects `backtest_data.broker_csv_dir`
(`data/pepperstone`). `broker_server_clock: new_york_plus_7` documents/enforces
the supported Pepperstone source clock: UTC+2 winter / UTC+3 US DST; normalized
CSVs are UTC. Active broker CSV checks use H1 for every pair, independently of
execution/bias, overriding `timeframes.position_checks` for offline tests only.
`backtest_data.position_checks` accepts H1 or the execution timeframe, not vendor M1.
Setting the switch false restores legacy selection; explicit research CLI opt-in
overrides it. No live/strategy/cost/risk switches change.

This mode uses broker H4/D1, H1/H4 or H1/D1, never vendor H1/M1. Source originals are archived in
`data/pepperstone/raw/`; normalized files and the manifest live one level above.
Missing active pairs/check feeds or failed chart checksums are errors. Broker
conversion feeds follow the check timeframe; closes are available only after the
following open. Range exits book at check-candle close; execution-chart close
marks are still used for drawdown.
Both-stop-and-target candles count as stops; trailing/BE precision is limited.
Every pair's final 2025-12-31 20:00 server-time H4 candle is absent, explicitly
warned, not filled. See RUNBOOK for source/timezone, coverage and run commands.
H1 is a separate `manifest_h1.json` extension, pinned to the existing base manifest.
Adding it does not change old H4 dataset identities. H1 runs pin both manifests.
H1 OHLC aggregates are audited against actual H4 exports, never substituted for
them; partial hourly coverage is warned and never filled.

An explicit **vendor-derived research** alternative now exists:
`mkdata --research --all-existing --src data --out-dir data/vendor_derived_2015_2025`.
It builds H4/D1 directly from M1 using stored timestamps/midnight boundaries,
not verified broker session boundaries. It retains partial periods with observed
minute counts, omits empty periods, and writes source/coverage/integrity metadata.
Only `backtest --research-data-dir ...` or `dice_probe --research-data-dir ...`
may opt into these files; broker/live defaults do not change. `--data-dir` locates
matching original H1/M1 and conversion feeds. No strategy YAML changes are needed.
See RUNBOOK for commands, explicit reference parity, source assumptions and the
unseen-period warning before running the full 2015-2025 dataset.

For broker-consistent history, `quant.mkdata --broker` exports the configured
execution/regime/position-check feeds plus H1 and needed USD conversion feeds.
It supports standard broker timeframe names without changing the engine's
allowed strategy combinations. Use `--start`, exclusive `--end`, and either
`--symbol` or `--batch`; `--plan` previews without connecting/writing.
Export includes configured indicator warmup, validates candles, reports gaps,
and writes source/export/coverage sidecars. Existing output is refused unless
`--overwrite` is explicit. See `docs/RUNBOOK.md` before replacing vendor files;
broker data availability and M1 retention can limit the usable date range.

Open-trade checks (stop/TP/trail) run on the M1 feed when
`timeframes.position_checks: M1`. If a pair has no M1 rows for an hour,
the checks silently fall back to H1.

Build M1 once per pair, before tick trails matter:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --symbol EURUSD --m1-csv
```

The all-pairs parallel loop lives in `docs/RUNBOOK.md`.
