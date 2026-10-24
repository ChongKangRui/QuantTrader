# Dev Log (TODO first; records newest first)

## TODO (unfinished work only; finished work goes into the dated log below)

Current focus: find and validate the system's edge. The prepared four-pair
backtest is deferred, not the next action. No backtest is authorized now.
Completed setup tasks are recorded in the dated history, not in this checklist.

### Next (pending work; experiments need separate authorization)

- [ ] Separately verify live API clock semantics before claiming live/offline
  timing parity. `trader._gate_check` / `_refresh_crossover` still label broker
  rate epochs UTC; `monitor._utc` formats raw epochs as UTC. Deal timestamps in
  `records` / `account_store` need independent verification, not an assumed
  candle-clock shift. Read-only code review identified these consumers; their
  runtime/deal-clock impact remains unverified. No live code changed here.

- [ ] DICE REMINDER — obtain a NEW reference with current config, broker H1
  checks and `simulation_timing: position_accounting_v3`. The 31 saved runs
  checked on 2026-10-24 predate that accounting marker. Then run
  `quant.dice_probe --real-only --reference backtest_results/<NEW_RUN>`.
  Only after full trade parity PASSES, proceed to the pre-declared B comparison.
  No matching current-model parity/random result found; old dice A/B results
  exist but use the superseded 2026-10-18 reference. Keep the reference/config fixed; choosing
  a pattern to disable is a new idea and requires separate validation.
  Full-range results have been inspected; 2023-2025 cannot now be called unseen
  for ideas chosen from these reports.
- [ ] Compare widened stops against a matching baseline.
  No widened-stop-enabled run was found in the 31 saved params files checked.
  Write the TESTLOG pre-declaration, then obtain matching user-run results
  with and without `--widen-stop` (one change per run).
- [ ] Research better protection against flat/ranging execution markets.
  Execution-chart consolidation detection and its benefit remain unvalidated;
  the existing bias-chart filter is not proof of execution-chart protection.

### Cross-sectional momentum — core first, comparison later

- [ ] Finalize the currency-ranking specification before implementation: fixed
  currency universe (including USD), scoring method/common reference, ranking
  timeframe, lookback, update schedule, strongest/weakest group sizes and
  optional minimum score gap. Define ties, disjoint groups, insufficient history
  and stale/missing data handling. Top 3 versus bottom 3 is an example, not a
  locked setting. Keep ranking timing independent of execution/EMA-bias timing.
- [ ] Implement a shared offline/live ranking and bias decision with selectable
  `ema_only`, `ema_and_ranking`, and `ranking_only` modes. Ranking disabled must
  preserve the existing baseline. Agreement mode blocks conflicting/neutral
  directions; ranking-only replaces EMA bias, not entry-chart EMA requirements.
  Keep the same bounce/recovery entry, exits, costs, sizing and risk guards;
  support all existing execution/bias timeframe combinations. New controls
  must be switchable and numeric settings editable. Use synchronized completed
  broker candles available at decision time, never future prices. Invalid
  ranking data blocks dependent entries, not open-position management. Save
  decision-time scores, ranks, source timestamps, EMA/final direction and
  rejection reasons now; build comparison reporting only after this core.
- [ ] After the core, extend existing reporting to compare EMA-only baseline,
  EMA + ranking agreement, and ranking-only direction. Show baseline trades
  kept/removed, after-cost profit forgone and loss avoided (amounts, not merely
  winner/loser counts), expectancy in R/USD, profit factor, portfolio maximum
  drawdown, net profit, exposure and trade count. Also compare full variant
  portfolio results: changed admissions affect later quotas/opportunities, so
  deleting trades from a baseline is only a diagnostic, not a complete replay.
  Optional separate comparison: prioritize simultaneous eligible candidates by
  largest currency-strength score gap when slots are scarce, not by bid-ask
  spread or eventual profit. Keep other settings/data/costs matched.
- [ ] Before separately authorized experiments, freeze variants, parameter
  ranges, sample requirements and pass/fail rules in TESTLOG. Check neighboring
  lookbacks and cost sensitivity; flag INSUFFICIENT samples, including when
  configured pair/portfolio entry caps and strict ranking shrink trade counts.
  Agree genuinely unseen validation data: previously inspected 2023-2025,
  including 2024-2025, cannot be relabelled an unseen holdout. No backtest is
  authorized by this design or by adding comparison tooling.

### Verdict track (timebox: 2-3 more experiments, then decide)

- [ ] Write the variance-ratio / Hurst script (spec §11.3). No implementation found.
- [ ] Run the variance-ratio / Hurst check after implementation and record its
  results alongside the current-model dice comparison in `docs/TESTLOG.md`.
  The dice baseline/parity/B steps are tracked above; old A/B runs do not
  complete this current-model validation. Experiments require a user request.
- [ ] Decide from the results:
  - real result inside the random cloud AND variance ratio ≈ 1 → no convincing trend/entry edge found for the tested pairs and configured timeframes → consider another market, timeframe or edge type — or stop.
  - real result clearly above the cloud, or gross > 0 but costs kill it → investigate the measured spread/swap burden and stop distances before proposing a separately tested change.
- Standing rules:
  - each hypothesis → `docs/TESTLOG.md` BEFORE running, one change per run
  - keep the last ~3 years unseen for any new idea
  - do NOT drop or keep pairs based on this run (about 200 trades per pair; the best/worst pairs are within noise)
  - stopping is a valid result; the tooling/engine/ledger/report are reusable; keep it demo-only

### Next research directions — recorded 2026-10-24 (ideas only)

- [ ] Research Donchian breakout trend following as a separate, simple
  benchmark against the current strategy. Define breakout windows, exits and
  sizing before testing; use completed candles and no future-price information.
- [ ] Research FX carry: investigate holding currencies with higher carry
  against those with lower carry. Check historical carry data and actual broker
  financing costs; today's swap rates cannot establish historical carry returns.
  Include the risk of sharp losses when crowded carry positions unwind.
- [ ] Research standalone cross-sectional momentum separately from the
  ranking/bias integration tracked above: rank a pre-declared set of currencies
  or instruments by past performance, then study stronger versus weaker ones.
  Keep this distinct from trend following on each instrument's own price history.
  Define ranking dates, holding periods and currency exposure before testing.
- [ ] Compare different strategy families across different markets, not only
  variations of the existing entry rules. Agree instruments, suitable data and
  realistic costs first; broader market support is a research idea, not built.
- [ ] Longer-term idea: a multi-strategy risk-premia system with **carry,
  value and trend as separate components**, included in one overall portfolio.
  Research value measures and their publication dates before designing signals.
  Each component would have its own rules, enable/disable switch, editable
  parameters, risk budget and standalone results before considering combinations.
  Study combined exposure, correlations and drawdowns; separate strategies can
  still lose together. Cross-sectional momentum is a further research candidate,
  not automatically a fourth component or a replacement for trend.
- Research process: consult relevant material in `resources/`, record source
  and page/chapter, and distinguish published ideas from locally validated results.
  Pre-declare each experiment in `docs/TESTLOG.md`, including the market universe,
  costs, comparison baseline, pass/fail rules and genuinely unseen data. Previously
  inspected 2023-2025 results are not an unseen holdout for these new ideas.
- Status: future research only, not evidence of an edge or an approved redesign.
  No strategy/config changes, data collection, backtests or trading authorized
  by this note; experiments require a separate user request.

### Methods for finding an edge LONG TERM
- Start with a reason, not a pattern. Write down why the edge should exist and who is on the other side. Typical reasons are risk premia (trend, carry, value), behavioral biases (slow reaction, herding), and forced flows (hedging, rebalancing, session liquidity). If you can’t state the reason, expect noise.
- Replicate published edges first. Reproduce known strategies like Donchian breakout trend following, carry, and cross-sectional momentum before inventing your own. - Good sources include Robert Carver’s Systematic Trading, Andreas Clenow’s trend-following books, AQR’s papers, and SSRN. Your first goal is to see whether a documented edge survives your costs and data.
- Explore data with simple, conditional questions. For example: what is the average forward return after a 20-day breakout, by session, or by day of week? Measure effect size and sample size, not just whether it looks good. Hold out data you don’t touch.
- Go for breadth. Run the same idea across many instruments (FX, gold, indices, oil, crypto) and timeframes. An edge that appears in many markets is far more credible than one that appears in a single pair.
- Decompose the system. Test entry, exit, and sizing separately. A random-entry benchmark with your exits shows whether the entry adds anything. In most trend systems the exits, sizing, and diversification matter more than the entry signal.
- Validate for robustness.
1 Look for a parameter plateau, not a single peak.
2 Use walk-forward or out-of-sample testing.
3 Stress-test costs at 2× and 3×.
4 Bootstrap your trades for a confidence range.
5 Log every variant you try, because the more you try, the more your best result is inflated.
6 Look where you can compete. Slow, small-capacity strategies and less-crowded markets suit an individual, as long as liquidity and costs are manageable.
Forward-test small. Demo or tiny size checks that the live system behaves like the backtest. It is slow evidence, not proof.

