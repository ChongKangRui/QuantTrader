# Strategy Spec: Multi-Pair Trend System (H4 bias, H1 entry) on MT5

Status: DRAFT v0.9. Every rule below is a **hypothesis to be tested**, not a proven edge.
`[TEST]` = has a range to evaluate. `[DECIDE]` = needs your choice before coding. Parked ideas sit in section 15 and are NOT active rules.

Changes from v0.8:
- **No-trade windows** (section 8): `limits.no_trade_ranges`, a list of `{start, end}` MM-DD ranges that repeat every year (wrap-safe across New Year). No NEW entries whose fill day falls inside a window; open trades keep being managed.
- **Tick-like position checks** (sections 3 and 7): stop / target / breakeven / trail are checked on the M1 feed (`timeframes.position_checks: M1`), not once per H1 bar. Signals, bias and fills stay on H1.

Changes from v0.7:
- **No time cap on trades.** The 120-bar hard time stop is removed. A trade ends at its stop, its target, or an optional bias-flip / weekend exit.
- **T1 is one profit-trail rule** (section 7). The stop keeps its initial level until the best profit reaches `trail_r` (trigger point), then follows the best price at `trail_r` x risk. Breakeven is now an optional separate leg (`use_be`, off).
- **Same fixed spread on both sides** (section 10): longs pay it entering, shorts pay it exiting.
- **Portfolio-wide daily entry cap** `limits.max_trades_per_day` (section 8).
- `configs/_base.yaml` strategy block is split into BIAS / ENTRY / RISK MANAGEMENT. Every gate and exit leg has a `use_*` toggle.

Changes from v0.6:
- **E1 setup made exact** (section 5): per-bar EMA50 and ATR, the 12-bar window includes the signal bar, lows may pierce below EMA50, only closes are floored at `EMA50 - breakdown_atr x ATR`.
- **Stale-HL guard** added to HR4 (`hl_guard`, default on): skip if any low since the pivot is below it. Own funnel column.
- Zero-range guard, warmup bars, H1 EMA lengths and `breakdown_atr` moved into config; fill-time re-check of the extension cap and caps stated.
- **New section 8A: loss limits and drawdown rules** (proposed, `[DECIDE]`/`[TEST]`), plus streak math. The locked rules in section 8 are unchanged.
- Section 11 items 14-16 added (calibrating circuit breakers, pair pause test, streak Monte Carlo). Section 13 kill switch now points to 8A.

Earlier changes carried: H1-based ATR, HR4 edge = previous H1 HL/LH, extension cap, S1 baseline stop, BE at +1R then trail (v0.6); baseline bias back to original B1, HR5 parked (v0.5); signal funnel (v0.4); locked risk rules (v0.3).

---

## 1. Goal and constraints

- Trade with the trend on about 10 FX pairs, entries on H1, bias from H4.
- Typical holding 2-3 days. No hard time cap: a trade runs until its stop, target, or an optional bias-flip / weekend exit.
- Target 1:3 reward-to-risk. Breakeven (+1R) and the T1 profit trail are toggles (`use_be`, `use_trail`) — both OFF in the R2 working baseline (section 7).
- Per-trade risk comes from `risk.sizing_scope_usd` in `_base.yaml`: actual 1R lands inside the low-high band (2.5-3.6 USD); the old fixed USD 3 cap is retired (section 8, section 12 sizing rule).
- Python on Windows, `MetaTrader5` package, demo account first.
- Success is judged on **expectancy in R after costs**, drawdown and robustness, not win rate or signal count.

## 2. Universe

Candidates (finalize after a correlation check):
`EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, EURJPY, GBPJPY, EURGBP, AUDNZD`

- `[DECIDE]` Final 10 and broker symbol names.
- Sanity check: print signals per pair per month. Expect well over 4-5 a month across the portfolio. Far fewer = rules too strict (the hard rules below stack, so watch this closely).
- **Signal funnel (first output of every backtest run, before any P&L):** count candidate H1 bars surviving each rule in order: H4 bias (EMA stack, plus separation if on) -> HR1 -> HR2 -> HR3 -> HR4 (edge, including the stale-HL guard) -> extension cap -> E1 setup -> E1 trigger (or E2) -> scope sizing band / min lot / cost filter -> risk rules (1 open per pair, 1 entry per pair per day, `max_trades_per_day` across the portfolio, `max_total_positions` open max, loss limits in 8A). Report per pair and per month. This shows exactly which rule kills the trade count. If a test variant such as HR5 is switched on, and for each enabled optional filter, give it its own column.

## 3. Data and timing conventions (avoid lookahead)

