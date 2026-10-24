# Test Log — every run, one row

The single index of what we tried and what it did. Newest first.
Full numbers live in each `backtest_results/<run-id>/` (params.json is the truth); this is the readable tier.

## Pass line (fixed before each run — do not move after seeing results)

- Acceptance = STRATEGY.md §12 + `configs/_base.yaml benchmarks:` (graded verdict: PASS/WARN/FAIL per run).
- Probe verdict (pre-decided 2026-10-17): CONFIRMED iff pooled onset mean edge ≥ 0 AND mean − 2×SE > 0 at **both** 48 and 72 bars. 24-bar horizon = info only, never used to pick a horizon afterwards. Per-pair rows = information only, never verdict material.
- One rule change per run. The variant count is the row count below.

## Four-pair evaluation preparation — frozen design (2026-10-24; no run)

- User authorized finishing the isolated setup, 2019 preparation wiring and
  exporter clock repair. This authorizes code/tests and offline dataset assembly,
  NOT an actual-history backtest, dice experiment or orders.
- Evaluation universe fixed before strategy results: EURAUD, GBPCAD, AUDCAD and
  CADJPY, pooled under one portfolio. No keep/drop decision from per-pair results.
  EURNZD/GBPCHF remain untouched reserve strategy results; AUDJPY remains parked.
- Preparation prices: actual UTC 2019. Trading start: 2020-01-01 inclusive;
  end: 2026-01-01 exclusive. Indicators may read preparation candles; trades,
  sizing, quotas, loss state, exposure and scored equity may not inherit 2019
  trading. No pre-start open positions. Keep configured warmup guards, including
  validation of closed preparation candles on both configured chart roles.
- Preserve the current active strategy/risk/limits/benchmarks in a separate
  frozen base snapshot; do not retune them or modify active configs/selection.
  Freeze exact snapshot hashes and the calibrated cost proposal into the isolated
  setup under `data/four_pair_evaluation_20261024/`. H4 execution / D1 bias / H1
  checks are this frozen choice, not a new restriction on other supported combos.
- Costs fixed to the previously pre-declared recent-quote proposal: EURAUD 15,
  GBPCAD 18, AUDCAD 7 and CADJPY 14 broker points, exact proposed USD swaps.
  Commission 0 USD/lot/side and slippage 0 pips remain explicit Standard-account
  assumptions, not measured fills. Triple-Wednesday is the existing approximate
  observed-UTC-date model (booked on Thursday); exact rollover is not claimed.
  Current financing/recent demo quotes do not reconstruct historical costs.
- Primary first-evaluation rule: at least 100 pooled accepted trades and at
  least one trade in each of the four pairs; otherwise INSUFFICIENT, not PASS.
  Require positive net USD and TOTAL PASS against ALL frozen benchmark bands
  (currently expectancy >= +0.10R, PF >= 1.50, MTM DD <= 30% of USD 200,
  >= 2 trades/month and worst-year R >= -20). WARN is not PASS. Use the exact
  isolated snapshot, not future edits to active settings. These are pre-decided
  reporting criteria, not an invented result or a claim of statistical certainty.
- A primary PASS is not full strategy validation: STRATEGY section 12 still
  requires separately authorized cost stress, neighboring-parameter robustness,
  contribution concentration review and a matching-reference random comparison.
  No automatic second experiment or claim of independently unseen date regimes.
- Assemble real UTC broker sources offline into a NEW checksummed bundle:
  original chart imports + corrected new-pair API collection + full-2019 API
  collection. Identical overlaps deduplicate once; conflicting OHLC/volume fails.
  Never fill or average missing prices or replace original inputs. Missing
  evaluation history for a parked pair must stay visible, not silently borrowed
  from vendor data. Preserve known final-day and NZDUSD preparation-hour warnings.

### Preparation outcome — 2026-10-24 (setup complete; no strategy result)

- Frozen profile: `data/four_pair_evaluation_20261024/configs/`. Exactly the four
  declared pairs load/are selected. Effective calibrated costs propagate without
  changing active strategy/risk/limits/costs/benchmarks or any live settings.
  `evaluation_plan.json` pins six profile files, source base, cost proposal,
  broker identity and 22 engine-file hashes. `input_verification.json` records
  independent input-only checks; its scan/simulation functions were blocked.