### Parked until the verdict is in

- [ ] Deferred four-pair evaluation — revisit only after the edge research
  and a separate user backtest request. Follow the frozen TESTLOG design and
  `data/four_pair_evaluation_20261024/evaluation_plan.json`: 2019 preparation,
  score 2020-2025, minimum-trade/INSUFFICIENT gate before benchmark PASS, and
  leave EURNZD/GBPCHF strategy results untouched. No experiment run yet.
- [ ] Percentage-based sizing scope (future, not built): user envisages a
  configurable band such as 2%-3% instead of a fixed USD band, with dynamic
  lots. No automatic balance threshold or percentage-band implementation now.
  The old 1/3/5% lot-scale sweep is deferred. Existing balance scaling still
  checks a fixed USD band; it does NOT implement percentage bounds.
- [ ] Complete strategy demo smoke: 0.01 lots EURUSD + one JPY pair → all 10;
  compare fills vs backtest. Existing local demo records contain EURUSD/GBPUSD,
  but do not verify the JPY/all-pair strategy check or fill comparison.
  Demo password rotation remains unverified (it appeared in chat); do not
  assume it is complete or inspect credentials to check it.

## 2026-10-24 — Ranking/bias design agreed; comparison work deferred

- Recorded the agreed flexible bias modes: existing EMA-only baseline, EMA and
  ranking agreement, or ranking-only direction with the same entry trigger.
  Entry-chart EMA rules remain separate from the optional EMA bias. Scoring,
  universe, timing and data-failure details still need agreement; no ranking
  implementation or performance validation is claimed.
- Added core-first and deferred comparison TODOs. User confirmed that filter
  quality must compare after-cost amounts, not just avoided losers versus
  removed winners by count. Full portfolio comparisons and baseline-trade
  diagnostics are distinct; strength-gap candidate priority is optional.
- Retained standalone momentum research and all other unfinished tasks. Prior
  inspected dates are not a fresh holdout; experiments need separate approval.
- Documentation only. No code, configs or data changed. Tests, backtests,
  terminal requests and orders not run.

## 2026-10-24 — TODO cleanup; four-pair evaluation deferred

- User deferred the prepared four-pair backtest while finding and validating
  the system's edge. Moved that experiment from Next to Parked; it is unfinished,
  not cancelled or completed. Any later run still needs a separate user request.
- Completed collection, calibration, evaluation setup, exporter repair and
  launcher tasks were already removed from TODO and recorded below. Removed
  completed-implementation detail from remaining research/experiment items;
  retained all unfinished validation, research and safety work.
- Documentation only. No code, configs or data changed. Tests, backtests,
  terminal requests and orders not run.

## 2026-10-24 — Dedicated four-pair evaluation launcher added

- Added `run-backtest-unseen.bat` for the frozen EURAUD/GBPCAD/AUDCAD/CADJPY
  profile and isolated results folder. It refuses missing local profile files,
  accepts no overrides, and preserves the backtest exit status after pausing.
- `configs/scan-selection.yml` is unchanged. The launcher uses the separate
  selection under `data/four_pair_evaluation_20261024/configs/`; 2019 preparation,
  2020-2025 dates and costs remain those of the frozen profile.
- Added `tests/test_backtest_launchers.py` using a substituted command and
  synthetic profile files only; documented the launcher in `docs/RUNBOOK.md`.
  Actual evaluation remains pending. No backtest, signals, terminal or orders run.
- Validation: `uv run pytest -q tests/test_backtest_launchers.py` -> 15 passed.
  `git diff --check` for the changed docs passed. Full suite not rerun.

## 2026-10-24 — Evaluation setup, 2019 wiring and exporter clock fix completed

- Completed and removed the three setup TODOs: isolated evaluation preparation,
  preparation-year wiring, and the shared API history exporter's clock repair.
  Actual evaluation is a separate pending experiment, not a result of this work.
- `python/quant/mkdata.py`: verified Pepperstone API labels now normalize to UTC
  consistently for date queries, warmup/coverage anchors, closed-candle checks
  and CSV output. US DST, not fixed offsets or Europe DST. Auto selection has
  explicit config/CLI overrides (`broker_api_clock`, `--broker-clock`); metadata
  distinguishes original query labels from actual UTC. Live consumers unchanged.
- `python/quant/broker_data.py`: offline verified-source bundles pin H1/H4/D1
  and converters with checksums, preserve provenance/warnings, deduplicate only
  identical OHLC/volume overlaps, and fail on conflicts/unverified inputs.
  Added `mkdata --bundle-broker`; no dependency or new shared entry-point file.
- New local-only bundle: `data/pepperstone_prepared_2019_2025_20261024/`.
  All 17 pairs have 2019 preparation charts. Sixteen have evaluation history;
  AUDJPY has only preparation history and remains parked. Original inputs were
  not overwritten; no vendor substitution, gap fill or price resampling.
- `python/quant/backtest.py`: optional configurable/disableable evaluation
  boundaries retain indicator preparation but exclude earlier trades, sizing,
  position/loss/quota state and scored equity/exposure. Validate closed prefix
  candles on both chart roles; reject an end cutting an execution candle. CLI
  supports explicit start/end and enable/disable. Terminal-boundary yearly marks
  belong to the interval just ended; preparation never enters monthly metrics.
  Final regression: enabled-window fills use their trading day, not the prior
  preparation signal day, for daily admission. Engine hashes refreshed before
  any actual-history experiment; frozen strategy/costs/verdict rules unchanged.
- `python/quant/dice_probe.py` shares the same window/eligible fills and keeps
  parity/reference window checks. `python/quant/ledger.py` includes the window
  in comparison groups. Synthetic real/dice full-trade parity passes; no actual
  parity/dice run. All six supported chart combinations have window coverage.
- Frozen isolated four-pair configs: `data/four_pair_evaluation_20261024/configs/`.
  Current strategy, risk, limits, benchmark, timeframes and base-cost assumptions
  copied unchanged; only offline data/window settings and the four calibrated
  pair costs differ. EURAUD/GBPCAD/AUDCAD/CADJPY only. Source/config/code/cost
  hashes and fixed sample/pass/fail rules are in `evaluation_plan.json` / TESTLOG.
  EURNZD/GBPCHF strategy results remain untouched; active settings are unchanged.
- Input-only audit blocked scan/simulation functions and verified 51 charts,
  104 unchanged source price files, exact price/volume union (zero roundtrip
  price difference), all six profile files, 22 code hashes, converter closure
  and preparation/position-feed coverage. No actual-history signals or results.
- Validation: initial focused exporter/intake/backtest/dice/comparison tests
  363 passed. Final full suite, including DST/report-bundle and boundary-fill-day
  regressions: 877 passed, two pre-existing weekly-cap assertions failed (expect
  5; active editable value is 0); no values reset to satisfy them. Command:
  `$env:PYTHONPATH="python"; uv run pytest -q`.
  `git diff --check` passed. No actual-history backtest, terminal connection,
  orders, credential reads, report rebuild or strategy-result inspection.
- Remaining risks: recent demo cost/current swap assumptions are not historical
  financing or fill proof; observed-UTC swaps and H1 ordering remain approximate.
  Known source/session/final-day warnings are retained. Separate live API clock
  consumers were reviewed (trader.py 428/443, monitor.py 293, records.py 36,
  account_store.py 146-147) but not modified or runtime-validated; tracked above.

## 2026-10-24 — Four-pair broker cost calibration proposal completed

- User chose broker calibration rather than shared defaults. Current Saturday
  reads gave 12 stale pair snapshots; zero were accepted as live calibration.
  Recorded current POINTS swaps and quote-clock uncertainty without promoting
  stale spreads or stale USD conversion references into configuration.
- Used recent broker tick history instead, with sampling/method declared in
  TESTLOG before requests: Oct 21-23, 02:00 / 08:00 / 14:00 UTC, five minutes
  per window. All 36 pair windows and three converter windows passed minimum
  quote counts and tick/H1 clock-price consistency. 24179 pair observations,
  26712 including converters. No strategy signals/returns or reserve results.
- Method fixed beforehand: highest per-window P95, using the higher observed
  value, rounded up to broker points. Proposed spreads: EURAUD 15 points / 1.5
  pips; GBPCAD 18 / 1.8; AUDCAD 7 / 0.7; CADJPY 14 / 1.4. These estimates do
  not cover every session, stress event or the full historical trading period.