- Source: MT5 H1 and H4 history including the per-bar `spread` field, same broker as live. Cross-check against a second source.
- MT5 bar timestamps are bar **open** time in broker server time. Derive bar boundaries from data.
- **Signals are evaluated only on H1 bar close. Fills happen at the next H1 bar open.**
- H4 bias at H1 time `t` uses the **last fully completed H4 bar** only (never the forming one).
- EMA = standard exponential MA. ATR and RSI = Wilder smoothing. **H1 ATR period = `atr_n` (default 7)**. H4 ATR (bias separation and the optional H4 filters only) and RSI use period 14.
- Candle terms: body = |close - open|, range = high - low. A bar with range = 0 never qualifies as a signal bar.
- Warmup: ignore the first `warmup_bars` bars of each series so the EMAs and ATR have settled (code default 300; the current `_base.yaml` value is 100).
- **Position checks are tick-like.** With `timeframes.position_checks: M1` (the default), everything that manages an open position — stop, target, breakeven, trail — is checked on the minute (M1) feed built from the same data source (`data/<SYM>_M1.csv`). An H1 bar with no M1 rows falls back to H1 checks for that bar only. Backtest and live share these conventions.

## 4. H4 bias (direction filter)

### HR1 (hard rule): H4 candle must be on the trend side of EMA(h4_ema_slow)
The last completed H4 candle must satisfy, for longs (mirror for shorts), one of `[TEST]`:
- **HR1a (baseline):** close > EMA(`h4_ema_slow`, H4)
- **HR1b:** body fully above: min(open, close) > EMA(`h4_ema_slow`, H4)
- **HR1c (strict):** whole candle above: low > EMA(`h4_ema_slow`, H4)

Note: HR1c removes most signals during pullbacks and may leave too few trades. HR1 overlaps with the `h4_ema_fast > h4_ema_slow` condition but is not identical: during a pullback the close can dip under the slow line while the fast line is still above it, and HR1 reacts first.

### Bias definition
Baseline **B1: EMA(20/50) on H4** — the MA periods are now CONFIG keys, not code
constants: `h4_ema_fast = 20`, `h4_ema_slow = 50`, `h4_atr_n = 14` in
`configs/_base.yaml` (locked defaults; changing them is its own declared
change-set). Long bias when all are true on the last completed H4 bar:
1. EMA(`h4_ema_fast`) > EMA(`h4_ema_slow`)
2. HR1 satisfied
3. (EMA(`h4_ema_fast`) - EMA(`h4_ema_slow`)) >= `sep_atr` x ATR(`h4_atr_n`, H4)   `[TEST]` 0.0 / 0.2 / 0.4 (default 0.3)

Short bias is the mirror. Otherwise NEUTRAL (no new entries). Variant **B2** uses EMA(100) instead of EMA(50) for the slow line (and HR1 against that line). Comparison leg (not baseline): `use_atr_sep: false` drops the separation gate, HR1 and NEUTRAL — pure `h4_ema_fast`/`h4_ema_slow` direction, for ablation only.

On H4, EMA20 is about 3 days, EMA50 about 8 days, EMA100 about 17 days.

Test variant (not baseline): **HR5 body-EMA agreement**, which adds "last completed H4 candle direction matches the trade" as a 4th condition. Off by default, see section 15.

### Optional regime filters `[TEST]` (add one at a time)
- **Efficiency Ratio (Kaufman), H4, length 20:** ER = |close_t - close_t-n| / sum(|close_i - close_i-1|). Range 0-1, how straight the path was. Trade only if ER >= threshold (try 0.20 / 0.30 / 0.40).
- **ADX(14, H4) >= 20 or 25.** ER and ADX overlap, so test them separately, not stacked.
- **EMA50 slope:** (EMA50_now - EMA50_6 bars ago) / ATR(14, H4) >= `slope_min` in the trade direction (try 0.2 / 0.5).
- **Volatility regime:** skip when ATR(`atr_n`, H1) is in the bottom 10% or top 10% of its trailing 100-day range (dead market or news spike).

## 5. H1 entry

All ATR in sections 5-7 means ATR(`atr_n`, H1). Everything is evaluated at the close of the H1 signal bar. Fill is at the next H1 open. `signals.py` evaluates at the signal close; the backtest and execution layers re-check against the actual fill (see "Fill-time re-check").

### Parameters for sections 5-7 (put all in config)

| Parameter | Default | Test range | Used in |
|---|---|---|---|
| `atr_n` | 7 | 7 / 14 | every H1 ATR rule |
| `h1_ema_fast` | 20 | config | extension cap, E1 trigger |
| `h1_ema_slow` | 50 | config | E1 setup |
| `warmup_bars` | 300 | fixed | all indicators |
| `stop_atr` | 1.5 | 1.0 / 1.5 / 2.0 | S1 stop |
| `tp_mult` | 3.0 (R) = 4.5 ATR | 2 / 3 | take profit |
| `ext_atr` | 1.5 | 1.0 / 1.5 / 2.0 | extension cap |
| `edge_atr` | 1.5 | 1.0 / 1.5 / 2.0 | HR4 |
| `pivot_n` | 3 | 3 / 5 | HL / LH detection |
| `hl_guard` | on | on / off | HR4 stale-HL guard |
| `min_body_ratio` | 0.5 | 0.4 / 0.5 / 0.6 | HR2 |
| `max_body_atr` | 1.5 | 1.0 / 1.5 / 2.0 | HR3 |
| `lookback` | 12 | 8 / 12 / 20 | E1 setup |
| `touch_atr` | 0.5 | 0.25 / 0.5 / 0.75 | E1 setup |
| `breakdown_atr` | 1.0 | 0.75 / 1.0 / 1.5 | E1 setup |
| `be_trigger_r` | 1.0 | 1.0 / 1.5 / off | breakeven |
| `be_buffer` | 0 | 0 / 0.05R | breakeven |
| `trail_r` | 1.0 | 0.5 / 1.0 / 1.5 | trailing (R of initial risk) |