- Built `data/pepperstone_prepared_2019_2025_20261024/`: 51 H1/H4/D1 charts.
  Verified all original source hashes, all 104 source price files unchanged,
  exact timestamp/price/volume union, zero CSV price roundtrip difference and
  deterministic identical-overlap deduplication. Source gaps remain warnings.
  Sixteen symbols have evaluation history. Parked AUDJPY has preparation only;
  no missing 2020-2025 broker prices were invented or borrowed from vendor files.
- Optional window now gates fills before any simulated trading state, while
  retaining indicator prefix. Metrics/equity exclude preparation; saved windows
  distinguish reference/parity/comparison groups. Checks retain all supported
  execution/bias combinations. CLI/config may disable or change dates, but doing
  so changes this frozen experiment and requires a new declaration before results.
  Final boundary-fill-day regression confirms daily admission uses the fill's
  trading day, not the preparation signal day. Engine hashes were refreshed
  before any actual-history experiment; strategy/costs/verdict rules unchanged.
- Exporter root cause fixed: price validation formerly labelled server epochs
  UTC and queries used the wrong clock. Date requests, returned candles, warmup,
  anchors and last-closed checks now use a consistent explicit broker API clock,
  with Pepperstone auto detection, US DST and documented override controls.
- Initial focused synthetic tests: 363 passed. Final full suite, including the
  added DST/bundle-report and boundary-fill-day cases: 877 passed and two pre-existing editable
  weekly-cap assertions failed (expect 5, active value 0); settings unchanged.
  Command: `$env:PYTHONPATH="python"; uv run pytest -q`. No actual-history backtest/parity,
  dice, strategy-result inspection, MT5 connection, orders or existing report
  rebuild. This completes setup, not an evaluation verdict or live-parity claim.

## Four-pair broker cost calibration — sampling plan (2026-10-24)

- User chose broker calibration rather than substituting shared default costs.
  Scope: EURAUD, GBPCAD, AUDCAD and CADJPY only. Conversion quotes: AUDUSD,
  USDCAD and USDJPY. No reserve-pair results, signals or returns inspected.
- Read-only current Pepperstone-Demo/USD account: symbol selection, symbol
  specifications and quotes only. No credentials, account changes, trading-flag
  changes, orders, backtests or historical-performance inspection.
- Start with three diagnostic snapshots, five seconds apart. Record broker
  swap mode/raw swaps, contract/point units, triple-rollover day, spreads from
  both symbol info and bid/ask, quote timestamps, and conversion references.
  Tick clock is not assumed identical to the verified candle clock: store
  both clock interpretations and mark uncertainty explicitly.
- Weekend/stale quotes are NOT valid spread calibration samples, including
  nonzero spreads. Freshness diagnostic threshold: 60 seconds, not a strategy
  change. Today is Saturday; a successful read does not establish an open market.
- Keep diagnostics separately under
  `data/pepperstone_cost_calibration_20261024/`. Do not create/freeze/promote
  pair-cost overrides from these weekend snapshots. Later collect fresh samples
  across different open-market sessions before agreeing the fixed assumptions.
  Broker swap specifications describe current terms, not historical 2020-2025
  financing. Quote-only reads do not measure commission or execution slippage.

### Historical-quote fallback — declared before tick requests

- Weekend symbol-info snapshots cannot calibrate spreads. Read recent broker
  bid/ask tick history instead, without any strategy simulation or orders.
- Fixed windows for each of the same four pairs: 2026-10-21, 22 and 23, at
  02:00, 08:00 and 14:00 UTC, five minutes each (nine windows per pair).
  These are inside the current entry-hours envelope and sample different
  sessions; they are not chosen from strategy returns or observed spreads.
- Request broker-clock labels using the previously verified candle conversion.
  Verify each window's first bid against the corresponding broker H1 open,
  and all sampled bids against that H1 range, before treating tick labels as
  the same clock. Archive original ticks and the H1 clock-check evidence.
- Required quality: at least 30 positive, non-crossed bid/ask observations per
  window, finite values and ascending timestamps within its requested bounds.
  Missing/invalid windows block a completed calibration; bounded retries only.
- Proposed fixed spread = the maximum per-window 95th-percentile spread across
  all nine windows, rounded UP to an integer broker point. Define percentile
  using the higher observed value; no post-result method changes. Keep per-pair
  snapshots/statistics so this recent-sample assumption is auditable, not a
  claim about full historical spreads or the worst spread possible.