- Proposed ordinary-night swaps in USD per 0.01 lot (long / short):
  EURAUD -0.090788284 / +0.035443296; GBPCAD +0.026260429 / -0.092161942;
  AUDCAD +0.029051047 / -0.064899752; CADJPY -0.020989639 / -0.037449599.
  Current published terms, converted with the last declared historical quote
  window; not a reconstruction of 2020-2025 financing. Triple-day code 3 from
  the broker is preserved. Commission 0 and slippage 0 remain explicit existing
  Standard-account assumptions, not tick measurements or a new execution claim.
- Local records: `data/pepperstone_cost_calibration_20261024/`, including raw
  quotes, H1 clock checks, proposals, units, source hashes and an unchanged base
  config snapshot. No active pair configs/costs/selection or shared code changed.
- Validation: `$env:PYTHONPATH="python"; uv run pytest -q tests/test_spreadcheck.py`
  -> 8 passed (existing synthetic cost conversion tests). Independent collected
  data audit recomputed all 39 window statistics, clock/range checks, swap-unit
  conversions, complete window sets and 80 evidence-file checksums; passed.
  No full suite, backtest, dice, orders, credentials or account switches.
- Cost sampling/proposal subtask complete. Isolated evaluation freeze/intake,
  2019 preparation boundaries and shared exporter clock repair remain TODO;
  the three broader tasks are not marked complete just because sampling passed.

## 2026-10-24 — Standing rule for completed TODO tasks

- Added persistent project instructions in `AGENTS.md`: whenever a listed TODO
  task is completed, remove it from TODO and record completion in the dated log
  below the full TODO section in the same change. Partial tasks retain only
  unfinished work; unverified/pending tasks must not be marked complete.
- Data collection is complete and already archived. Dataset intake and the
  2019-preparation / 2020-2025 evaluation boundary are not wired yet, so those
  TODO items remain. No trading code, configs or data changed.
- Documentation only. No tests, backtests, terminal requests or orders run.

## 2026-10-24 — Full 2019 preparation history collected for all 17 known pairs

- User confirmed all 17 known pairs, including parked AUDJPY, not every broker
  FX symbol. Collected direct Pepperstone-Demo H1/H4/D1 for actual UTC calendar
  2019 into `data/pepperstone_all17_2019_export_20261024/`: 51 feeds, 136492
  candles. All required USD conversion feeds are already among the 17 pairs.
- Per pair: 259 Daily, 1554 H4 and 6216 H1 candles, except NZDUSD H1 has 6215.
  Actual common first open: 2019-01-01 22:00 UTC (Jan 2 server time). Last H1
  open: Dec 31 21:00 UTC; H4 Dec 31 18:00 UTC; D1 Dec 30 22:00 UTC.
- Applied the verified broker-clock conversion only in this new collection.
  API query labels were shifted to match actual UTC bounds before requesting
  history. Preserved 102 original CSV/metadata files; corrected 51 feeds'
  timestamps without changing price/volume strings. All 30906 candles shared
  with the previous corrected dataset match OHLC and volume. No resampling,
  filling, overwriting existing datasets or shared-source/config changes.
- Candle consistency/coverage audit has no OHLC mismatches or uncovered higher
  candles. One NZDUSD H1 open, 2019-01-28 18:00 UTC, remains absent after three
  additional broker reads; surrounding hours return normally. H4/D1 OHLC still
  matches. Recorded the warning and recheck evidence; no replacement invented.
- This collection requests zero EXTRA pre-2019 warmup bars. Strategy warmup
  guards/settings remain unchanged. Full 2019 is preparation data for a future
  2020-2025 evaluation, not permission to score 2019 trades. Explicit intake and
  evaluation-start enforcement remain TODO; no files were merged or promoted.
- Validation: `$env:PYTHONPATH="python"; uv run pytest -q tests/test_mkdata.py tests/test_broker_data.py`
  -> 61 passed. Independently checked all 204 normalized/raw feed checksums,
  unchanged price/volume fields, 2019 UTC limits and clock/overlap evidence.
  No full suite, backtest, dice, strategy-result inspection, orders, account
  switches, trading-flag changes or credential reads. AUDJPY stays parked;
  EURNZD/GBPCHF strategy results remain untouched. Initial requests needed no
  automatic retry; three targeted missing-hour reads are recorded separately.

## 2026-10-24 — Six additional FX pairs collected; broker clock verified

- Completed the user-authorized data collection after TESTLOG pre-declaration:
  EURAUD, GBPCAD, AUDCAD and CADJPY first group; EURNZD and GBPCHF reserved.
  Pepperstone-Demo supplied direct H1/H4/D1 plus five required H1 converters:
  23 feeds, 507109 candles, requested 2020-2025 with 100-bar configured warmup.
  Actual common prefix starts 2019-08-11 21:00 UTC (2019-08-12 server time).
- Local-only folder: `data/pepperstone_unseen_fx_2020_2025_export_20261024/`.
  Source/export dates, raw bytes, SHA256 checksums, collection config snapshot,
  timestamp evidence and quality audit are retained. Bounded retry handling was
  used, but every history request succeeded without an additional attempt.
- Caught incorrect UTC labels in the API exporter. Interpreting its epoch labels
  as broker server clock, then using the existing New York + 7h / US DST rule,
  matches all 186728 existing converter H1 candles; treating labels as UTC
  matches zero. Corrected timestamps only in this new dataset. All 23 feeds'
  original price/volume fields and all 46 raw files were verified unchanged.
- Final quality audit: no cross-timeframe OHLC mismatches or uncovered higher
  candles; all requested calendar years and required warmup present. Short
  sessions/possible missing hours remain reported, never filled. EURNZD has
  one fewer H4 candle than the other pairs; matching Daily OHLC does not prove
  all hours are present. No claim of exact broker execution parity.
- Validation: `$env:PYTHONPATH="python"; uv run pytest -q tests/test_mkdata.py tests/test_broker_data.py`
  -> 61 passed (existing synthetic exporter/intake tests). Actual collected-file
  checksum, unchanged-price, warmup and cross-chart audits also passed, with
  session warnings. No full suite, backtest, dice experiment, strategy-result
  inspection, orders or credential reads. No active source/config/data changes.
- Collection is complete, not an approved experiment or ready-wired backtest.
  Costs, evaluation design, explicit intake/pair setup and the shared exporter
  clock repair remain pending. Reserve pairs have no strategy results inspected.

## 2026-10-24 — TODO audit and completed TP experiment archived

- Rechecked all 15 checklist tasks against code, TESTLOG, saved run metadata,
  local data inventory and demo trade/journal summaries. Removed one completed
  task; 14 remain open. TODO stays above every dated record.
- No-fixed-TP experiment: user explicitly confirmed completion during this
  audit; removed its checked TODO. Local reproduction is not verified: all 31
  available saved runs still record positive fixed targets (2R–10R), and current
  simulation code still creates a target. No TP-free result or comparison was
  found locally. This is a user-confirmed completion, not a validated benefit
  or a claim that the active strategy has no fixed TP.
- Additional unseen-pair collection remains pending; broker H1/H4/D1 files
  cover the same ten selected pairs. No new current-accounting dice reference
  or parity/B result found; existing dice artifacts are from the old model.
- Widened-stop implementation is complete, but no enabled saved experiment
  was found. Basic bias flat filtering exists; improved execution-chart ranging
  protection remains research. Variance-ratio/Hurst implementation, execution
  and the resulting current-model verdict remain pending.
- All five research directions remain open: Donchian, carry, cross-sectional
  momentum, cross-market strategy-family comparison and combined carry/value/
  trend. No completed study or implementation was found. General research
  methods remain guidance, not completed tasks.
- Percentage sizing bands remain unbuilt; existing percent-target sizing still
  checks a USD band. Full demo strategy/fill validation and password rotation
  remain unverified; partial demo records do not complete either task.
- Documentation only. No tests, backtest/parity/dice process, data collection,
  terminal connection, orders or credential reads performed.

## 2026-10-24 — Check-time swap, duration exposure and broker export wiring

- Fixed missed overnight charges when an H1/M1 exit crosses a UTC date within
  an execution candle. Charges/events now follow observed check dates and the
  recorded exit boundary, once per date transition. Midnight entries do not pay
  the prior night. The existing Thursday triple and approximate UTC/gap model
  remain; exact broker rollover/session/DST financing is not implemented.