### Hard rules on the signal candle
- **HR2 body ratio:** body / range >= `min_body_ratio` (range must be > 0), and the candle direction matches the trade (close > open for long).
- **HR3 body size cap (not too aggressive):** body <= `max_body_atr` x ATR. Optional (off): range <= 2.5 x ATR.
- **HR4 edge proximity (stay close to the previous HL / LH):**
  - Longs: `HL` = the most recent confirmed H1 pivot low centered at or before `t - pivot_n` (a bar whose low is strictly lower than the `pivot_n` bars on each side; ties are not pivots). Require `close > HL` and `close - HL <= edge_atr x ATR`.
  - Shorts: `LH` = the most recent confirmed H1 pivot high, strictly higher than the `pivot_n` bars on each side. Require `close < LH` and `LH - close <= edge_atr x ATR`.
  - A pivot is only known `pivot_n` bars after it forms, so it lags by that many bars.
  - **Stale-HL guard (`hl_guard`, default on):** skip the signal if any low since the HL bar (through the signal bar) is below the HL (shorts: any high above the LH). This catches a lower low that is not yet a confirmed pivot, where the higher-low structure has already broken. Test it on/off via the funnel column.
  - Optional structure check (default off): the HL must be higher than the previous pivot low (true higher low); mirror for shorts.
  - Meaning: the leg is young, not already stretched far from where the pullback ended. With `edge_atr = stop_atr`, the stop always sits at or beyond the HL.
- **Extension cap vs EMA20:** `|close - EMA20(H1)| <= ext_atr x ATR`. With `ext_atr = stop_atr` this is identical to "the stop sits beyond the H1 EMA20" (long: `entry - stop_atr x ATR < EMA20`).
- Note: the hard rules plus the trigger can make E1 behave almost like a breakout from a young leg. That is fine, but check that trade count stays healthy in the funnel.

### Fill-time re-check
The signal is built on the signal bar's close, but the order fills at the next open. Before accepting the fill, recompute with the actual fill price: the extension cap, the sizing-scope risk distance, the lot size and the cost filter. If any fails (for example after a gap), skip the trade. This check lives in the backtest and execution layers, which know the real fill price.

### E1: Pullback-resume (baseline trigger)
Long, short is the mirror, in addition to the hard rules. Over the window of the last `lookback` H1 bars **including the signal bar**, using **each bar's own** EMA(`h1_ema_slow`) and ATR:
- **Touch:** at least one bar in the window has `low - EMA50 <= touch_atr x ATR`. Lows may pierce below EMA50; the touch only requires price to have reached down to within `touch_atr x ATR` above it (or lower).
- **No breakdown:** no bar in the window has `close < EMA50 - breakdown_atr x ATR`. Only closes are floored, not lows (a pullback, not a breakdown).
- **Trigger:** the signal candle closes above H1 EMA(`h1_ema_fast`) and above the previous H1 bar's high.
- **Entry:** market order at the next H1 open.

### E2: Channel breakout (variant)
- Trigger: H1 close above the highest high of the previous `N` H1 bars (`[TEST]` 20 / 30 / 50), plus the hard rules. Mirror for shorts.
- Optional compression filter `[TEST]`: ATR below its 50-bar average before the breakout.

### E3: H4 supply/demand zone pullback (experimental, test last)
Technically feasible, but only if the zone is defined by an objective algorithm. Zones are H4 objects, so the ATR in this definition is the H4 ATR. Proposed definition `[TEST]`:
- **Base:** 2-6 consecutive H4 candles each with range <= `base_atr` x ATR(14, H4) (try 0.8).
- **Impulse:** the next 1-3 candles leave the base with a combined move >= `impulse_atr` x ATR(14, H4) (try 2.0) and close beyond the base.
- **Zone:** base high/low (or base body extremes). Demand = zone below price after an up-impulse; supply = above price after a down-impulse. Reuse the definition from your existing EA if you prefer.
- **Freshness:** only zones price has not yet re-entered. Expire after `zone_max_bars` H4 bars (try 60).
- **Use:** for longs, require H4 bias long and the H1 signal candle to form with its low inside or touching a fresh demand zone. Stop beyond the zone's far edge (plus buffer). Mirror for shorts.
- Judge it by ablation: E1 with the zone filter vs E1 without. Keep it only if after-cost results improve clearly and the trade count stays workable.