- Current POINTS swaps are recorded separately in profit currency. If all quote
  checks pass, use converters from the same last declared sample window for a
  labelled USD reference, not today's stale quote. Commission/slippage remain
  explicit existing assumptions, not measurements from ticks. No active cost
  promotion or backtest is authorized by sampling alone.

### Cost sampling outcome — 2026-10-24 (no strategy experiment)

- Saturday live diagnostic: 12 stale pair snapshots, zero accepted calibration
  samples. Nonzero stale spread readings were not promoted into pair settings.
- Historical fallback completed all 36 planned pair windows plus three matching
  converter windows. 24179 pair quotes / 26712 including converters; every window
  had at least 30 quotes and passed first-bid/H1-open and full bid-range checks.
  This verifies the requested sample clock against broker candles, not unrelated
  live API consumers or exact execution parity. No history request retry needed.
- Pre-declared spread method produced:

  | Pair | Spread points | Spread pips | Current swap long | Current swap short |
  |---|---:|---:|---:|---:|
  | EURAUD | 15 | 1.5 | -0.090788284 | +0.035443296 |
  | GBPCAD | 18 | 1.8 | +0.026260429 | -0.092161942 |
  | AUDCAD | 7 | 0.7 | +0.029051047 | -0.064899752 |
  | CADJPY | 14 | 1.4 | -0.020989639 | -0.037449599 |

  Swaps above are USD per 0.01 lot per ordinary night. Raw POINTS-mode terms,
  contract/point units, triple-day code 3 and conversion references are preserved
  in the proposal. USD conversion uses Oct 23 14:00 UTC sample-window bid quotes.
  These current swap terms do not reconstruct historical 2020-2025 financing.
- Commission 0 USD/lot/side and slippage 0 pips are carried existing explicit
  assumptions, not calibrated from tick quotes. No real fills/commissions were
  requested. The sampled P95 model is not a worst-case spread guarantee or proof
  of full-history costs. No return-based method/parameter/pair selection occurred.
- Evidence: `data/pepperstone_cost_calibration_20261024/recent_ticks/` contains
  raw quotes, matching H1 checks, `proposed_pair_costs.yaml`,
  `calibration_report.json`, `calibration_base_snapshot.yaml` and
  `independent_validation.json`. All 80 listed evidence-file hashes verified;
  statistics, clock/range consistency and swap calculations independently pass.
- `uv run pytest -q tests/test_spreadcheck.py` with `PYTHONPATH=python`: 8 passed.
  No active cost/config/pair-selection changes, backtest/dice/orders, credentials
  or reserve strategy-result inspection. Sampling/proposal is complete; isolated
  evaluation approval/freeze and remaining wiring/exporter work are still pending.

## Full 2019 preparation history — pre-declaration (2026-10-24)

- User confirmed the scope: all 17 known pairs, not every broker FX symbol:
  AUDJPY, AUDUSD, EURGBP, EURJPY, EURUSD, GBPJPY, GBPUSD, NZDUSD, USDCAD,
  USDCHF, USDJPY, EURAUD, GBPCAD, AUDCAD, CADJPY, EURNZD and GBPCHF.
  AUDJPY remains parked in active selection; collecting it does not enable it.
- Collect direct broker H1/H4/D1 for 2019-01-01 inclusive through 2020-01-01
  exclusive in actual UTC. All required USD converters are already among these
  17 pairs, so the request is 51 feeds. No extra pre-2019 warmup is requested.
  This zero-extra-prefix collection setting does not disable strategy warmup.
- Purpose: prepare indicators using 2019 before a future 2020-2025 evaluation.
  No 2019 trades/results may enter that intended evaluation. Downloading files
  alone does not enforce this; explicit intake and test-start boundaries remain
  separate work. Do not merge/overwrite existing histories or modify settings.
- Source: current Pepperstone-Demo terminal; no credentials/account switches,
  trading-flag changes or orders. Allow bounded retries for history loading.
  Preserve original API bytes, normalize the verified broker server clock to
  UTC with US DST, and verify overlaps against the prior corrected collection.
- Destination: `data/pepperstone_all17_2019_export_20261024/` (local-only).
  Record query labels, actual UTC coverage, export date, checksums and quality
  warnings. No resampling, filling gaps, backtests or strategy-result inspection.
  Reserved EURNZD/GBPCHF strategy results remain untouched.