- New trades record exposure seconds within observed execution intervals.
  Metrics use the full tape's available seconds, excluding gaps and clipping
  short sessions. Portfolio filtering keeps this denominator; chart `bars_held`
  stays unchanged. Reports distinguish duration exposure from legacy estimates.
- Broker export planning respects the effective broker position-check setting:
  active H1 checks no longer request unnecessary M1. Legacy settings and generic
  exporter timeframe support remain. Strategy/config values and live code unchanged.
- `simulation_timing: position_accounting_v3` prevents old accounting references
  from validating new costs/admission outcomes. Saved runs are not rewritten.
- Validation: `$env:PYTHONPATH="python"; uv run pytest -q` -> 837 passed,
  two existing editable weekly-cap assertions failed (expect 5, active value 0).
  Added 25 regression cases; `git diff --check` passed. Synthetic/fake MT5 only;
  no actual-history backtest, dice experiment, report rebuild, data collection,
  terminal connection or orders run.

## 2026-10-24 — Broker H1 position checks, independent of entry/bias

- Active `configs/_base.yaml` now uses broker H1 stops/targets/BE/trailing for
  every selected pair, retaining H4 entries and D1 bias. No costs, sizing, live
  management or inert preset settings changed. Legacy/research M1 stays intact.
- Backtest and dice share the same verified H1 feed. Completed H1 extremes only
  update the next hour's stop; ambiguous stop/target ties choose the stop.
  Hourly range exits book at H1 close; gap exits retain the known open timestamp.
  Missing H1 files/checksum mismatches/empty execution intervals fail instead of
  silently using H4. Known partial sessions remain warned, not filled.
- Runs pin the H1 extension and loaded check prices; converters use closed H1
  rates. Old H4-only references require a new user-run baseline/parity check.
  Reports distinguish H1 checks from unchanged execution-tape equity marks
  (currently H4). Live trailing still uses current quotes; H1 is approximate.
- Validation: `uv run pytest -q` with `PYTHONPATH=python`: 812 passed, two
  pre-existing editable weekly-cap assertions failed (expect 5, active value 0).
  Final focused backtest/broker/dice/report/comparison/performance/crossover
  checks: 345 passed; `git diff --check` passed.
  Synthetic fixtures only. No actual-history backtest, dice experiment, report
  rebuild, data collection, terminal connection or orders run.

## 2026-10-24 — Follow-up accounting and order-safety fixes

- Cash flows use broker milliseconds when available. Broker collection brackets
  history with account reads and skips inconsistent balance/credit snapshots.
- Local entry refusals are recorded as `not_sent`, not uncertain broker sends.
  Definite refusals/rejections may retry on the same bar; previous attempts stay
  in the local audit. Unknown/partial/placed responses still block duplicate sends.
- Roundtrip journaling failures no longer prevent its close attempt. Exit code 3
  means the position closed but the journal is incomplete; code 2 still needs
  operator attention for an open/uncertain position.
- Validation: 219 related tests passed; full suite: 805 passed, two existing
  config-value assertions failed. Active configuration values were not changed.
  No backtests, MT5 connections or real orders run. Old uncertain records still
  need broker verification; they cannot safely be assumed to be unsent.

## 2026-10-24 — Local net performance and broker fill memory

- Added shared Sharpe/Sortino/Calmar calculations and Sharpe interpretation bands.
  Settings are optional/editable; no active configuration values changed.
- Added account/server/type-separated JSON storage (no database/dependency),
  broker deal reconciliation, snapshots, and JSON/CSV/HTML exports. Actual entry
  intents are flushed before send; uncertainty blocks new entries, not management.
- Net live equity includes broker costs without deducting spread/slippage twice;
  external capital is separated using labelled cash-flow-adjusted estimates.
  Strategy deal totals are separate; strategy ratios are not invented.
- New backtest marks accrue entry commission, short spread valuation, and swaps;
  old or incomplete cost-timed equity remains N/A. Unit tests use controlled data
  and mocked MT5 only. No backtest process or terminal trading was launched.
- Validation at initial implementation: 224 related tests passed; full suite: 710 passed,
  six failures outside this feature (two active-config value assertions and
  four exit-timing assertions following separate edits during this session).
  Those settings/timing edits were not reverted to satisfy tests.

## 2026-10-24 — Execution-price, conversion and admission repairs

- Fixed normal/M1 gap stops to use the available opening bid/ask plus configured
  slippage, never an unreachable stop price. Known execution opens are checked
  even if the first M1 candle is absent. Gap targets conservatively fill at TP;
  ambiguous range stop/target ties still choose the stop.
- Short protective orders now trigger on ask, with spread charged exactly once.
  Breakeven buffers remain configured in pips and are converted to price units
  in both backtest and live trailing decisions. Live order/restart plumbing unchanged.
- Entry risk uses rates available at entry; realized USD profit uses rates known
  at exit. Legacy H1 converter closes are availability-stamped, and new open
  positions are valued with current known conversion rates, spread and timed costs.
  Missing cross-conversion marks fail instead of inventing account values.
- Equity uses known opening prices at gaps, not pre-entry closes. A new open
  supersedes the previous close at a shared boundary. Converter updates can move
  USD equity independently of the traded pair's price. Legacy rows keep their
  initial-risk mark fallback; old saved artifacts are not rewritten.
- Main backtest/dice paths simulate independent candidate lifecycles and then
  admit entries chronologically. Rejected attempts consume no pair slots, fill-day
  allowance, portfolio quota or loss state. Optional balance sizing is performed
  inside admission using only accepted realized exits; sizing rejects use no quota.
  Previously gated scaling/strategy combinations remain gated, not enabled here.
  Unfinished lifecycles stay visible through tape end, labelled `end-of-data`;
  this is a terminal valuation, not a claim of an actual broker close.
- `simulation_timing: execution_prices_v2` separates these runs from earlier
  baselines and dice references. User must produce a new matching baseline;
  old results cannot validate the corrected fills/admission/account calculations.
  Coarse candles still cannot establish actual within-candle ordering/fills.
- Validation: 784 passed, two existing editable-config cap assertions failed
  (expect 5, active setting 0). Config values unchanged. Command:
  `$env:PYTHONPATH="python"; uv run pytest -q --tb=short`.
  Synthetic candles, calculation fixtures and mocked MT5 only; no actual-history
  backtest, data download, terminal connection, orders or report rebuild run.
  Full-history performance of independent-candidate replay is not benchmarked.

## 2026-10-24 — Look-ahead timing repairs

- Backtest trailing stops now use only previously completed check rows.
  Current-row highs/lows update the next row's stop, for both sides and
  H1/H4/Daily execution with coarse or M1 checks. Ambiguous stop/target ties
  still choose the stop. Signals, strategy settings and configured costs unchanged.
- Range-based exits book at check-row completion in every source mode;
  confirmed crossover/open-price exits retain their open timestamp. Legacy
  equity close marks are delayed to candle completion like broker marks.
- Balance scaling uses recorded initial risk/lot, never the eventual P/L or
  another trade's risk. Old rows without valid initial risk remain unscaled
  with a warning. Existing live execution/restart safeguards were not changed.
- New `simulation_timing: closed_rows_v1` metadata separates corrected runs
  in saved comparisons and rejects older dice references. Old artifacts remain
  untouched; a new user-run baseline and parity check are required. Candle
  checks still cannot recover true intrabar price order or exact fill times.
- Validation: 751 passed, two existing tests still pin editable weekly caps to
  5 while current settings use 0; configs left untouched. Command:
  `$env:PYTHONPATH="python"; uv run pytest -q`. `git diff --check` passed.
  No actual-history backtest, data download, terminal request or orders run.
  Additional-pair out-of-sample collection is recorded above as pending only.

## 2026-10-23

- Added `strategy.open_trade.use_crossover_exit` (off when absent; enabled in
  the active base and crossover preset without changing other tunable settings).
  A confirmed opposite entry-EMA cross exits at the next backtest open with
  costs, or next available live quote, independent of filtered bias/entry guards.
  Earlier protective exits take priority. No immediate reverse entry on a close
  pass. Live closes target the hedging ticket and current remaining volume;
  pending sends are persisted and uncertain outcomes require reconciliation.
  Existing SL/TP/trailing remain the fallback; no terminal or actual backtest run.
  Validation: 294 targeted tests passed, one obsolete repository-config equality
  assertion excluded. Tests use synthetic candles/fake MT5; `git diff --check` passed.

- Automatic post-backtest comparison: highest final net profit within a configurable
  MTM drawdown ceiling (defaults to the existing benchmark ceiling, currently 50%).
  `backtest_comparison.enabled` and CLI switches control reporting only; no signal,
  cost, sizing or live-trading rules changed. Actual loaded price fingerprints,
  requested pairs, feeds/chart roles, starting balance, effective costs and sizing
  budgets define comparable groups. Failed/partial/legacy unverified runs cannot win.
