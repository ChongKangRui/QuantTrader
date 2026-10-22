# Dev Log (newest first)

## TODO (living checklist — strike the line when done; finished work goes into the dated log below)

### Now (housekeeping, no backtest needed)

- [x] ~~Sizing decision~~ (2026-10-21): keep fixed-dollar scope and balance
  scaling OFF. User manually adjusts USD scope/base lot as the account grows.
  $200 is under consideration, not confirmed: benchmark remains $100.
- [x] ~~Pair-frequency protections~~ (2026-10-21): configurable max 2 actual
  entries/pair/week and pair-day block after a fully closed net loss, enabled
  in active `_base.yaml` and the H4/D1 preset; terminal validation pending.
- [x] ~~History export tooling~~ (2026-10-21): existing `mkdata --broker` follows
  configured chart/check timeframes and includes H1 + USD conversion feeds,
  warmup, validation and metadata. API pulls stalled; manual chart exports now imported below.
- [x] ~~Vendor-derived research dataset~~ (user-approved alternative): all 11
  existing M1 pairs converted directly to H4/D1 in
  `data/vendor_derived_2015_2025/`, 232037 derived candles. Source files unchanged;
  source timezone is unverified; partial periods retained, empty periods omitted.
  Normal broker/live data contract unchanged; research requires explicit CLI opt-in.
- [x] ~~Configured dice tooling~~: shared H1/H4 or H4/D1 frames, A/B entry modes,
  shared exits/costs/sizing/limits, source/config and full-trade parity gates.
  Synthetic H4/D1 real-path parity passed; no actual-history parity/dice run yet.
- [x] ~~User's Pepperstone MT5 chart exports organized~~: all 10 enabled pairs
  have H4+D1 in `data/pepperstone/`; 20 originals preserved under `raw/`.
  UTC-normalized actual broker candles, 2020-2025; no H1/M1/vendor mixing.
  `backtest_data` in active YAML now selects this offline default with H4 checks.
- [x] ~~User-run H4/D1 broker baseline~~: `20261021_202430` exists; user reports
  poor results. Source/config and all enabled-pair coverage match current setup
  (read-only validation; no actual-history parity run by the agent).
- [x] ~~Entry-reason diagnostics~~: future trades record wick-touch/cross-candle
  reasons from the signal candle. Latest report rebuilt without a backtest:
  all 786 existing trades classified from verified saved config/source; original
  trades, totals and params unchanged. Pattern summary/filter and CSV available.
- [x] ~~Malaysia entry window and lot display~~: configurable new entries only,
  09:15 inclusive–23:00 exclusive UTC+8; lots and UTC/Malaysia times in report.
- [ ] DICE REMINDER — entry-hours rule changes the baseline. User must first
  produce a NEW reference with current config; `20261021_202430` has no hours
  filter and is no longer compatible with the active setup. Then run
  `quant.dice_probe --real-only --reference backtest_results/<NEW_RUN>`.
  Only after full trade parity PASSES, proceed to the pre-declared B comparison.
  No parity/random experiment run yet. Keep the reference/config fixed; choosing
  a pattern to disable is a new idea and requires separate validation.
  Full-range results have been inspected; 2023-2025 cannot now be called unseen
  for ideas chosen from these reports. Risk/cost/account settings unchanged.
- [ ] Widened-stop mode (code done 2026-10-20, ships OFF): `risk.stop_sizing`
  trades a FIXED lot and widens the stop (and the target) until that lot
  reaches `sizing_scope_usd.low`, instead of trading more lots. Next: write
  the TESTLOG pre-declaration, then run the batch with `--widen-stop` and
  compare against the same run without it (one change per run).
- [x] ~~Optional lot increase when stop widening hits its cap~~ — implemented under
  `risk.stop_sizing.increase_lots_if_widening_fails` (default OFF).
- [] Add an entry logic of when cross from trend to opposite direction between EMA 20 and EMA 100
- [] Can we have a way to detect flat market? flat market make me lose a lot, literally just keep losing for flat, consolidation market where ranging just happen like crazy

### Verdict track (timebox: 2-3 more experiments, then decide)

- [ ] Write the variance-ratio / Hurst script (spec §11.3). Never done.
- [ ] Run both, record results in `docs/TESTLOG.md` (user runs them). Variance-ratio
  remains unbuilt. For current broker H4/D1, use the matching user-run pin,
  real-only parity then B comparison. `20261019_192501` is legacy H1/H4 only.
- [ ] Decide from the results:
  - real result inside the random cloud AND variance ratio ≈ 1 → no edge from these entry rules / no trend to harvest on these pairs at H1/H4 → change market, timeframe or edge type — or stop.
  - real result clearly above the cloud, or gross > 0 but costs kill it → structural (spread/swap is a big share of 15-20 pip stops) → wider stops via a longer timeframe, or a cent account.
- Standing rules:
  - each hypothesis → `docs/TESTLOG.md` BEFORE running, one change per run
  - keep the last ~3 years unseen for any new idea
  - do NOT drop or keep pairs based on this run (about 200 trades per pair; the best/worst pairs are within noise)
  - stopping is a valid result; the tooling/engine/ledger/report are reusable; keep it demo-only

### Parked until the verdict is in

- [ ] Percentage-based sizing scope (future, not built): user envisages a
  configurable band such as 2%-3% instead of a fixed USD band, with dynamic
  lots. No automatic balance threshold or percentage-band implementation now.
  The old 1/3/5% lot-scale sweep is deferred. Existing balance scaling still
  checks a fixed USD band; it does NOT implement percentage bounds.
- [ ] Go-live demo smoke: 0.01 lots EURUSD + one JPY pair → all 10; compare fills vs backtest. Rotate the demo password (it appeared in chat).



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