### 2019 collection outcome — 2026-10-24 (preparation data only)

- Completed 05:51:41 UTC: 17 pairs / 51 feeds / 136492 candles. Every pair has
  259 D1 and 1554 H4 candles; H1 has 6216 except NZDUSD 6215. All required USD
  converter pairs are included. No automatic retry was needed on initial reads.
- Verified actual UTC opens are within 2019. First open: Jan 1 22:00 UTC;
  last opens H1 Dec 31 21:00, H4 Dec 31 18:00 and D1 Dec 30 22:00 UTC.
  Query bounds were translated to this account's observed broker-clock labels
  before collection, then timestamps normalized with the existing US DST rule.
- Preserved 102 raw CSV/metadata files and verified all 204 raw/normalized feed
  checksums. All 51 feeds retain identical original price/volume strings. All
  30906 overlapping candles match OHLC/volume in the prior corrected dataset.
  Source/export time, query bounds, clock reference and audit are in the manifest.
- Cross-chart checks: no OHLC mismatch or uncovered higher candle. One NZDUSD
  H1 candle (2019-01-28 18:00 UTC) is absent, leaving one short H4/D1 group.
  Three fresh targeted broker requests still returned only the neighboring
  hours. Evidence: `missing_hour_recheck.json`. No bar was filled or invented.
- Existing exporter/intake tests: 61 passed. Full 2019 is intended preparation
  for 2020-2025 only; zero extra pre-2019 padding does not disable indicator
  warmup. Explicit test-start/intake wiring remains pending. No backtest, dice,
  orders, strategy-result inspection, active config changes or dataset merges.
  AUDJPY remains parked; EURNZD/GBPCHF strategy results remain untouched.

## Additional FX broker collection — pre-declaration (2026-10-24)

- User authorized collection only: EURAUD, GBPCAD, AUDCAD and CADJPY as the
  first evaluation group; EURNZD and GBPCHF reserved for a later untouched
  strategy check. None appears in the available saved backtest/dice params
  inspected before export; this cannot establish absence of external testing.
- Request: 2020-01-01 inclusive to 2026-01-01 exclusive, UTC, plus the active
  config-derived warmup (100 closed bars on each execution/bias chart).
  Direct Pepperstone H1/H4/D1 candles only; required H1 USD converters are
  AUDUSD, USDCAD, USDJPY, NZDUSD and USDCHF. No resampling or gap filling.
- Source: current logged-in Pepperstone-Demo terminal, without loading
  credentials, switching accounts, changing trading flags or sending orders.
  Retry temporary history-read failures with bounded attempts; persistent
  failures or insufficient history must be reported, not fabricated.
- New local-only destination:
  `data/pepperstone_unseen_fx_2020_2025_export_20261024/`.
  Preserve UTC coverage, warmup, source/export timestamps and file checksums.
  Do not replace/promote the existing active broker dataset or pair selection.
- Collection is NOT an approved backtest or a completed validation. Quality
  checks may inspect candle consistency/coverage, not signals or returns.
  Before any strategy evaluation, agree and freeze pair-specific costs,
  strategy/config snapshot, evaluation dates and pass/fail criteria separately.
  Current broker spreads/swaps are not historical financing evidence. Existing
  2023-2025 results are already inspected; these new crosses share currencies
  and market events with tested pairs and are not independent market evidence.

### Collection outcome — 2026-10-24 (not strategy results)

- Completed 05:26:47 UTC from Pepperstone-Demo: 23 feeds / 507109 candles.
  First-group and reserved-group assignments are unchanged. No history retries
  were needed; the wrapper allowed up to 12 attempts with a 5-second delay.
- Common prefix starts 2019-08-11 21:00 UTC, giving each pair 101 Daily and
  606 H4 pre-2020 candles. Each pair has 1658 D1 candles; H4 counts are 9948
  except EURNZD 9947. H1 counts: 39772 for the first four, EURNZD 39759,
  GBPCHF 39769. All include warmup; every requested calendar year is present.
- Clock finding: the API response encoded broker wall-clock values despite the
  exporter labelling epochs UTC. All 186728 overlapping converter H1 candles
  exactly match the verified existing imports after the existing US-DST-aware
  Pepperstone conversion; zero match without it. Archived all 46 original
  CSV/metadata files unchanged under `raw/`, then normalized timestamps only.
  Original query labels and actual UTC coverage are recorded separately.