- `comparison.json`, console deltas and an HTML comparison section show the
  previous comparable run and previous best. A managed `BEST.txt` marks the current
  qualifying winner in each group, without renaming folders or rewriting old HTML.
  Marker publication is locked/atomic and never overwrites user-authored markers.
  New comparisons establish a verified baseline; no old runs were reprocessed.
  Validation uses synthetic saved artifacts and mocked execution, not market data.
- Validation: 146 comparison/ledger/report/backtest tests passed; full suite
  619 passed, with three existing repository-config assumptions failing (preset
  equality and fixed caps). These do not indicate invalid user-tuned settings.
  Config values were not reset. No actual-history backtest or live process run.
- Recorded the user's config policy in AGENTS.md: settings may change anytime;
  exact-value tests belong in controlled fixtures, not active repository configs.

- Added opt-in `_base_crossover.yaml` and `--base-config` in backtest/monitor;
  existing active/preset settings were not edited. H4/H4 EMA20/100 memory,
  two actual fills per cross (configurable), identical fresh recovery entries,
  no same-pair overlap, stop 1.5 ATR / trail 1.5R / target 10R. Hours, blackout,
  daily-loss and weekly loss guards retained; entry/portfolio caps off.
- Shared closed-bar incremental indicators and recovery memory survive rolling
  history/restarts. Live counts broker-confirmed distinct positions since the
  cross, uses isolated magic/memory, and writes pending sends before ordering.
  Missing history/ambiguous sends fail closed; the panel shows cross time/usage.
- Crossover backtests simulate independent candidate lifecycles, then admit
  actual fills globally (including weekly halts) before using attempts/slots.
  Remaining positions are marked at tape end, labelled `end-of-data`.
  Existing strategy paths retain their old behavior. Scaling+crossover refused.
- Tests: full suite 571 passed, two existing config assertions expect weekly
  cap 5 while the active/older presets contain 0; left those files unchanged.
  No backtest or terminal/live process run. H4-only trailing remains coarse.

## 2026-10-22

- **Portfolio weekly entry cap: 5 across all pairs.** Added configurable
  `limits.max_trades_per_week` to active config and both presets; 0 disables it,
  absent keys preserve old behavior. UTC Monday 00:00 resets the quota (08:00
  Malaysia). Accepted entries consume slots; closes do not return slots and
  existing positions remain managed. Backtest/dice use the same chronological
  admission pass, so rejected candidates consume neither daily nor weekly quota.
  Saved run params and reference validation include the cap. Balance scaling
  with admission limits remains refused until a unified sizing pass exists.
  - Live recovers our-magic counts from broker history and saved confirmed-entry
    state. Successful sends update quota immediately, including missing-position
    discovery, before another pair reuses the history snapshot. Decisions persist
    per pair; unavailable history blocks entries, plans/failed sends consume no
    slots. Restart, UTC rollover, validation, presets, quota interactions, dice
    reference mismatch and continued management covered by synthetic tests.
  - **496 passed** with `$env:PYTHONPATH="python"; uv run pytest -q`;
    `git diff --check` passed. No actual-history backtest, report rebuild,
    terminal connection or orders run. No costs, signal timing or sizing changed.
  - Separate pre-existing execution risk left unchanged: `trader.send_entry`
    recognizes DONE only, not DONE_PARTIAL; a partial fill can be reported as a
    failure and retried. Partial-fill handling needs its own execution fix.

- **Removed stale strategy-value assumptions from the role-period test.**
  `tests/test_panel.py` now verifies positive integer periods and exact propagation
  from each config's bias/entry sections instead of pinning editable EMA/ATR
  settings (including the obsolete H1 preset EMA50 expectation). Kept legacy-key
  checks and added a synthetic nondefault-period collision regression; no tests
  deleted. Strategy, configs and trading code unchanged. **479 passed** with
  `$env:PYTHONPATH="python"; uv run pytest -q`; `git diff --check` passed.
  No backtest, report rebuild, terminal calls or orders run.

- **D1 bias / H1 execution supported.** Added H1->D1 to shared timeframe
  validation and actual broker-chart selection, including the legacy-source
  requirement for an exported Daily chart (no Daily resampling fallback).
  Existing H1 checks, closed converters, marks, costs, sizing, recovery entry,
  limits and restart protections remain. New folders label this combo `_D_H1`.
  Active config and presets were not changed. Report/dice/live chart selection
  follows the same roles; saved references still require exact timeframe parity.
  - Synthetic tests cover Daily completion boundaries, future-candle isolation,
    short/DST day availability, Daily warmup, missing Daily refusal, no resampling,
    H1/D1 real-path trade parity, report charts, naming and ledger compatibility.
    No actual-history backtest, parity/dice experiment, report rebuild, terminal
    connection or orders run. Full suite: **477 passed, 1 unrelated failure** with
    `$env:PYTHONPATH="python"; uv run pytest -q`. The unchanged assertion at
    `tests/test_panel.py:117` expects slow EMA50 in `_base_h1h4.yaml`, which now
    contains EMA100; that preset and assertion were left untouched by this change.
    All new-combination tests passed; `git diff --check` passed.

- **Timeframe-labelled backtest folders.** New runs append `_H4_H1` (H4 bias,
  H1 entry) or `_D_H4` (Daily bias, H4 entry) to the existing Malaysia timestamp,
  automatically from resolved timeframes. Existing directories and dice stamps
  untouched; config continues to record Daily as D1. Naming/ledger regression
  tests added. No strategy, costs, sizing, order behavior or saved results changed.
  No backtest, report/ledger rebuild over saved runs, terminal calls or orders run.
  Verification: **469 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`);
  `git diff --check` passed.

- **Report chart Previous/Next navigation.** Popup buttons and Left/Right keys
  follow the current filtered table order, update trade details/counter, retain
  the selected timeframe when available, and disable at first/last trade.
  Existing popup reused; missing charts and empty/changed filters clear stale
  charts safely. Keyboard shortcuts leave inputs and modifier shortcuts alone.
  - Added Node fake-DOM/Plotly runtime tests for navigation, filters, boundaries,
    missing charts, blocked/closed/reopened windows and timeframe fallback, plus
    report-input preservation. **466 tests passed** with
    `$env:PYTHONPATH="python"; uv run pytest -q`. Not visually browser-tested.
  - Rebuilt only `backtest_results/20261022_205535/report.html`; verified all
    original non-HTML artifact SHA256 hashes unchanged, including trade CSVs,
    params, summaries and equity. No strategy, costs, sizing or execution change.
    No backtest, terminal connection or orders run. Other reports stay unchanged.

- **Separate demo/real order launchers; generic launcher retired.** Added
  `start-trader-demo.bat` / `start-trader-real.bat`, each opting into orders for
  exactly its selected account. `--dry-run` can override for plans only; final
  account/journal arguments cannot be redirected by forwarded flags. Global
  dry-run default, USE_REAL, strategy/cost/risk settings and `.env` untouched.
  - Account selection narrows existing enabled flags, never enables an account
    or falls back to the other account. Both may be enabled without loading or
    trading the unselected one. Login, server and actual MT5 demo/real mode are
    verified after initialize and immediately before entries/SL modifications;
    unavailable/mismatched information fails closed, without stamping an entry.
  - Separate demo/real journals; existing per-tag restart and weekly state kept.
    A workspace OS lock prevents two panel/trader instances. Stop one before
    starting another; other workspaces/tools/manual terminal switches remain
    outside this lock and must not share the active terminal.
  - Synthetic tests suppress dotenv loading; account selection, disabled flags,
    broker-type mismatch, account switching during request construction, no-send/
    no-stamp behavior, CLI dry override, lock release and static launcher flags
    are covered. No launcher, terminal/API connection, orders, backtest or report
    rebuild run by the agent. Verification: **460 passed** with
    `$env:PYTHONPATH="python"; uv run pytest -q`; `git diff --check` passed.

- **Separate wick switch for remembered entry.** `strategy.entry.recovery_use_wick`
  defaults true in all three base configs, preserving existing behavior. False
  disables touch-based arming and refresh only; qualifying closes below EMA20
  (LONG) / above EMA20 (SHORT) still qualify. Trigger, expiry, crossover/EMA100
  cancellation, costs, risk and restart guards unchanged. Shared core covers all
  callers. Tests: **432 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`),
  including mirrored wick enable/disable, close-only setups, disabled refresh and
  invalid boolean. No backtest, terminal call, orders or report rebuild run.

