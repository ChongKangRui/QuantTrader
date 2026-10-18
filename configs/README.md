# Configs — `_base.yaml` and the pair files

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
   `--weekly-loss-pct`, `--max-cost-ratio`, `--ma-only`, ...) — sensitivity sweeps

## Gate codes

These codes appear in the panel ENTRY column and in journal/trades rows.
Funnel order = `signals.FAIL_ORDER` (first gate that fails writes the skip
reason). The yaml lists gates in reading order, not funnel order.

| Code | In the yaml | Meaning |
|---|---|---|
| B1 | `strategy.bias` | the bias family: H4 fast EMA above/below slow + HR1 band. Baseline = B1 |
| HR1 | `strategy.bias` (`hr1: a/b/c`) | H4 watchman: price flowing past the H4 slow EMA (a = close / b = body / c = whole candle) |
| HR2 | `strategy.entry` | signal candle conviction: right color AND body >= `min_body_ratio` of the range |
| HR3 | `strategy.entry` | signal candle not too big (never chase a giant bar) |
| HR4 (+guard) | `strategy.entry` | swing structure intact: recent higher-low (LONG) / lower-high (SHORT); guard = no NEW lower-low since the swing |
| EXT | `strategy.entry` | not stretched: close stays close to the H1 fast EMA |
| E1-setup | `strategy.entry` | pullback happened: within `lookback` bars price touched the H1 slow EMA WITHOUT closing below it (zone held) |
| E1-trigger | `strategy.entry` | the fire button: the bar closed beyond the fast EMA AND beyond the previous bar's high (LONG) / low (SHORT) |

`timeframes.position_checks: M1` selects the feed for open-trade checks.

## The OFF-gate rule

Every `use_x: false` = that gate auto-passes and its knobs are ignored.
The keys STAY in `_base.yaml` even for off gates — never comment them out:
the engine's code defaults (`signals.py: DEFAULTS`) differ from the yaml
values (`use_ext/use_hr3/use_hr4 = True`, `use_trail = True`,
`lookback = 12`, `warmup_bars = 300`, `trail_r = 1.0`).

## Units cheat-sheet

| Keys | Unit |
|---|---|
| `h4_atr_n`, `atr_n` | ATR periods (bars) |
| `sep_atr` | H4 ATR multiples |
| `touch_atr`, `breakdown_atr`, `ext_atr`, `max_body_atr`, `edge_atr`, `stop_atr` | H1 ATR multiples |
| `tp_mult`, `trail_r`, `be_trigger_r` | R multiples (share of the stop distance) |
| `min_body_ratio` | body / range share (0-1) |
| `spread_points` | POINTS (20 pts = 2.0 pips) |
| `slippage_pips`, `be_buffer` | PIPS |
| `swap_long_per_0_01`, `swap_short_per_0_01` | account-ccy per 0.01 lot per night |
| `commission_per_lot` | USD per 1.0 lot |
| `sizing_scope_usd.low/high` | USD — every trade's 1R must land inside |
| `weekly_loss_pct` | % of week-start equity |
| `max_cost_ratio` | round-trip cost as a share of the stop distance |
| `max_total_positions`, `max_ccy_net`, `max_trades_per_day` | counts |
| `lookback`, `pivot_n`, `warmup_bars` | bars |

Cost currency: the swaps/commission unit is `account.currency` (USD).
Triple swap is 3x on the Wednesday-night rollover; the engine approximates
it as the first bar after Wed 21:xx UTC.

## Sampling live costs (pair `costs:` blocks)

Read-only: `uv run python -m quant.spreadcheck` — sample at several hours,
then write the result into the pair yaml with the sample date in a comment.
Demo spreads move; re-sample per session.

## M1 data

Open-trade checks (stop/TP/trail) run on the M1 feed when
`timeframes.position_checks: M1`. If a pair has no M1 rows for an hour,
the checks silently fall back to H1.

Build M1 once per pair, before tick trails matter:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --symbol EURUSD --m1-csv
```

The all-pairs parallel loop lives in `docs/RUNBOOK.md`.