### Optional filters (all OFF by default, add one at a time via ablation) `[TEST]`
- **Structure-break trigger:** close above the highest high of the last 3-5 bars instead of "above EMA20 and previous high".
- **Value-zone pullback:** the pullback touched the zone between H1 EMA20 and EMA50.
- **Pullback length:** between about 3 and 20 H1 bars.
- **Pullback depth:** between 0.5 and 2.0 x ATR from the swing extreme (or a retracement band of about 38-62%).
- **RSI(14, H1):** between 50 and 70 on the signal bar for longs (mirror for shorts).
- **Close location value:** CLV = ((close - low) - (high - close)) / (high - low) >= 0.4 for longs.
- **Session filter:** London and New York hours only.
- **Cooldown:** no same-direction re-entry on a pair for `N` H1 bars after a stop-out (try 6 / 12 / 24). Max 1 open trade per pair.
- **Swap alignment:** skip a trade whose swap per night is negative beyond a threshold (see section 10).

### How quants usually define H1 entries
A measurable rule on closed bars, never a feeling. Common archetypes: channel breakout, pullback to an MA or volatility band, momentum confirmation, volatility expansion after compression, plus filters (spread, session, volatility regime). Parameters are picked from stable plateaus out-of-sample, not from the single best run. Indicators such as MACD, RSI and ADX are all functions of the same OHLC data, so add one only if the feature bucket analysis (section 11) shows it carries information the existing rules do not.

## 6. Stop loss and take profit

- **S1 (baseline):** stop = `entry -/+ stop_atr x ATR`, with ATR **frozen at the signal bar close** and not updated afterwards. Take profit = `entry +/- tp_mult x stop distance` (3R = 4.5 x ATR at the defaults).
- **S3 (variant):** structure + clamp. Stop beyond the last H1 HL / LH plus `0.25 x ATR`. If the distance is below `1.0 x ATR` use `1.0 x ATR`. If it is above the smaller of `2.5 x ATR` and the sizing-scope risk distance (section 8), skip the trade.
- **S2 (variant):** pure structure (HL / LH plus buffer), skip if wider than 3 x ATR.