- **Remembered-pullback entry + Pepperstone H1 extension.** New optional
  `use_recovery_entry` mode (OFF) replaces other entry-candle gates. Configurable
  expiry defaults to four subsequent candles; fresh touches/closes reset it.
  A later close beyond the immediately previous high/low triggers, with no extra
  EMA-position/body filter. Entry-EMA cross/tie clears pending state; configurable
  `recovery_cancel_beyond_slow` controls slow-EMA-close cancellation (default ON).
  Closed-history replay consumes each trigger and is shared by offline, dice real,
  panel and live gate. Existing risk/cost/next-open/limits/restart guards unchanged;
  pending cancellation never closes open trades. New report reason: recovery_break.
  - Imported all ten selected Pepperstone H1 exports, normalized with the existing
    US-DST server-clock rule. Originals archived byte-for-byte; vendor data and
    original H4/D1 manifest untouched. Separate `manifest_h1.json` pins H1 to the
    base dataset, preserving saved H4 identities. Per pair 37346 H1 bars, except
    NZDUSD/USDCHF 37345, 2020-01-02 through 2025-12-31 server dates.
  - H1 matches every supplied H4 OHLC exactly. 13 partial H4 periods per pair
    (14 NZDUSD/USDCHF) have fewer than four hourly candles; recorded as warnings,
    not assumed to be missing trading hours. No filling/resampling/trimming.
    Initial strict import refused partial periods before publishing/moving inputs;
    the final import retains them with explicit coverage warnings.
  - Broker offline H1/H4 uses actual exported charts, H1 checks/closed converters/
    drawdown marks and bar-close exit booking, with no vendor/M1 substitution.
    Reports and dice source/parity checks pin the extra H1 manifest. Active
    timeframes, old strategy switches, sizing and costs were not changed.
  - Synthetic tests cover mirrored setups/triggers, delayed/latest-edge breaks,
    strict boundaries, refresh/expiry/consumption, crossover and cancellation,
    legacy-off equivalence, fake-MT5 shared gate, H1 archive/identity/failure/gaps,
    actual-chart loading, H1 real-path parity and report labels/charts.
    No actual-history backtest, parity/dice experiment, report rebuild, terminal
    call or orders run. Verification: **427 passed** with
    `$env:PYTHONPATH="python"; uv run pytest -q`; `git diff --check` passed.
    Input-only validation verified all 373458 normalized H1 bars' file hashes,
    raw archive hashes, required charts/converters, unchanged base manifest and
    inactive recovery switch. H1 extension SHA256:
    `8628b43cc3287df371c6dc2bc2aeec1ab344e99fb2708b0ebbf5a2b90aef50ba`.

- **Optional pullback cross into the EMA gap added; ships OFF.**
  `strategy.entry.w1_cross_into_gap: false` in active `_base.yaml` and the
  H4/D1 preset. SHORT: aligned downtrend, candle opens below EMA20 and closes
  strictly above EMA20/below EMA100; LONG mirrors it. Closed signal candle,
  existing next-bar offline execution and live closed-bar gate. Any enabled
  W1 pattern qualifies; existing pattern switches are preserved. Uses configured
  EMA periods. Wick-only touches and equality do not qualify; wick-depth setting
  applies only to the original patterns. Other gates remain enforced; HR2
  conflicts with the pullback candle direction and must remain off to use it.
  - Shared signal core serves backtest, dice real path, panel and live gate.
    Reports recognize `pullback_cross` as Pullback cross into EMA gap, including
    summary/filter and verified historical reconstruction. SL/TP, costs, sizing,
    entry hours, trade limits and restart guards unchanged. No claimed improvement.
  - Tests: **397 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`).
    Synthetic LONG/SHORT, strict boundaries/alignment, optional and combined
    switches, legacy-off equivalence, HR2 conflict, report label and fake-MT5
    shared gate checked. No actual-history backtest, parity/dice experiment,
    report rebuild, browser test, terminal call or orders run.
  - Enabling is a new experiment: pre-declare before a new user-run baseline
    and matching parity gate. Dice compares exact saved strategy settings;
    adding even a false key can require a new matching reference. Flat-market
    detection remains pending research, not part of this change.

## 2026-10-21

- **Malaysia entry hours + report lot size.** User approved 09:15–23:00 local
  entry-only scope. Both base configs now enable `limits.entry_hours` with
  configurable `enabled`, `utc_offset_hours`, `start`, `end`. Fixed UTC+8 has no
  daylight saving; broker timestamps stay normalized UTC and broker candle
  boundaries are not moved. Window start inclusive/end exclusive, midnight wrap
  supported; malformed settings rejected. Missing config preserves old behavior.
  - Shared check in live strategy entries, backtest execution and dice simulation
    uses fill time (live current UTC time, offline next candle open), never the
    signal candle open. Rejected live bars retain the restart stamp; no queue.
    Open-position stops/targets/trailing keep running outside entry hours.
    Manual order-testing utilities are not changed by this strategy filter.
  - Saved params record the window; dice rejects mismatched/older unfiltered
    references. Entry-hour skips are included in the backtest funnel. No sizing,
    costs, holiday rules or existing pair/day/week definitions changed.
  - Report adds Lots, Entry time (UTC), Entry time (Malaysia UTC+8). Latest old
    report rebuilt for display only; its trades/results are NOT session-filtered.
    H4 entries still occur only at broker candle boundaries, not at 09:15 itself.
  - Verification: **367 tests passed** (`$env:PYTHONPATH="python"; uv run pytest -q`);
    Node JS syntax check passed. Browser and terminal behavior not tested.
    Report-only rebuild verified original trading CSVs/params unchanged.
    No actual-history backtest, parity/dice
    experiment, live/terminal call or real order run. User needs a new baseline
    before the parity gate and random comparison; previous readiness is superseded.

- **Entry-reason diagnostics added; rules and financial results unchanged.**
  User asked to compare wick-touch vs cross-candle entries before changing the
  strategy. `signals.check_entry` now reports diagnostic `entry_reason` only;
  acceptance/gate math stays unchanged. Modern W1 labels the signal candle's
  opening side of EMA20 (both LONG/SHORT); rejected entries stay Unknown,
  disabled W1 is Other entry rules, old W1 is Legacy W1, not guessed modern W1.
  - `scan_pair` carries the reason and `simulate` saves `entry_reason` plus
    `signal_bar_time` (signal candle OPEN timestamp, not the next fill candle)
    in trade CSVs. Candidate labels change no costs, sizing, P/L or trade limits.
    Dice candidates label A/B random entries explicitly rather than calling
    them wick/cross. Old references may omit only these new diagnostic columns;
    all original financial/execution columns still undergo full parity checks.
  - `report.html` gains an Entry reason column/filter and all-pair pattern table:
    trade/win/loss counts, net-USD win rate, net USD, average USD and average R.
    `entry_summary.csv` includes combined and per-pair groups, scratch counts
    and negative-USD sums. Summaries use accepted closed trades after costs and
    portfolio filtering, not all signals. Scratch trades stay in the win-rate
    denominator. No automatic pattern ranking, disabling or strategy retuning.
  - Historical labels are reconstructed only with the run's saved modern W1
    config and matching broker/research source identity/checksums, exact next-bar
    entry alignment, qualifying prior signal candle and matching saved ATR
    (allowing its existing five-decimal rounding). Otherwise Unknown. Tooltips
    identify reconstructed labels. Original trade CSVs are never backfilled.
    Arbitrary/invalid label strings normalize to Unknown, not injected into HTML.
  - Rebuilt **only** `backtest_results/20261021_202430/report.html`, adding its
    `entry_summary.csv`. Verified all original CSV artifacts and params hashes
    unchanged. All **786** existing trades reconstructed: **448 Cross candle,
    338 Wick touch**. This is reporting over existing trades, not a new backtest
    or performance conclusion. Other old runs remain unchanged unless rebuilt.
  - Read-only `validate_reference_setup` confirmed that this baseline's source,
    config, all enabled pairs and nonempty sample fit current dice setup. The
    next step is the **user-run --real-only parity gate**, not an already passed
    gate. Random B test is ready only after that passes and its design is fixed.
    No actual-history parity or random draws run by the agent.
  - User accepts the year-end final-candle limitation and removed its action item;
    it is NOT reintroduced as a repair task. Source audit metadata / saved run
    identity remain untouched. Existing no-trade dates block NEW entries only;
    they do not force already-open positions flat. No holiday rule changed.
  - Tests: **350 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`).
    Synthetic fixtures verify LONG/SHORT classification,
    disabled/legacy/failed W1, metadata-only execution invariance, post-cost group
    accounting, unknown/unsafe labels, historical-source/alignment/ATR guards,
    report filtering and old-reference diagnostic compatibility. JS syntax checked
    with Node; not browser-tested. No backtest, parity/dice experiment, live or
    terminal call. Reusing inspected full-period results to choose a pattern is
    not out-of-sample evidence; counts/averages are descriptive only.

