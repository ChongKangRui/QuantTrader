# Configs — `_base.yaml` and the pair files

## Presets (kept inert next to `_base.yaml`)

`_base_*` filenames are skipped by the pair loader, so full copies can sit
here safely. The engine reads `configs/_base.yaml` ONLY:

- `configs/_base_h1h4.yaml` — the older H1->H4 preset; copy it to
  `_base.yaml` to switch back.
- `configs/_base_h4d1.yaml` — the "Daily bias / H4 entry" strategy: W1 gate
  on with both `w1_touch_from_trend_side` and `w1_cross_from_other_side` on,
  E1-setup/trigger + HR2 off, `tp_mult: 2.5`,
  trail off. NOTE inside: the spec's "max 2 per pair per week" and "a loss
  disables the pair for the day" are not built — no knobs exist yet.
- Apply one: `Copy-Item configs/_base_h4d1.yaml configs/_base.yaml -Force`
- Revert:    `Copy-Item configs/_base_h1h4.yaml configs/_base.yaml -Force`

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
| W1 | `strategy.entry` | entry EMA20/EMA100 must agree with Daily bias. With the two H4/Daily switches present, require a close on the trend side of EMA20 plus either an open on the trend side with a touch (`w1_touch_from_trend_side`) or an open on the other side with a cross (`w1_cross_from_other_side`). Both work for longs and shorts; 0 on `w1_pen_atr` allows an exact touch. Older configs without those switches retain `w1_open_side`. |

`timeframes.position_checks: M1` selects the feed for open-trade checks.

`timeframes.execution` / `timeframes.regime` choose the timeframe pair.
Two locked combos only: `H1->H4` and `H4->D1` — same gates, same numbers,
bigger bars. H4/D1 backtests require `data/<SYM>_H1.csv`, plus broker-exported
`data/<SYM>_H4.csv` and `data/<SYM>_D1.csv` from the same broker, with UTC
timestamps; missing files stop the run. H1/H4 backtests still derive their H4
grid from H1 (legacy behavior; broker phase can differ). Live fetches broker
bars directly. Anything else fails the config check.

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
| `disable_pair_after_daily_loss` | true blocks new entries for a pair after a fully closed net loss, until the next UTC day; false disables |
| `lookback`, `pivot_n`, `warmup_bars` | bars |

Cost currency: the swaps/commission unit is `account.currency` (USD).
Pair limits count accepted entries only, not signals, rejected orders or dry-run
plans. Partial fills of one live position count once. Losses include entry/exit
costs and are booked on the closing day, even if opened in a previous week.
Existing positions keep their protection; unrelated pairs may still enter.
Live state is recovered from broker deals after restart; unavailable history
blocks new entries without stamping the bar, so it can retry. Today's closing
positions use full position history, including entry fees and manual closes.
In backtests with either pair guard enabled, daily and portfolio caps run in one
time-ordered pass: rejected trades consume no daily/weekly quota and their
exits cannot trigger a loss block. Older configs omit both keys to disable them.
Balance-scaling backtests with either pair guard enabled are refused for now:
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
CSVs are UTC. `backtest_data.position_checks: H4` is the explicit coarse mode,
overriding `timeframes.position_checks` for offline broker CSV tests only.
Setting the switch false restores legacy selection; explicit research CLI opt-in
overrides it. No live/strategy/cost/risk switches change.

This mode uses H4/D1 only, no vendor H1/M1. Source originals are archived in
`data/pepperstone/raw/`; normalized files and the manifest live one level above.
Missing active pairs or failed chart checksums are errors. Broker H4 closed-price
conversion feeds replace H1 helpers, with closes unavailable until the following
open. Coarse exits book at candle close; H4 close marks are used for drawdown.
Both-stop-and-target candles count as stops; trailing/BE precision is limited.
Every pair's final 2025-12-31 20:00 server-time H4 candle is absent, explicitly
warned, not filled. See RUNBOOK for source/timezone, coverage and run commands.

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