- Final cross-timeframe audit: no OHLC mismatches or higher candles without
  constituent coverage. Short groups remain: H1/H4 14 each first-group pair,
  EURNZD 19 and GBPCHF 16; H4/D1 one EURNZD short group. Gaps/short sessions
  may include missing hours; nothing was fabricated or filled. Last H1 opens
  2025-12-31 19:00 UTC, H4 18:00 UTC, D1 2025-12-30 22:00 UTC (Dec 31 server).
- Reproducibility files: `collection_spec.json`, `collection_base_snapshot.yaml`,
  `timestamp_verification.json`, `quality_audit.json`, and per-feed metadata.
  Price/volume strings match originals for all 23 feeds; all normalized/raw
  checksums were verified. Existing exporter/intake tests: 61 passed.
- No strategy returns inspected, backtests/dice/orders run, active config/pair
  selection changed, credentials read or existing datasets replaced. Costs and
  pass/fail rules are not finalized; API intake/pair wiring and shared exporter
  clock repair remain separate work before evaluation. Collection TODO complete.

## Pepperstone H4/D1-only baseline — user-run reference, dice pending (2026-10-21)

Superseding update: Malaysia new-entry window 09:15 inclusive–23:00 exclusive
(fixed UTC+8) is now enabled. `20261021_202430` predates this rule and must NOT be
used as the active dice reference. Pre-declare the revised comparison and obtain
a new user-run baseline, then full-trade parity PASS, before random draws.
Report-only lot/time display changes do not change old trades. No new backtest
or actual-history parity/random experiment was run by the agent.

Update: user produced `backtest_results/20261021_202430` and inspected results.
Its config/source/pair coverage passed read-only compatibility checks; actual
`--real-only` full-trade parity and dice remain pending. Entry-reason reporting
was added without changing trading rules/results; report-only reconstruction
does not rewrite the reference trades. Missing new diagnostic columns alone
do not invalidate the old reference's financial/trading parity. Pattern tables
are descriptive, not permission to pick a winner on the same inspected sample.

**Agent work: intake/readiness/reporting only; no actual-history backtest, parity
or dice experiment run by the agent.** User confirmed all tagged files are Pepperstone/MT5
exports. All 10 enabled pairs have H4+D1; parked AUDJPY is excluded.

- Active offline dataset: `data/pepperstone`, manifest SHA256
  `f6b67d52faa3a0e097ceb9bf64564ce27688278bf3a52b9b92a2b3df2803b081`.
  Per pair: 9341 H4 / 1557 D1, broker dates 2020-01-02 to 2025-12-31.
  Raw originals archived unchanged; UTC conversion uses server = New York + 7h
  with US DST, not Europe DST or a fixed offset. No price resampling/filling.
- One known coverage problem per pair: final server day has five H4 candles,
  ending 16:00, while D1 includes later prices. Missing 20:00 H4 is not filled,
  reconstructed or silently trimmed; warnings remain in metadata/results.
  No pre-2020 warmup added: early 2020 supplies the configured warmup.
- Explicit H4-only stop/target checks and H4-close drawdown marks; no vendor
  M1/H1 or fabricated helpers. Both stop and target inside one candle => stop.
  Whole-bar exits book at bar close so portfolio state cannot see a later
  candle result at its open. Actual intrabar ordering/time is still unknown.
  Trailing/BE OFF as before; enabling either is a separate approximate model.
- Quote-currency conversion uses only the last available closed broker H4
  price; current-candle closes are not visible early. Existing configured costs,
  scope, account benchmark and pair/portfolio limits are unchanged. The raw
  export `<SPREAD>` zeros do not remove the configured trading costs.
- A NEW matching user-run reference is required; old vendor/research/H1-M1 pins
  are incompatible. Dice A/B design remains as below, but both paths must share
  this manifest, H4 checks and bar-close exit timing and pass full-trade parity.
  No automatic carryover of old verdicts. The P95 B timing criterion, separate
  +0.10R money bar and configured benchmarks remain fixed before results.
- User decides the evaluation/holdout window before running. Full 2020-2025
  would inspect 2023-2025, previously reserved as unseen; no holdout split here.
  Partial final-day history, coarse fills/marks and approximate swap timing
  prevent claims of precise broker execution parity.