- **Manual Pepperstone H4/D1 CSV intake and broker-only offline mode completed.**
  User supplied/confirmed all 20 `_PEPPERSTONE` MT5 chart exports for the 10
  enabled pairs (including the four initially missing the tag, since renamed).
  AUDJPY is parked and excluded, not counted missing. Read-only audit verified
  ascending unique timestamps and valid OHLC/volume. Per pair: **9341 H4 + 1557
  D1**, raw broker dates 2020-01-02 through 2025-12-31.
  - Ran `mkdata --import-pepperstone --batch --src data --out-dir data/pepperstone`
    (with `PYTHONPATH=python` via uv). Original tab-separated exports moved from
    the root to `data/pepperstone/raw/`, after verified archived copies existed;
    bytes/checksums preserved. Normalized `<SYM>_H4.csv` / `<SYM>_D1.csv`, 20
    source/coverage sidecars and a manifest live in `data/pepperstone/`.
    Vendor H1/M1, original vendor folders and derived research files untouched.
    Manifest SHA256:
    `f6b67d52faa3a0e097ceb9bf64564ce27688278bf3a52b9b92a2b3df2803b081`.
  - `broker_data.py` shares validated intake, identity/checksum paths, offline
    source settings and closed-price conversion feeds. MT5 UI timestamps were
    normalized from Pepperstone's documented GMT+2 winter/GMT+3 **US DST** clock
    (New York + 7 hours), not treated as UTC or Europe DST. No broker candle
    OHLC resampling, synthetic H1 helper, price filling or date trimming.
    Clock source: https://pepperstone.com/en/about-us/trading-hours.
    Import date is recorded; original export date was not supplied/invented.
  - H4/D1 daily OHLC audit matched every overlapping server day except the last
    day in each pair: H4 stops at **2025-12-31 16:00** (five candles that day),
    while D1 includes later quotes. The 20:00 H4 is missing in every export.
    Preserved and flagged in manifest, console and report; no reconstruction.
    No 2019 warmup files were provided: normal warmup consumes early 2020 bars.
  - Active `_base.yaml` and H4/D1 preset now expose `backtest_data`:
    `use_broker_csv: true`, `broker_csv_dir: data/pepperstone`, supported source
    `broker_server_clock: new_york_plus_7`, and explicit `position_checks: H4`.
    Disable the source switch for legacy selection; an explicit research CLI
    opt-in instead selects its existing source. Live fetching/settings untouched.
    `run-backtest.bat` needs no new arguments; dice reads the same data settings.
    Missing active charts or checksum/source mismatches fail, not silent skips.
  - H4 is the actual price tape for metrics/marking; no vendor H1/M1 inputs.
    EURGBP and JPY crosses use broker GBPUSD/USDJPY H4 converters. Closes become
    available only at the following broker open, never at the candle's start.
    Both-stop-and-target candles still count as stops; coarse exits now book
    at bar close in this broker mode, so same-timestamp portfolio decisions do
    not see whole-bar outcomes early. Actual intrabar time/order is unknown.
    Trailing/BE remain OFF; coarse behavior is approximate if enabled later.
    Drawdown marks use H4 closes at availability time; report labels say so.
  - Reports load exact H4/D1 manifest charts and omit the nonexistent raw H1
    view. Params/parity artifacts record broker dataset identity, H4 resolution
    and bar-close exit timing. Dice rejects old research/vendor/M1 references
    and requires a NEW matching user-run pin plus full-trade parity. No costs,
    spread/swaps/commission/slippage, risk band, benchmark or selection values
    changed. Raw `<SPREAD>` zeros do not turn configured costs off. Existing
    approximate swap rollover timing was not redesigned.
  - Input-only readiness check resolved all 10 enabled jobs, both broker converter
    feeds, all 20 normalized/archived checksums, and H4 checks without H1/M1.
    Tests: **337 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`), including
    US-vs-Europe DST, byte-preserved archival, failure safety, final-day warnings,
    closed converter availability, no vendor helpers, synthetic real/dice parity,
    stop-first ambiguity and bar-close booking, exact-source H4 report/MTM labels.
    Full 2020-2025 would expose reserved 2023-2025; holdout decision remains open.
    **Not run:** actual-history backtest, real-only parity, random dice, MT5/API
    connection, orders or ledger rebuild. Only intake, data validation and tests ran.

- **User-approved vendor-derived H4/D1 research route built and data generated.**
  After broker requests stalled, user explicitly accepted stored-clock aggregation
  as an exploratory alternative, not broker/live parity. Extended `mkdata --research`
  to stream consolidated M1 directly into configurable fixed-duration charts.
  `--all-existing` includes all 11 pairs with source files, including parked AUDJPY;
  `--symbol`, `--research-timeframes` and `--chunk-rows` control the build.
  No new dependencies or source/config moves; existing vendor/broker commands remain.
  - Ran `$env:PYTHONPATH="python"; uv run python -m quant.mkdata --research --all-existing --src data --out-dir data/vendor_derived_2015_2025`.
    Produced 22 CSVs + 22 coverage/source sidecars + manifest: **232037 H4+D1
    candles**, all 11 pairs spanning 2015-01-01 through 2025-12-31. All 10
    currently selected pairs are covered; AUDJPY stays disabled in config.
    Dataset manifest SHA256:
    `e2297f26c674cff8346331759c0ed333a2cad8b0274b943f6675b2b4799fd75e`.
  - Boundaries = floor timestamps as stored, left-closed 00/04/08/... buckets
    and midnight days. The existing source clock is unverified; UTC labels are
    not independently verified timezone conversion. No empty bars or prices are
    filled. Partial bars retain observed OHLC and `n_minutes`; metadata records
    partial counts, absent periods, source gaps/endpoints and per-year coverage.
    Short sessions/weekends/quiet minutes can also be partial; no completeness
    certification. The first observed quote approximates a partial candle's open.
    No fabricated pre-2015 warmup; normal engine warmup consumes initial history.
  - Sources were read-only. Checked all derived files for order/duplicates,
    expected years, counts and valid observed-minute bounds; verified chart
    SHA256 hashes and unchanged original H1/M1 size/mtime snapshots. All passed.
    Data remains local/ignored, separate from normal broker input paths. Staging
    and overwrite refusal protect existing files; publication remains per-file.
  - Backtest now accepts explicit `--research-data-dir` and a source `--data-dir`;
    manifest source snapshots and derived checksums must match. Normal H4/D1
    mode still reads broker files and rejects labelled derived files without
    opt-in. Research M1 load failures are errors, not silent H4 fallback. Run
    params save source identity/hash; portfolio settings now always persist even
    when no trades are dropped. No strategy/cost/sizing/pair-selection changes.
  - Shared `load_chart_frames` feeds backtest and dice. Dice reads the configured
    execution/regime roles, calculates ATR on execution bars, maps only completed
    regime bars and passes actual bar duration to stop checks. A=random timing
    and direction; B=random timing with valid strategy LONG/SHORT direction.
    Unsupported modes/scaled references are refused. Engine timeframe/strategy
    support is not universally expanded; `edge_probe` remains H1/H4-only.
  - H4/D1/research dice requires an explicit NEW user-run reference. Source,
    timeframe, strategy, costs, sizing, limits and symbol selection are checked
    before simulation; complete trade rows and pooled totals must match before
    dice draws. Empty comparisons are refused. Parity/config artifacts record
    the research identity. Synthetic H4/D1 fixtures produce identical trades
    through both real-entry paths, not merely equal counts.
  - Reports load exact manifest charts, display RESEARCH ONLY and refuse chart
    substitution if manifest/source integrity changes. RUNBOOK/config/STRATEGY
    docs describe opt-in and limitations; TESTLOG records the pending experiment
    design, not results. A full 2015-2025 run would expose reserved 2023-2025;
    user must choose evaluation/holdout treatment first. No holdout split built.
  - Tests: **325 passed** (`$env:PYTHONPATH="python"; uv run pytest -q`), including
    streaming-boundary invariance, partial/gap handling, validation/staging,
    source/hash/opt-in guards, configured H4/D1 mapping and real-path parity,
    reference rejection, full-trade parity and exact-source report warnings.
    No actual-history backtest/parity/dice experiment, MT5 connection or orders
    run for this change. Only the requested data conversion and data validation ran.

- **2020-2025 fallback coverage probe: NOT CONFIRMED for any enabled pair.**
  User approved small read-only endpoint/warmup checks, not a full download or
  backtest. Checked AUDUSD, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, NZDUSD,
  USDCAD, USDCHF and USDJPY on D1/H4/H1/M1. Requested one candle at/before
  2020-01-03 23:59 UTC and 2025-12-31 23:59 UTC, plus 101 pre-2020 candles
  on D1/H4 when earlier calls completed. Each pair/timeframe worker had a
  10-second total budget; a timeout does not mean all endpoint/warmup calls
  were reached, nor does it establish the broker's retention limit.
  - An initial temporary probe-wrapper argument error was corrected before
    the actual terminal checks. In the corrected run, 39 of 40 feed workers
    timed out. GBPUSD M1 returned 2026-07-15 19:34 UTC for BOTH historical
    anchors: rejected as outside the requested windows, not coverage evidence.
    No D1/H4 prefix warmup was verified in this run.
  - The first worker reached Pepperstone-Demo and reported maxbars 100000;
    that alone does not prove a healthy server connection. A subsequent bounded
    terminal connection/tick diagnostic also timed out before printing a result.
    Current connection status and continuous historical coverage remain unknown.
  - No CSV writes, data replacements, orders, account switches, history-setting
    changes, backtests or dice runs. Tests not rerun (documentation-only update).
    Next restore/verify the terminal connection and manually load a historical
    chart before repeating requests; do not assume shortening the range fixes
    a stalled history bridge. Previous EURUSD D1 2020/2025 sample successes
    remain samples only, not proof that the present terminal session works.

- **Broker availability check attempted; full history not verified.** User
  confirmed the existing calendar range 2015-01-01 through 2025-12-31 for
  all 10 selected pairs (export end exclusive 2026-01-01). Existing H1 file
  endpoints were inspected; the first intraday timestamp differs by pair.
  Offline batch `mkdata --broker ... --plan` passed. The initial full-export
  invocation was interrupted by the user; subsequent inspection confirmed
  `data/broker_review_2015_2025` does not exist, so no export files were published.
  - Read-only EURUSD connection reached Pepperstone-Demo; terminal maxbars
    reported 100000. Latest closed D1 returned 2026-10-20; one-candle probes
    returned 2020-01-03, 2025-01-03 and 2026-01-05 at the corresponding January
    anchors. The 2015-01-05 query failed (`Terminal: Call failed`), then the
    pre-2015 warmup request stalled until the 240-second command timeout.
  - Follow-up isolated D1/H4/H1/M1 probes requested up to 99999 closed bars
    each; every probe timed out after 25 seconds and its own child process
    was stopped. This establishes neither the earliest available broker date
    nor that 2015 history is absent. H4/H1/M1 historical coverage is unverified;
    successful D1 samples do not establish complete daily coverage either.
  - No CSVs written, orders, backtests or dice runs; existing data and terminal
    history settings unchanged. No tests rerun for this documentation-only
    update. Next diagnose terminal history loading/retention; do not treat the
    timeouts as proof of the broker's absolute retention limit. A 100000-bar
    chart limit is much smaller than eleven years of M1 data; raising it alone
    is not a guarantee the server supplies the requested history.

- **Config-driven broker history exporter built, second stage (tooling only).**
  Extended `quant/mkdata.py` rather than adding a new entry point/dependency.
  `--broker` uses the currently logged-in terminal read-only, with guarded MT5
  import and initialize/shutdown cleanup; it neither reads account credentials
  nor switches accounts or sends orders. `--batch` reuses selected config pairs;
  `--symbol` selects one. Explicit UTC `--start` and exclusive `--end` are required;
  `--plan` previews without connecting or writing. Original vendor commands work.
  - Reads configured execution/regime/position-check charts; standard MT5
    timeframes are supported without the engine's H1/H4 vs H4/D1 restriction.
    Engine/probe strategy-combo support itself is unchanged. H1 and needed USD
    converter feeds remain included for existing backtest/report consumers.
    The existing conversion map is now shared from `rules.py`, not duplicated.
    Six-letter FX symbols and USD accounts match current engine sizing scope;
    broker suffixes resolve separately and are recorded in metadata.
  - Warmup defaults to the largest configured warmup/known indicator period;
    `--warmup-bars` overrides it. Fetches actual preceding broker chart bars,
    using a following open as closure proof; all feeds share the resulting
    earliest prefix. Insufficient chart warmup or auxiliary/M1 start coverage
    fails rather than silently falling back. No calendar resampling or gap fill.
  - Streams bounded queries (`--chunk-days`, default 31); excludes the current
    candle using each feed's last closed broker candle. Rejects malformed data,
    invalid/non-finite prices/volumes, duplicates and descending timestamps.
    Reports actual endpoints, leading/trailing coverage, empty chunks and gaps
    (including normal sessions/weekends/DST; not certified missing trading bars).
    Monthly gap checks use calendar months, not a hardcoded 30-day duration.
  - `<SYM>_<TF>.meta.json` records source/server, broker symbol, export date,
    requested/actual UTC coverage, warmup and gap statistics, not login/secrets.
    Refuses existing CSVs/sidecars unless `--overwrite` is explicit; stages all
    feeds before publication, so collection failures preserve existing files.
    Publication is per-file, not transactionally atomic across the whole bundle.
  - RUNBOOK/config docs describe preview/export, retention constraints, source
    review and promotion. Default output names match existing data consumers,
    but use a fresh review folder first: batch still reads `data/`, and existing
    vendor H1/M1 must not be silently mixed with broker H4/D1. Export metadata
    does not impose a trade-start filter on the current backtester.
  - Tests: 308 passed (`$env:PYTHONPATH="python"; uv run pytest -q`), including
    config selection/converters, alternate broker timeframes, prefix closure,
    current-candle exclusion, chunk boundaries, monthly gaps, invalid rates,
    unavailable warmup/M1 history, overwrite safety, cleanup, offline preview
    and the unchanged vendor CLI. Synthetic rates/fake MT5 only;
    no broker connection, real export, backtest, live order or dice run.
    Actual pairs/date range remain unconfirmed. Adaptable dice is still next
    after history review/collection, not part of this change.

- **Pair-entry protections built, first stage only.** Active `_base.yaml` and
  `_base_h4d1.yaml` now enable `limits.max_trades_per_pair_per_week: 2`
  (0 = off) and `limits.disable_pair_after_daily_loss: true` (false = off).
  Older configs without the keys keep both disabled; invalid counts/booleans
  are rejected. The H1/H4 preset is unchanged.
  - Week = UTC Monday 00:00; day = UTC calendar day. Count actual entries,
    not signals, rejected orders or dry-run plans. Partial live fills of one
    position count once. A fully closed position with negative net P/L,
    including costs, blocks its pair for the rest of the closing day, even
    when opened in an earlier week. Floating losses and scratch/winning
    positions do not trigger it. Other pairs and open-position management
    remain subject to their existing guards.
  - Shared guard decisions in `limits.py`; backtest enforcement joins the
    existing chronological portfolio pass, with exits before equal-time
    entries. When either pair guard is enabled, the portfolio daily cap also
    runs inside that pass: rejects use no entry quota and their exits cannot
    create a daily loss block or weekly loss halt. Drop reasons and both
    controls are recorded in run params. Existing per-pair simulation's
    overlap/one-entry-per-day candidate suppression is unchanged; this is not
    a replay of candidates suppressed before the portfolio pass.
  - Live recovers state from magic-owned entry history after restart. For
    today's exits, complete position history includes older entry fees and
    manual/close-by exits; partial closes wait for full closure. Missing
    account/position history blocks new entries without stamping the bar, so
    it retries; account-history exceptions no longer skip position management.
  - Existing H1/H4 dice filtering is wired to the same new limits to avoid
    silently ignoring them. No timeframe/random-model redesign in this stage.
  - **Compatibility guard:** balance-scaling backtests with either new pair
    guard enabled are refused before simulation. The existing later scaling
    pass can remove trades and invalidate already-counted quota/loss state;
    a unified sizing/admission pass is needed before that combination is safe.
    Fixed-dollar sizing remains selected, with $4-$5.50 scope/base 0.01 lot
    unchanged. $200 account size is only being considered; benchmark stays $100.
  - Tests: 282 passed (`$env:PYTHONPATH="python"; uv run pytest -q`), including
    weekly/daily resets, equal-time close/entry, net-cost loss, rejected-trade
    state, other pairs/magic, partial fills/closes, old entry fees/manual
    closes, restart recovery, dry plans, failed sends, history failure,
    config validation and the scaling incompatibility guard. Fake MT5 only.
    No backtest, terminal connection, orders, history export or dice experiment
    run. Documentation updated; history then adaptable dice remain next stages.

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