Skip rules that apply to every stop type:
- If the smallest lot already risks more than `sizing_scope_usd.high`, skip the trade (the engine's `scope` funnel gate). Never widen risk.
- If lots would fall below `volume_min`, skip.
- Skip if `(spread + expected slippage) / stop distance > max_cost_ratio`.

## 7. Exit

Take profit at `tp_mult` (3R). **Working baseline (R2, docs/TESTLOG.md) is X1: frozen initial stop** (`use_trail: false`, `use_be: false`). The T1 profit trail and the BE leg stay as toggles for the comparison runs. All exit legs are toggles in `_base.yaml` (`use_trail`, `use_be`, `bias_flip_exit`, `weekend_flat`).

Trail:
- **T1 (baseline, profit-based):** profit = best price since entry, in R of the initial risk. While profit < `trail_r` (the trigger point, default 1R) the position keeps its initial stop; `profit - trail_r` is negative, so nothing moves. From the trigger on, stop = `best price since entry - trail_r x initial risk` for longs (mirror for shorts). At the trigger the stop equals entry (breakeven); beyond it the stop follows (peak +1.5R, stop +0.5R; peak +3R, stop +2R). It only moves in the trade's favor, never back. ATR is not used.
- **Optional BE leg (`use_be`, default off):** moves the stop to entry plus `be_buffer` once profit reaches `be_trigger_r`. With `be_trigger_r == trail_r` it is redundant, because the trail already sits at breakeven at the trigger. It exists for comparison legs such as BE at +1.5R, where the trail then also starts only at that point.
- **T2:** trail under the last confirmed H1 pivot low (long) minus a small buffer.
- **T3:** exit on an H1 close beyond the H1 EMA(20).

Timing rules (no lookahead):
- Breakeven and trail changes take effect from the **next check row**: the next M1 bar when `position_checks: M1`, otherwise the next H1 bar.
- If stop and target are both inside the same row (M1 minute or H1 bar), assume the **stop was hit first**.

Comparison runs `[TEST]` (these decide whether the BE rule is worth it):
- **X1:** fixed 3R, no breakeven, no trail (`use_trail: false`, `use_be: false`) — R2 working baseline
- **X4a:** BE at +1R then trail (pre-R2 design default, not the current baseline)
- **X4b:** BE at +1.5R then trail
- **X4c:** no BE, trail only after +1.5R
- **X3:** close 50% at 1.5R, stop to breakeven, remainder targets 3R

Always on:
- **No time stop.** A trade is never closed for age alone.
- **Bias-flip exit** `[TEST]`: close if the H4 bias (section 4, conditions 1-3) turns against the trade. If the HR5 variant is ever tested, HR5 stays out of this exit, so one counter-direction H4 candle cannot close an open trade.
- **Weekend rule** `[TEST]`: flat before Friday close vs hold through.

Caution: breakeven stops get hit by ordinary pullbacks and can reduce the share of trades that reach 3R. Whether that helps or hurts is an empirical question for the comparison runs above, not something to assume.

## 8. Risk and sizing (LOCKED rules)

- **Per-trade risk (sizing scope, since 2026-10-17):** the engine sizes the smallest 0.01-lot multiple whose actual 1R reaches `risk.sizing_scope_usd.low` (2.5 USD) and refuses the trade when that would overshoot `high` (3.6 USD) — including when even `volume_min` already risks more than `high`. The old fixed USD 3 cap is retired (section 12 sizing rule; funnel gate renamed `scope`). A fixed `--lot` is a diagnostic override and must still land inside the band.
- If the result is below `volume_min` (usually 0.01), **skip the trade**. Do not round up.
- **Max 1 open position per pair.** If the pair already has an ongoing trade, skip it — no new entries.
- **Max 1 entry per pair per calendar day** (broker server date of the H1 signal bar). A stop-out or time-stop exit does not allow same-day re-entry. Ablation may later test whether this adds value beyond the bar-cooldown in section 5.
- **No-trade windows:** `limits.no_trade_ranges`, a list of `{start, end}` month-day pairs (`MM-DD`, UTC), inclusive on both ends, repeated every year; a range whose start is later than its end wraps the New Year (e.g. `12-15` to `01-01`). **No new entries whose fill day falls inside a window.** Open positions keep their stop / target / trail — windows are entry filters, not forced repairs. The funnel records skipped candidates in the `window` column, and `params.json` stores the active list.
- **Max entries per day across the portfolio:** `limits.max_trades_per_day` (default 5, 0 = off). The backtest applies it as a deterministic post-filter: per calendar day the earliest entries stay, later ones drop, and a pair is not refilled that day.
- **Max open trades portfolio-wide: `risk.max_total_positions` = 5.** Total open risk is then at most 5 x `sizing_scope_usd.high` = USD 18.0. Enforced since 2026-10-18 by the backtest's portfolio pass (`backtest.py::portfolio_filter`, after the per-pair simulation); the pass also enforces `risk.max_ccy_net` and the `limits.weekly_loss_r` halt (spec 8A: a week whose CLOSED R total reaches −`weekly_loss_r`; fixed 2026-10-19, was %-equity and flipped sign at zero equity) — CLI overrides `--max-total-positions / --max-ccy-net / --weekly-loss-r`, 0 = that rule off. The live/panel weekly halt stays %-equity (`limits.weekly_loss_pct`) for now; switching it to R is its own change-set. One open position per pair stays structural (not a config knob).
- What the cap implies at minimum lot 0.01 (approximate, check the symbol info):
  - USD-quoted pairs (EURUSD, GBPUSD, AUDUSD): about USD 0.10 per pip, so the stop can be at most about 30 pips.
  - JPY pairs: about USD 0.06-0.07 per pip, so at most about 40-45 pips.
  - Compute per symbol: `max_stop_distance = high / (tick_value / tick_size x volume_min)`.
- Currency exposure: count a long EURUSD as +EUR, -USD. Cap net exposure per currency at `max_ccy_net` trades in one direction `[TEST]` (suggested 2).
- Margin check: with all positions open, free margin must stay comfortably positive.
- **Log risk as a percentage of equity on every trade** (per-trade risk / equity). The USD risk is scoped, not fixed, so its percentage changes with the account and the stop, and it is the number that matters for drawdown (see 8A).

## 8A. Loss limits and drawdown rules (PROPOSED, not locked)

Principles:
- Losing trades are normal in a trend system (most trades lose). Rules here protect against an unusual run, a regime change, or a bug. They are **circuit breakers, not strategy tuning**.
- Calibrate every limit in the backtest so it triggers rarely (for example around the 95th percentile of historical daily and weekly losses). A limit that triggers often changes the strategy and can cut off the winners that follow losses.
- Limits are written in R and in percent of equity, so they stay meaningful as the account changes. R here is the actual risk taken on each trade (at most `sizing_scope_usd.high`, less when lot rounding makes it smaller).

Proposed limits `[DECIDE]` / `[TEST]`:
- **Daily loss limit:** realized loss of `daily_loss_r` (start 2R) on trades closed in the broker-server day: no new entries until the next day. Open trades keep their SL / TP / trail.
- **Weekly loss limit:** realized loss of `weekly_loss_r` (start 5R) for the broker-server week: no new entries until the next week.
- **Drawdown ladder** (from the equity peak, balance plus floating):
  - L1 at `dd1_pct` (start 10%): reduce max open trades from 5 to 3.
  - L2 at `dd2_pct` (start 15%): no new entries for the rest of the week, then review.
  - L3 at `dd3_pct` (start 20%): stop the system (kill switch). Restart only after a written review and, preferably, a demo re-test.
  - If the account is large enough for lot sizes to scale, L1 may instead halve the per-trade risk.
- **Open-risk cap** `[DECIDE]`: total open risk is 5 x `sizing_scope_usd.high` ≈ USD 18.0 under the current rules. Decide whether a lower cap in USD or percent is appropriate for the account size (for example 3 trades), because one USD move can stop several positions at once.
- **After a loss: no change to sizing.** No martingale, no size-up to "win it back". Risk changes only through the ladder above.
- **Pair level:**
  - No pair ban after a single loss.
  - Optional `pair_pause` (OFF by default, `[TEST]`): after `k` consecutive stop-outs on the same pair (try 2), no new entries on that pair for `pause_days` trading days (try 2 / 3 / 5). Keep it only if the backtest shows an after-cost benefit out-of-sample.
  - Correlated losses are handled by the per-currency exposure cap (section 8), not by banning pairs.

Reference math (approximate):
- **Streaks:** with loss probability `q` per trade, the expected longest losing streak in `n` trades is about `ln(n x (1 - q)) / ln(1 / q)`. At a win rate of 30% (`q = 0.7`) and `n = 100`, that is about 9-10 losses in a row. Breakeven and trailing exits turn some losses into zero-R results, which shortens real streaks, so measure it in the backtest.
- **Streak cost:** a 10-loss streak at risk `r` of equity per trade costs roughly `1 - (1 - r)^10`: about 9.6% at 1%, 14% at 1.5%, 26% at 3%.
- **Sizing from drawdown:** choose the maximum drawdown you accept first (say `D`), then keep `r` small enough that a streak of about 1.5 times the expected worst streak still fits within `D`. For example `D = 20%` and an expected worst streak of 10 (so plan for 15) gives `r` of about 1.5%.
- **Small-account floor:** with a minimum lot of 0.01, the smallest achievable risk per trade is set by the stop distance (about USD 0.10 per pip on USD-quoted pairs). On a very small account this can force a risk percentage higher than the formula suggests. Options: a cent or micro account where the same lot is worth a fraction of the money (check the broker's specs), fewer or tighter-stop trades, or accepting the higher drawdown risk deliberately. Any choice is yours, and this is not financial advice.

## 9. Trade filters

- Skip if `(spread + expected slippage) / stop distance` > `max_cost_ratio` (start 10%, `[TEST]`). With a small stop and per-trade risk in the 2.5-3.6 USD band, spread weighs more, so this filter matters.
- No new entries within about one hour of the daily rollover (broker server time).
- Optional session filter `[TEST]`: London and New York hours only.
- News filter: not in v1; add only if losses cluster around events.

## 10. Cost model for the backtest

- Backtest on vendor H1 (no per-bar spread): one fixed spread from config, the same for both directions. Longs pay it at entry, shorts at exit (buy back on the ask).
- Spread: per-bar `spread` field (points). Longs enter at ask and exit at bid, shorts the reverse. A short's stop/target triggers on ask, so add the spread to the bid high/low.
- Slippage: fixed addition per fill `[TEST]` (e.g. 0.2 x typical spread), plus a 2x spread stress run.
- Swap: `swap_long` / `swap_short` per night held; the engine charges it at UTC-midnight bar crossings and approximates the broker's triple swap as the first bar after the Wednesday-night rollover (the unused yaml key was removed — triple day is not configurable yet).
- Commission: per the broker's account type.
- **Per-pair calibrated costs (since 2026-10-17):** pair yamls carry their own `costs` (spread/swaps/slippage sampled by `python -m quant.spreadcheck`); CLI sweep flags (`--spread-points` / `--spread-pips`, `--slippage-pips`, `--flat-swaps`) beat them globally. Every run records the applied costs — global in `params.json: costs`, per pair in `pair_costs`.

## 11. Test plan

1. Signals only: **print the signal funnel and signals per pair per month first** (section 2), then plot on charts and hand-check a sample against the rules and the H4 shift. Do not look at P&L until the trade count is acceptable.
2. Full simulation with costs. Metrics: expectancy (R), win rate, profit factor, max drawdown, trades/month, exits by type (target, stop, breakeven, trail), results per pair.
2a. **Bias-only probe (`python -m quant.edge_probe`) comes before any entry work:** direction-aligned forward move over 24/48/72 H1 bars in ATR units at onset flips, all bias-on bars (state), and a random-direction null; costs live in the units. Verdict rule is pre-decided in `docs/TESTLOG.md`: pooled onset edge >= 0 beyond 2 SE at 48 and 72 bars; per-pair rows and the 24-bar horizon are information only.
3. **Thesis check before building more:** compute a variance ratio (or Hurst estimate) on each pair's returns at 1-5 day horizons to see whether momentum or mean reversion dominates in your data and period.
4. **Ablation:** switch each hard rule (HR1-HR4), the stale-HL guard, the extension cap and each optional filter on/off one at a time and record the change in after-cost expectancy and trade count. Keep a rule only if it clearly helps, and not just in-sample.
5. **Null model:** run the same stop, exit and sizing with random entries in the bias direction (many repetitions). The real system must beat the random-entry distribution (e.g. above its 95th percentile).
6. Change one factor at a time in an order fixed in advance. Log every run (the count of variants tried is needed to judge overfitting).
7. Split: first ~60% of history for development, last ~40% untouched out-of-sample used once. Then walk-forward (e.g. 2-year train, 6-month test).
8. Robustness: parameter-neighborhood stability, 2x spread, Monte Carlo on trade order, per-pair contribution.
9. Stress periods: Jan 2015 (CHF), Oct 2016 (GBP flash crash), Mar 2020, 2022.
10. **Entry quality scoring (before exits):** for every candidate signal, record MFE and MAE over a fixed window after entry (try 24, 48 and 72 H1 bars), in ATR units, ignoring stop, take profit, BE and trail. Compare entry rules by average MFE / MAE and by the share of signals where MFE exceeds MAE.
11. **Feature bucket analysis:** for any candidate condition (RSI, ADX, MACD histogram, distance to EMA20, body ratio, hour of day, swap sign), split signals into 3-5 buckets by the feature value and compute average forward result in R after costs per bucket. Add the filter only if the relationship is clear, monotonic, similar across pairs, and holds out-of-sample.
12. **Redundancy check:** compute correlations between candidate features and existing rules (e.g. distance to EMA20 in ATR units, RSI, MACD histogram). If a candidate correlates above about 0.7 with a rule already in the system, skip it.
13. **Rule budget:** keep the baseline to a small fixed number of entry conditions. Every added condition must clear a pre-set improvement threshold, and the number of variants tried is logged.
14. **Circuit-breaker calibration:** report the distribution of daily and weekly P&L in R, the longest losing streak, the time spent in each drawdown level, and how often each limit in 8A would have triggered. Run with and without the limits and compare expectancy and max drawdown. Choose limits that trigger rarely.
15. **Pair pause test:** run `pair_pause` off vs on (k = 2, pause 2 / 3 / 5 days) and keep it only if it clearly helps out-of-sample.
16. **Streak Monte Carlo:** resample the trade sequence many times to get the distribution of the worst losing streak and the worst drawdown at the chosen risk per trade, and use it to set the drawdown limit.

## 12. Acceptance criteria (proposed starting points, edit before testing)

A variant passes only if all hold on out-of-sample data after full costs:
- At least 300 trades in development, at least 100 out-of-sample.
- Expectancy >= +0.10R per trade and profit factor >= 1.2.
- Still positive at 2x spread.
- Beats the random-entry null model (section 11.5).
- Neighboring parameter sets mostly positive (e.g. 70%+), not a single spike.
- No single pair contributes more than about 40% of profit.
- Max drawdown at the chosen risk within your limit `[DECIDE]`.
- Numeric bands now live in `configs/_base.yaml` (`benchmarks:`): the backtest grades each run into `summary.csv` (PASS/WARN/FAIL per metric plus an overall `verdict` per row). Declared account 100 USD, so drawdown % = USD drawdown / 100 — an aggressive yardstick, retunable in yaml without code edits.

Reference math (fixed 1:3 target, no breakeven or trailing): breakeven win rate = (1 + c) / (RR + 1), where c is the average cost in R. With RR = 3 and c = 0: 25%. With c = 0.10R: 27.5%. A zero-drift random walk reaches +3R before -1R about 25% of the time, so a real edge shows up as a win rate meaningfully above that after costs. With breakeven and trailing the formula no longer applies, so use the simulation.
Entry gate: `limits.max_cost_ratio` in `_base.yaml` rejects any candidate whose round-trip cost exceeds that share of its stop distance (0 disables the gate). It is a visible knob now — it used to hide in engine defaults and silently selected only volatility spikes. Calibrate spreads per pair from `python -m quant.spreadcheck` before tuning it.
Sizing rule (2026-10-17): `risk.sizing_scope_usd` in `_base.yaml` is the only sizing input — the engine picks the smallest 0.01-lot multiple whose actual 1R reaches `low` (2.5 USD) and refuses the trade when that overshoots `high` (3.6 USD), or when even 0.01 lot already risks more than `high`. Granularity holes (no lot fits the band, e.g. stops of 18-25 pips on EURUSD) show up as `scope` skips in funnel.csv — widen `high` only if the funnel proves the hole eats good setups. A fixed `--lot` is a diagnostic override and still must land inside the band. The legacy `risk_usd` target and the USD3 cap-distance gate are retired (funnel gate renamed `scope`).

Demo forward test (2-3 months) checks plumbing (fills, timing, slippage, swaps) more than edge. Go live only at minimum size.

## 13. Execution notes (later)

- Python on Windows with the MT5 terminal open and logged in. Evaluate once per H1 bar close for all pairs.
- Every order carries a server-side SL and TP. The trailing stop is applied by modifying the SL each bar. On startup, reconcile open positions with system state.
- Log every decision with its reason (including which rule vetoed a candidate). Kill switch: the daily, weekly and drawdown limits in 8A, plus a manual stop file.
- Trade record: every fill appends one row to `trades/journal.csv` (`time_utc,symbol,direction,entry,sl,tp,lot,h4_bias,h4_ema20,h4_ema50,h4_sep_atr,hr1,trigger,spread_pts,slippage_pips,magic,comment,ticket,dry_run,reason`; the `h4_ema20`/`h4_ema50` column names are legacy labels — their VALUES follow the configured `h4_ema_fast`/`h4_ema_slow` periods). The MT5 on-chain comment is a short code only (`QT B1-L E1`, 31-char limit); the full reason lives in the journal + log.
- Panel: `python -m quant.monitor` prints bias + entry checklist per pair (`GO` or first failing section-5 rule, `*` = open position), repainted only on a new closed H1 bar. Header rows: laptop local time (Malaysia UTC+8), broker last-H1-close time (UTC), per-account week P&L with `HALTED` banner at the `WEEKLY_LOSS_PCT` limit. `NONE DETECTED` when no pair holds UP/DOWN H4 bias; per-pair `DATA ERROR` rows otherwise. Halt state persists in `memory/weekly_<demo|real>.json`.
- Executor: `python -m quant.live --roundtrip` (open + immediate market close) and `--touch-close` (open with close SL+TP, broker closes on first touch, timeout falls back to market close). No signal entries yet. Dry-run default; real orders need `--no-dry-run` plus exactly one enabled account. Both legs journaled.
- Trading loop (built, 2026-10-18): `python -m quant.monitor --trade` = the panel PLUS the trading supervisor. Nothing trades unless this process runs — closing the window closes the system. Layers, in order per new closed H1 bar: same-bar stamp memory file (`memory/live_<demo|real>.json`, restart double-send guard) -> per-pair open check -> weekly halt -> daily portfolio cap + structural 1-per-pair-per-day -> no-trade windows -> shared portfolio caps (`risk.max_total_positions`, `risk.max_ccy_net`) -> E1 gate on fresh closed bars -> cost gate + sizing scope with the SAME `quant/rules.py` math as the backtest -> market entry with broker-side SL/TP attached. Adopted from broker IN-deal history + journal rows on restart (position context survives; one loud "adopt" journal row if a position has no row). Trail/BE (`use_trail/trail_r/use_be/be_trigger_r/be_buffer`, off stays off) evaluates every cycle (~60s) against the best bid since entry. Every event lands in `trades/journal.csv` (columns extended with `position` + `risk_usd`; legacy header auto-upgrades). Launch: `start-trader.bat` (dry-run default; real orders only with `--no-dry-run`, one enabled account, and the user's own action).
- Backtest: `python -m quant.backtest --batch` loops `configs/scan-selection.yml` (tick pairs on/off there; missing `data/<SYM>_H1.csv` prints SKIP and continues). Results to `backtest_results/<local-time>/`: `summary.csv`, `funnel.csv`, `trades_<SYM>.csv`, `yearly.csv`, `params.json`, plus `report.html` (auto, plotly; import-guarded). Every run also appends one summary row to `backtest_results/_ledger.csv` (auto, best-effort; `python -m quant.ledger --rebuild` rebuilds it). Build H1 with `python -m quant.mkdata --symbol <SYM>`.
- Demo account only until section 12 is satisfied.



## 14. Open decisions

- [x] Per-trade risk = sizing scope 2.5-3.6 USD (`sizing_scope_usd`, section 8/12) — supersedes the old "USD 3 max loss" lock (2026-10-17)
- [x] Baseline bias = original B1 (EMA20 > EMA50, HR1a, separation); HR5 is an off-by-default test variant
- [x] HR4 edge = previous H1 higher low / lower high (section 5)
- [x] HR1 variant: HR1a (close) is the baseline (section 4)
- [x] Baseline stop = S1 (1.5 x H1 ATR), take profit 3R = 4.5 x H1 ATR
- [x] E1 setup defined exactly (section 5); E1-only for the first build
- [ ] `atr_n`: 7 vs 14 (test)
- [ ] `ext_atr` / `edge_atr`: keep equal to `stop_atr` (1.5) or test 1.0 and 2.0
- [ ] Loss limits in 8A: daily / weekly limits, drawdown ladder levels, open-risk cap (calibrate in the backtest)
- [ ] Whether to use `pair_pause` (test only)
- [ ] Final 10 pairs and broker symbol names
- [ ] B1 (20/50) vs B2 (20/100), E1 vs E2 vs E3 after testing
- [x] Trailing: T1 profit trail only (`trail_r` 1.0); BE is an optional leg, off
- [ ] Drawdown limit, weekend rule

## 15. Parked (remembered, NOT active rules)

- **HR5 body-EMA agreement (test variant, `use_hr5` off):** on the last completed H4 bar, for longs, all three must agree: EMA20 > EMA50, candle placement per HR1, and a bullish candle (close > open). Mirror for shorts. Strict inequality, so a doji vetoes both directions. Position between EMA20 and EMA50 is allowed; only the directions must align.
  - Run only after the baseline E1 + HR1-HR4 ablation is done.
  - Known concerns to check: (1) it can veto the best E1 pullback setups, because the last H4 bar often contains the pullback and is counter-direction; (2) it duplicates HR2 (H1 signal candle direction); (3) the bias then flips at most every H4 bar, and candle color depends on broker server-time boundaries; (4) it strongly correlates with HR1.
  - Judge it by the signal funnel plus ablation: the trades removed vs kept, and whether the removed trades were actually worse after costs. Keep it only if the improvement is clear and out-of-sample.
  - Never include it in the bias-flip exit (section 7).