## Vendor-derived H4/D1 research — pending evaluation design (2026-10-21)

**No actual-history backtest, parity run or dice experiment executed for this
change. Evaluation window / preservation of the unseen years remains a user
decision before running.** This is not a result or a live-parity claim.

- User approved deriving H4/D1 directly from existing M1 for all 11 available
  pairs, 2015-2025. Only the existing 10 selected pairs take part in a batch;
  AUDJPY remains parked. No source prices/periods are filled, no broker history
  is substituted silently, and strategy/cost/risk settings are unchanged.
- Dataset: `data/vendor_derived_2015_2025`, manifest SHA256
  `e2297f26c674cff8346331759c0ed333a2cad8b0274b943f6675b2b4799fd75e`.
  232037 H4+D1 candles; midnight-based grouping of timestamps as stored, source
  timezone unverified. Partial periods are retained and counted, including
  ordinary short sessions/quiet minutes and potentially missing data.
- Reference must be a NEW user-run H4/D1 backtest with explicit research opt-in,
  matching source, config, costs, sizing, limits and pair set. The old H1/H4 pin
  is not a valid reference. The benchmark/$100 baseline and $4-$5.50 risk band
  are unchanged; no parameters were selected from results of these new files.
- Before any dice draws: `--real-only` must reproduce complete per-pair trades
  and pooled totals, not just counts. Both paths use the same configured charts,
  next-open completed-regime mapping, H4 bar duration, M1 checks and pair/portfolio
  limits. At joint portfolio admission, disallowed entries cannot contribute
  later loss/cap state; legacy per-pair candidate suppression remains unchanged.
- A = random timing+direction (placebo, information only). B = random timing
  among regime-bias-on execution bars, following that strategy direction. Only
  entries are replaced; exits/costs/sizing/limits are unchanged. Existing adaptive
  candidate waves / uniform trade thinning and pre-pass trade-count targets stay.
- Existing planned null rule remains: 300 seeds, base 42; B timing evidence only
  if real pooled post-filter mean R is above dice B's 95th percentile. A is not
  verdict material. The separate +0.10R money bar and configured benchmarks stay.
  Do not tune these after inspecting results. Zero-trade/unsupported comparisons
  are refused. This design applies to the current trend core, not every strategy.
- Keep the last ~3 years unseen for new ideas. The full-dataset RUNBOOK command
  would expose them; use separate date-sliced source snapshots/datasets to keep
  a holdout. No split or out-of-sample evaluation has been performed here.

## D1 dice probe — pre-declaration (2026-10-18, written BEFORE any dice run)

Question: do the entry rules beat dice, or does the reference result sit inside dice luck?

- Reference (pinned): `20261019_192501` (post-fix, 2026-10-19) — batch, **no cost flags** (params.json: slippage 0, per-pair spreads+swaps, scope 2.5–3.6, max_total_positions **5**, ccy net 2, weekly halt **5R closed** (R-based, was 15%), M1 checks, cap 20/day). Reference figures: 4509 trades, −577.99 USD, **−0.043R pooled**. The pre-fix pin `20261018_173936_prefix` (2064 trades, −0.013R) is superseded — all D1 dice verdicts against it are provisional until the re-run lands.
- Everything of the system stays (exits, costs, sizing scope, caps, windows, M1 checks); only the entry moment is dice.
- **D1-A** = random bar + random direction (placebo, machinery sanity — never verdict material). **D1-B** = random bar among bias-ON H1 bars, direction = the mapped H4 bias (tests entry timing only).
- Target counts per pair = the **pre-cap, pre-portfolio-pass recorded trade counts of the `--real` parity run** (not funnel `sized`, which counts trades that start and never record the one open at data end).
- Dice draw in waves (first wave ≈ 4× target; each wave re-simulates the pair's full cumulative candidate set from scratch — the open-position rule interleaves), then the recorded trades are thinned **uniformly at random** (never first-in-time) to the target. Then the same daily cap and portfolio pass, in the engine's order.
- Seeds: base 42, one numpy `default_rng` stream per (seed, pair); 300 seeds planned — 3 seeds timed first, fall back to 100 if too slow.
- Verdict metric: **pooled expectancy = mean R per trade over post-cap+pass trades** (same stage as the reference −0.013R). Net USD is information only (dice trades spread through time vs bunched real trades change the drop counts).
- **D1-B verdict (pre-decided): entry timing CONFIRMED iff the real run's pooled expectancy > the 95th percentile of the dice-B distribution. Otherwise: "within dice noise".**
- The §12 money bar (expectancy ≥ +0.10R) stays a SEPARATE condition — beating dice ≠ making money.
- Parity gate: `--real` must reproduce the reference exactly (per-pair trade counts + TOTAL 2064 / −54.84). If it fails, suspect the reference run first (older code) and re-run it with current code before assuming a probe bug.
- **PROVISIONAL (2026-10-19, added after the runs):** every D1 number above ran
  through the broken %-equity weekly halt (see DEVLOG 2026-10-19): once closed
  equity hit 0 (2015-11-16 in the reference), the halt tripped on FIRST-exited
  weeks regardless of direction — 4,430 of 5,134 portfolio drops were
  `weekly_halt`, and the dice trades (spread evenly through time) hit that
  state differently than the real trades do, distorting the comparison in
  both directions. Second flaw same day: the week rolled over on ENTRIES
  only, so early-week exits (Monday-morning closes, or a previous-week entry
  closing in the new week) were booked into the discarded bucket — an
  exit that should halt a week never did; fixed to deal-time booking.
  The engine halt is now R-based (`limits.weekly_loss_r` = 5.0) with
  exit-time week buckets. Re-run needed (user): reference batch + `--real`
  parity + D1-A/D1-B with `--reference <new run>`; the old D1-A/D1-B rows
  above are SUPERSEDED by the re-run row once it lands.

## Errata / corrections

- 2026-10-17: R0 drawdowns above excluded the account baseline (started at the first
  trade's P/L). Corrected figures: EURGBP max DD 2.86 (was shown 0.0), GBPJPY 29.51
  (was 27.43); TOTAL unchanged. Per-pair DD% are NOT additive — one shared 100 USD
  account; DD bands grade the TOTAL row only (engine v0.9.3).
- 2026-10-17: R0 entry ATR sat in a ~15.3–20 pip band by construction: the then-hidden
  `max_cost_ratio 0.10` gate banned stops under ~10x cost (ATR < ~15.3 pips) and the
  USD3 cap-distance gate banned stops over ~30 pips (ATR > ~20). Now both are named
  funnel gates. Spread calibration landed same day (Friday-close per-pair sample from
  `quant.spreadcheck`, written into pair yamls as `costs:` overrides; re-sample in
  live sessions Monday — demo spreads move intraday).

## Ladder notes (decisions log)

| # | Change | Purpose |
|---|---|---|
| R1 | bias-only probe (new, no trades): onset/state/null, edge vs cost in ATR units | does the bias alone predict anything? If not, no entry will fix it |
| R2 | gates HR2/HR3/HR4/guard/EXT off → E1-setup + E1-trigger only; trail off; cap 5→20 | **new simple baseline — 3 changes at once, an improvement claim: none** |
| R3+ | one change per run: e.g. bias-flip exit, or wider trail / no fixed TP | enter/exit refinement only if R1 confirms and R2 beats R0 |

R0 old settings to restore if ever needed: `use_hr2/3/4: true, hl_guard: true, use_ext: true, use_trail: true, max_trades_per_day: 5`.

## Ledger

| Date | Run | Conditions ON | Trades | Net USD | Net R | Max DD % | PF | Bars (avg/med) | Tier | Takeaway |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-18 | D1-A dice probe (placebo, info-only) `dice_results\20261018_210348` (design pre-declared in the D1 section above; same reference + parity gate) | reference system exactly; entries = **random bar + random direction** (no bias signal at all); exits/costs/caps/filter order identical; per-pair targets = parity pre-pass counts; 300 seeds, base 42 | ≈1.4–4.3k/seed post-pass | dice mean −259.6 (real −54.84, info only) | real −0.013R vs dice mean −0.0513R | — | — | — | info only | placebo ≈ bias-timed dice (A mean −0.0513R vs B −0.0453R, Δ 0.006R) → the H4 bias direction adds almost nothing on top of entry timing — R1b's finding confirmed through the full trade machinery; real = P92.0 vs A (P95 −0.0088R missed); 6/300 positive |
| 2026-10-18 | D1-B dice probe `dice_results\20261018_210825` (merged with fragments `20261018_192432` + `20261018_193236`; design pre-declared in the D1 section above; reference `20261018_173936`, parity re-passed per invocation) | reference system exactly (no cost flags, slip 0, per-pair swaps, scope 2.5–3.6, 5 open, ccy 2, halt 15%, M1); entries = random **bias-ON** H1 bars with the mapped H4 direction; exits/costs/caps/filter order identical; per-pair targets = parity pre-pass counts (7198); 300 seeds, base 42 | ≈1.4–4.3k/seed post-pass | dice mean −248.8 (real −54.84, info only) | real −0.013R vs dice mean −0.045R | — | dice PF ≈ 0.96 | — | **WITHIN DICE NOISE** | real expectancy = P90.3 of 300 blind-timing seeds; pre-declared P95 bar (−0.008R) missed by ~0.005R; only 6/300 dice seeds positive and dice mean −0.045R vs real −0.013R → the entry timing selects better-than-dice spots among bias-ON bars, but does NOT clear the pre-declared bar; §12 money bar (≥ +0.10R) separately NOT MET — beating dice was never the money test; verdict metric = pooled post-cap+pass mean R per trade |
| 2026-10-17 | R1b probe `edge_probe_R1b_20261017.csv` | same probe, honest per-pair costs (spreadcheck Fri close: 0.2–2.2 pips/pair; pooled cost line 0.085 ATR; commission 0 = Razor TBD) | — | — | — | — | — | — | **NOT CONFIRMED** | cost halved (0.164 → 0.085 ATR) yet raw onset drift unchanged (+0.030 / −0.027) — the gap is the missing signal, not the costs; random-direction bars still beat bias-onset bars (+0.10 / +0.14). Bias redesign required before any entry work. |
| 2026-10-17 | R0 `20261017_153137` | all gates + trail, cap 5, M1 checks, windows | 282 | −98.36 | −40.91 | 110.9 | 0.737 | 9.6 / 7.5 | **FAIL** | current simple-ish baseline loses after costs on 10 pairs; DD > 100% of the 100 USD account |
| 2026-10-17 | R1 probe `—` | bias-only, pooled onset 48+72, cost line 0.164 ATR (avg over 10 pairs) | — | — | — | — | — | — | **NOT CONFIRMED** | pooled onset move ≈ zero (+0.030 / −0.027 ATR at 48/72) — it does not even cover the cost line (0.164 ATR), edge = −0.13 / −0.19 ATR; random-direction null did about the same or better (+0.10 / +0.14) so the bias direction adds nothing; 9/10 pairs at ≈ 0 or negative (best: GBPJPY +0.25 @48). **Ladder rule: R2 paused until the bias itself is rethought — no entry can fix a flat bias.** |
| 2026-10-17 | R2 backtest `20261017_191201` (deterministic re-run; replaces deleted `20261017_183837`, identical figures) | E1-setup + E1-trigger only, no trail, cap 20/day — **honest per-pair live costs** (spreadcheck Fri close), **sizing scope 2.5–3.6 USD** (no fixed lot), corrected DD baseline | 7274 | −1379.19 | −449.29 | 1479.8 (MTM) | 0.921 | 16.2 / 9.0 | **FAIL** | baseline capture per plan, verdict as measured: −0.062R/trade × 7274 trades destroys the account; win rate 24.6% sits below the 25% zero-cost breakeven of a 1:3 target — a textbook no-edge signature; 7/10 pairs negative (best GBPJPY +0.115R, PF 1.171 — still under the PF band) agrees with R1b: the H4-bias 1H-entry family shows no positive drift at honest costs; scope holes ate 144–467 triggers on JPY pairs (funnel `scope`), windows/1-day/open skips the rest. Report re-rendered: 53 MB, all 7274 windows embedded (chart cap removed — its pair-order slicing starved 8/10 pairs). |

### R1 pooled detail (probe run 2026-10-17, seed 42, `--batch`)

| Set | k=24 move | k=48 move | k=72 move | note |
|---|---|---|---|---|
| onset (flip bars, n≈6200) | −0.039 | **+0.030** | **−0.027** | verdict set; edge incl. cost −0.13 / −0.19 ATR, 2-SE bands exclude 0 |
| state (all bias-on bars, n≈477k) | −0.028 | −0.068 | −0.117 | where R2 enters; slightly negative BEFORE costs |
| null (random bars × random direction) | +0.044 | +0.101 | +0.135 | machinery sanity: bias onsets fail to beat even random bars |
