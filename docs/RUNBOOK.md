# Runbook — commands you can run manually (PowerShell, from repo root)

## Local performance records (no database)

The monitor now writes `trades/accounts/<demo|real>_<login>_<identity hash>/`.
`account.json` is the authoritative local file: raw confirmed broker deals,
open positions, equity/balance snapshots, and write-ahead entry intents. JSON is
atomically replaced and flushed before an entry is sent. Keep this folder backed
up privately. It contains account identifiers, but no credentials. `trades/` is
git-ignored. The existing journal and demo/real CSVs remain legacy convenience
exports; the account-separated raw deals are authoritative for fills/partial closes.
Use one workspace writer only; the monitor and one-shot actual-order executor
share the existing process lock.

Normal monitoring (without `--trade`) sends no orders and collects performance:

```powershell
$env:PYTHONPATH="python"
uv run python -m quant.monitor --account demo
```

`deals.csv`, `equity.csv`, `performance.json`, and `performance.html` are exports
beside `account.json`. The broker history query initially covers the last 365 days;
stored deals are retained across subsequent windows. This is not proof of full
account-inception coverage. A missed/older ticket is merged by identity, not
discarded by a highest-ticket watermark. Dry-run plans are never confirmed fills.
Actual sends require durable recording even with `--no-record-performance`;
that flag only opts out of collection in a read-only/dry-run monitor session.

To rebuild a saved account report **offline**, without connecting to MT5:

```powershell
$env:PYTHONPATH="python"
uv run python -m quant.account_store --account-dir "trades/accounts/<account-folder>" --magic 100001
```

The report shows whole-account ratios and separate whole-account/strategy deal
totals, in the account's native currency (no assumed USD conversion).
Strategy-specific ratios are not inferred from whole-account equity.
Charges without a strategy magic remain in whole-account results, not silently
allocated to a strategy. All `profit`, `commission`, `swap`, and `fee` deal fields
are included, including separate broker charge transactions. Spread/slippage
are already in fills and must not be subtracted again. Broker equity is already
net of booked costs. Balance and credit movements are treated as external capital.
Cash-flow-adjusted ratios use an explicitly labelled Modified Dietz estimate;
exact return measurement would require valuations at every external cash flow.
Broker deal milliseconds are preserved for cash flows; old records without them
fall back to seconds. Collection reads account state before and after querying
history. If balance/credit or account identity changes during collection, the
snapshot is skipped and new entries wait for a consistent later poll.

Optional shared settings in the selected base YAML (defaults below; rates are
annual decimals, so `0.04` means 4%). No active config is changed automatically:

```yaml
performance:
  enabled: true
  risk_free_rate: 0.0
  minimum_return: 0.0
  periods_per_year: 252.0
  minimum_observations: 20
```

`enabled: false` disables ratios, not mandatory order auditing. Offline account
report overrides: `--risk-free-rate`, `--minimum-return`, `--periods-per-year`,
`--minimum-observations`. Backtests snapshot these settings in `params.json`.
Sharpe uses sample volatility; Sortino uses downside deviation across **all**
daily observations. Calmar uses calendar annualized growth / daily-close maximum
percentage drawdown over the shown period. Daily-close drawdown is not the
intrabar maximum drawdown used elsewhere. Sharpe bands do not rate Sortino/Calmar.

New backtest curves accrue entry commission, short ask-spread valuation, and
overnight swap events before closing; final exit P/L already includes the full
costs, so these temporary accruals are not deducted again. Comparison groups
separate this equity-cost timing from older price-only marks. New summaries also
show round-trip commission charged. Marks remain approximate bar-close values.
Old/incomplete runs show N/A rather than pretending their price-only curves are
cost-timed net equity. No historical account equity is reconstructed from deals.
Missing weekday snapshots, insufficient history, zero equity, zero volatility,
no downside, or no drawdown can make the corresponding ratios N/A. Keep the
monitor collecting; it cannot observe equity while offline.

An unresolved send, missing broker history, corrupt account file, or failed local
write blocks new entries; existing-position management is still attempted.
Broker-reported deal/order IDs resolve known responses on subsequent polls.
If a crash loses the response itself, automatic attribution is deliberately NOT
guessed: verify the broker history and request a supervised recovery. Do not
delete pending records or blindly resend. Legacy crossover pending guards can
also continue to require operator verification. No live-terminal verification
or financial-performance guarantee is implied by mocked tests.
Known local refusals are now recorded as `not_sent`. These and definite broker
rejections can retry on the same signal bar, retaining previous attempts inside
the entry's `attempts` list. Confirmed fills and uncertain sends cannot reuse the
entry key. Old uncertain records are not automatically reclassified as unsent.
For the one-shot roundtrip executor, exit code 3 means it closed the position but
could not finish its journal; check broker history/local sync. A journal failure
does not prevent that roundtrip's close attempt. The separate `touch_close` path
still has journal writes before its wait/timeout management; that similar issue
was not changed in this fix.

New backtest folders include bias first, execution second:
`YYYYMMDD_HHMMSS_H4_H1` for H4 bias/H1 entries, or
`YYYYMMDD_HHMMSS_D_H4` for Daily bias/H4 entries, or
`YYYYMMDD_HHMMSS_D_H1` for Daily bias/H1 entries. The suffix is automatic from
the run's resolved config; existing folders and dice folder names are unchanged.
After a successful run, the final portfolio profit factor is appended to two
decimal places, e.g. `YYYYMMDD_HHMMSS_D_H4_PF1.25`. `PFinf` means no gross losses;
`PFNA` means no trades. Failed/partial runs keep their original name. If the
rename fails or the destination exists, a warning is printed and the original
folder is kept. Reports, comparisons and the ledger use the final folder name;
the best-run ranking rule is unchanged.

Terminal must be open and logged in for anything that reads MT5.
Monitor and smoke send no orders.

## Daily bias with H1 execution

This combination is now supported by backtest, report, dice and live/panel chart
selection. To select it in the active `configs/_base.yaml`:

```yaml
timeframes:
  execution: H1
  regime: D1
```

Keep `backtest_data.use_broker_csv: true` and `backtest_data.position_checks: H1`
for the imported Pepperstone charts. Actual H1/D1 exports are loaded, never
resampled. Daily bias uses only a candle known closed at the H1 signal close;
entries fill at the next H1 open. Stops/targets, ATR, recovery expiry and marks
remain on H1. Broker H1-only intrabar limitations and configured costs still apply.
Legacy source mode also needs an actual Daily export beside H1; no synthetic
Daily fallback. Existing H1/H4 and H4/D1 combinations remain supported.

Support was added without changing active config values, running a backtest,
or launching trading. Changing the shared config also affects the next trader
launch. A different timeframe is a separate experiment; no improvement is claimed.
The older `edge_probe` remains H1/H4-only; it was not adapted by this change.

## Remembered-pullback entry and broker H1 addition (2026-10-22)

New mode ships OFF: in `configs/_base.yaml -> strategy.entry`, set
`use_recovery_entry: true` to test it; `recovery_expiry_bars: 4` is editable and
`recovery_cancel_beyond_slow: true/false` controls cancellation on a close beyond
the slow entry EMA. Rules and consumption/refresh details: `configs/README.md`.
Other entry patterns cannot bypass this separate mode. No financial improvement
or live-terminal parity is claimed. Pre-declare the experiment before a user-run
backtest; keep exits, sizing and costs fixed for the first entry-rule comparison.

All ten enabled pairs' tagged Pepperstone H1 exports have now been imported with:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --import-pepperstone --add-h1 --batch --src data --out-dir data/pepperstone
```

This was a data import, NOT a backtest. Do not rerun into the same extension:
overwrites are refused. Raw bytes are archived in `data/pepperstone/raw/`, with
UTC `<SYM>_H1.csv` and metadata beside existing H4/D1 files. `manifest_h1.json`
pins the extension to the unchanged original `manifest.json`; old H4 source
identities remain valid. Vendor H1/M1 files were not replaced.

Per pair: 37346 H1 candles (NZDUSD/USDCHF: 37345), server timestamps 2020-01-02
00:00 through 2025-12-31 19:00. H1 OHLC matches every existing H4 candle exactly.
There are 13 H4 periods with fewer than four H1 candles per pair (14 for
NZDUSD/USDCHF). Short sessions versus missing hours are not certified; warnings
are retained. No hours or prices are filled and no history is trimmed.

Active `_base.yaml` now selects `backtest_data.position_checks: H1` for every
pair, including H4 entries / D1 bias. H1 checks and closed H1 converters require
the verified extension; missing feeds or execution intervals with no H1 rows
fail without coarse/vendor fallback. Stops/targets/BE/trailing use H1 candles;
trailing updates apply only after the hour closes. Partial sessions remain
warned, not filled. Equity marks still follow the execution tape (H4 here).
Old H4-only baselines are incompatible; obtain a new matching reference before
dice. No live management timing is changed.

The broker exporter now also honours the effective broker `position_checks`
setting, rather than requesting legacy M1 alongside H1/H4/D1. Preview/export
still requires a separate request; no terminal history has been collected here.

To select broker H1 entries, change only `timeframes.execution: H1` and
`timeframes.regime: H4` in the active config. With `use_broker_csv: true`, the
engine loads actual broker H1/H4, not a resampled H4 or vendor helper. H1 mode
uses explicit H1 stop/target checks, H1 closed-price converters and H1-close
drawdown marks. Both-stop-and-target candles still count as stops and exits book
at candle end; intrabar order is not known. No broker M1 has been added.
Changing timeframe is a separate experiment from changing the entry rule.

The older H1 preset retains its old strategy/risk values, including EMA20/50 on
the entry chart; copying it is not a one-change comparison with the active config.
Dice needs a matching NEW user-run baseline and full-trade parity before draws.
No backtest, actual-history parity/dice run, report rebuild or live order was
executed for this change.

## Original offline dataset: user's Pepperstone MT5 H4/D1 exports

`configs/_base.yaml -> backtest_data` now selects `data/pepperstone` for offline
backtests and dice. All **10 enabled pairs** have both charts. AUDJPY is parked
and was not requested/imported. Live fetching and trading flags are unchanged.

```text
data/pepperstone/
  raw/                 original 20 MT5 tab-separated exports, unchanged bytes
  <SYM>_H4.csv         standardized UTC four-hour candles
  <SYM>_D1.csv         standardized UTC daily candles
  <SYM>_<TF>.meta.json source identity, checksums, server/UTC endpoints
  manifest.json        full dataset identity and coverage warnings
```

The tagged originals were moved from the cluttered `data/` root into `raw/`
after validating archived checksums. Original vendor H1/M1, source folders and
the vendor-derived research dataset were not moved, renamed or changed.
The importer command was run, not a backtest:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --import-pepperstone --batch --src data --out-dir data/pepperstone
```

Do not rerun into the existing folder: overwrites are refused. A corrected export
requires a fresh destination/review; retain the old dataset identity for old runs.

**Coverage:** raw chart dates are 2020-01-02 through 2025-12-31, per pair 9341 H4
and 1557 D1 candles. All full server days' H4 OHLC matches the supplied D1 except
the final day. Every H4 export ends at **2025-12-31 16:00 server time**; the
20:00 candle is missing while D1 includes later prices. This is recorded and
shown as a warning; nothing is filled or silently trimmed. If the complete last
day matters, re-export that final H4 candle. Pre-2020 history is not present:
normal indicator warmup uses initial 2020 bars; earlier charts would be needed
to start evaluating trades from the very beginning of 2020.

**Time:** MT5 UI exports use broker server time, not UTC. Intake uses Pepperstone's
documented GMT+2 winter / GMT+3 **US** daylight saving schedule (server clock =
America/New_York + 7 hours), then converts timestamps to UTC without changing
OHLC or resampling. It does not use Europe's DST calendar or a fixed offset.
Reference: <https://pepperstone.com/en/about-us/trading-hours>.

**Original coarse execution (before the H1 addition above):** offline checks explicitly
use H4, not a silent fallback or mixed vendor feed. Both stop and target hit in
one candle => stop first. Coarse exits are booked at bar end, not prematurely at
bar open; their actual intrabar timestamp remains unknown. Trailing/breakeven
are approximate if enabled (both currently OFF). Currency conversion uses the
last broker H4 close only once the next candle opens. Drawdown marks use H4
closes at their availability time, not invented hourly/minute observations.
Existing configurable spread, commission, slippage and swaps remain charged;
the raw export's zero `<SPREAD>` values do not turn costs off. Swap rollover
timing remains the engine's existing approximation, not a newly exact model.

User-run command when ready (NOT run by the agent):

```powershell
run-backtest.bat
```

or `$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch`.
Both now follow the broker dataset config. `--broker-data-dir` overrides the
dataset folder; `use_broker_csv: false` disables this default and restores legacy
input selection. An explicit `--research-data-dir` instead selects the separate
research path. Missing enabled broker pairs, damaged checksums and wrong-source
inputs fail rather than silently skipping pairs or mixing sources.

Reports display the H4-coarse and coverage warnings and exact H4/D1 charts, with
no fabricated H1 view. Run params save source identity, manifest hash, H4 check
resolution and bar-close exit timing. Dice requires a NEW matching reference:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.dice_probe --real-only --reference backtest_results/<RUN_ID>
```

Only after parity and the pre-declared design are accepted, the user may run
`--variant B --seeds 300` against that same reference. Research/H1-M1 pins do not
match this source/resolution. Full 2020-2025 results would expose reserved
2023-2025 holdout years; decide evaluation/holdout treatment before running.

## Entry reasons and dice readiness

### Malaysia entry hours (2026-10-21 update)

`limits.entry_hours` in `_base.yaml` / `_base_h4d1.yaml` controls NEW strategy
entries: `enabled: true`, `utc_offset_hours: 8`, `start: "09:15"`, `end: "23:00"`.
Start is inclusive, end exclusive; `enabled: false` removes this guard.
The offset is fixed (Malaysia has no DST), not the broker's seasonal offset.
Times remain UTC internally; check live order-decision time / offline next-bar
fill time in the configured local clock. Overnight windows are supported.
Existing positions stay managed outside the window. Skipped signals are not
queued. H4 entries still use broker candle boundaries, not arbitrary 09:15 fills.
Manual order-testing utilities are outside this strategy-entry guard.

The report displays Lots and explicitly labeled UTC and Malaysia entry times.
Rebuilding an old report changes presentation only; it does NOT apply this new
entry rule to old trades. **Dice now needs a NEW user-run baseline** with these
settings; `20261021_202430` is unfiltered and no longer matches active config.
After that baseline, run `--real-only --reference backtest_results/<NEW_RUN>`;
only after PASS may the pre-declared random comparison run.

New trade CSVs record `entry_reason` and `signal_bar_time` from the **signal
candle**, not the subsequent fill candle. Modern W1 labels are Wick touch and
Cross candle; disabled/legacy rules and random A/B entries have distinct labels.
This is diagnostic metadata only, not a new strategy parameter or entry rule.

Reports show an entry-reason column/filter and all-pair results by reason. Each
report rebuild writes `entry_summary.csv` with combined and per-pair trade counts,
wins/losses/scratches, win rate, net USD, negative-USD sum and average USD/R.
All figures use accepted closed trades after costs/portfolio filters. A zero-net
trade counts in the win-rate denominator but is neither a win nor loss.

Rebuild an existing report **without rerunning a backtest**:

Chart popups have Previous/Next trade buttons and Left/Right arrow shortcuts.
Navigation follows the visible table's pair, outcome, exit and entry-reason
filters, with a Trade N of M counter and no wrap at the ends. Timeframe choice
is retained when available. Missing charts show a notice without trapping
navigation; changing filters updates an open popup, including empty selections.
Keep the report page open while using its popup. Existing reports need rebuilding;
new backtest reports include navigation automatically. Only the latest saved
`20261022_205535/report.html` was rebuilt for this change; all its original
non-HTML artifacts were verified byte-for-byte unchanged.

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.report --run backtest_results/20261021_202430
```

Historical reasons are reconstructed only when saved modern strategy settings,
source identity/checksums, signal-to-fill alignment and recorded ATR agree.
Otherwise they display Unknown. Hover a reason to see recorded/reconstructed
status. Rebuilding does not change original trades, totals or parameters.
The latest report above has already been rebuilt for all 786 trades.

**Historical dice command (before entry hours were enabled):** the old baseline
passed read-only checks then, but no longer matches the active configuration.
Replace the reference below with a new session-filtered run before using it:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.dice_probe --real-only --reference backtest_results/20261021_202430
```

This gate has **not** been run by the agent. Only after it PASSES can the
pre-declared random B comparison proceed. Added diagnostic columns alone do not
invalidate an older reference; original financial/trading columns still must
match exactly within existing numeric tolerance. Do not disable a pattern just
because its inspected sample looks worse: that is a new hypothesis, not proof.

The year-end missing candle is an accepted source limitation, not a pending
repair request. Audit metadata stays intact. The holiday window blocks new
entries but does not force existing trades closed; its rules were not changed.

## Trading supervisor (the trading switch)

```powershell
start-trader-demo.bat
```

Launches the panel WITH the trading loop and **demo orders ON**. The generic
`start-trader.bat` has been removed. `start-trader-real.bat` instead selects
**real-money orders ON** and displays a warning. Only the user launches these;
the agent has not run either launcher or tested actual broker execution.

- `--account demo/real` narrows to the requested enabled account, even when both
  enable flags are true. No enable flag is changed. A disabled selected account
  is refused; the other account's credentials are not loaded as a fallback.
- The selected login, server and actual broker account type must match before
  polling/trading and are checked again before entry/SL-modification requests.
  A real account cannot be traded through the demo launcher, nor vice versa.
- Separate journals: `trades/demo_journal.csv` and `trades/real_journal.csv`.
  Existing per-account restart memory and weekly state remain in use. Original
  shared journal/history files are not deleted or migrated. If already running
  managed positions, review their saved context before changing launchers.
- One panel/trader per workspace: a nonblocking OS lock at `memory/monitor.lock`
  prevents accidentally launching two supervisors. Stop the old panel/trader
  before switching. The lock file may remain after exit; the OS lock is released,
  including after process termination. Do not delete it while a process runs.
- Do not run another program/workspace against the same terminal or manually
  switch its account while trading. Account rechecks cannot make an external
  account switch atomic with an MT5 order request.
- `start-panel.bat` remains read-only. Direct CLI and the global config still
  default to dry-run. To override a launcher safely: `start-trader-demo.bat --dry-run`
  (or `start-trader-real.bat --dry-run`). Launchers fix account/journal after
  forwarded arguments, so a demo launcher cannot be redirected to real by flags.

MT5 must be running/logged in with Algo Trading enabled. Closing the trader stops
new entries and Python-managed adjustments, not existing broker-held SL/TP.
Verify demo fills, attached stops/targets and restart recovery before considering
real money; unit tests and launchers do not establish profitability or terminal
readiness. No strategy, sizing, costs or USE_REAL settings changed here.

## Live broker costs (read-only, no orders)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.spreadcheck
```

Prints each enabled symbol's live spread and swaps from the terminal.
Sample it at different hours — demos spread out massively in dead sessions,
and the backtest cost model needs calibrated numbers.

Numbers land in each pair yaml as a `costs:` override (spread + swaps; sample
date and session are noted in each pair file). CLI sweep flags (`--spread-points`,
`--flat-swaps`, ...) beat pair yaml values, so sensitivity sweeps stay global.
Zero spreads in the output mean the market is closed or the quote is stale.

## Edge probe (R1 — bias-only measurement, no trades)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.edge_probe --batch
```

Reads the same H1/H4 data as the backtest. Verdict line lives by the
pre-decided rule in `docs/TESTLOG.md`; per-pair rows are information only.

## Broker history export (read-only, no orders)

### Prepared 2019 / 2020-2025 evaluation (not run)

- New offline union: `data/pepperstone_prepared_2019_2025_20261024/`.
  All 17 known pairs have 2019 preparation H1/H4/D1. Sixteen also have broker
  evaluation history; parked AUDJPY has only 2019 and is not enabled. Do not
  substitute vendor data to enable it. Original datasets remain unchanged.
- Isolated frozen config directory:
  `data/four_pair_evaluation_20261024/configs/`. Only EURAUD, GBPCAD, AUDCAD,
  CADJPY are selected. EURNZD/GBPCHF are reserved; active configs are untouched.
- Dedicated Windows launcher: `run-backtest-unseen.bat`. It uses that isolated
  selection and `backtest_results/four_pair_evaluation_20261024/`, refuses missing
  profile files, and accepts no overrides. Leave `configs/scan-selection.yml`
  unchanged. Launching it runs the evaluation; adding it did not run a backtest.
- `evaluation_plan.json` in that setup records strategy/cost/source/config/code
  hashes, input-only readiness, dates and the fixed primary decision rules.
  Current/recent demo costs are assumptions, not historical financing evidence.
- After a SEPARATE user backtest request, the prepared command is:

  ```powershell
  $env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --config-dir data/four_pair_evaluation_20261024/configs --results-dir backtest_results/four_pair_evaluation_20261024
  ```

  This command is documented, NOT executed. Read `docs/TESTLOG.md` first. The
  engine's benchmark label alone does not enforce the experiment's minimum 100
  pooled trades / one trade in every pair; apply the declared INSUFFICIENT rule
  before interpreting a PASS. Full strategy validation requires further approved
  robustness/cost-stress/null experiments, not automatic follow-up runs.

To reproduce data assembly only (fresh output directory required; no simulation):

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --bundle-broker data/pepperstone data/pepperstone_unseen_fx_2020_2025_export_20261024 data/pepperstone_all17_2019_export_20261024 --out-dir data/pepperstone_prepared_review
```

The normal exporter now automatically converts verified Pepperstone API clock
labels to actual UTC, including query dates and warmup. An explicit
`--broker-clock utc` / `--broker-clock new_york_plus_7` overrides detection;
`backtest_data.broker_api_clock` can set the same policy in a base config. CSV
metadata records the chosen clock and original query labels. This does not
normalize live APIs or old files again; never double-convert normalized inputs.

### Normal history export

The exporter follows `_base.yaml`'s execution, regime and position-check
timeframes. It also exports H1 for the current backtest's price/report inputs
and required USD conversion feeds. It exports broker candles, never resamples.
It supports standard MT5 timeframes independently of the engine, which still
accepts only H1/H4 and H4/D1 strategy combinations.

First agree the pairs/date range. Example **only**, for calendar year 2025:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --broker --batch --start 2025-01-01 --end 2026-01-01 --out-dir data/broker_review --plan
```

`--plan` connects to nothing and writes nothing. `--batch` uses selected config
pairs; replace it with `--symbol EURUSD` for one pair. Dates without offsets
mean UTC, and `--end` is exclusive. The example dates are not an approved test
window. Actual export, after confirmation, uses the same command without `--plan`:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --broker --batch --start 2025-01-01 --end 2026-01-01 --out-dir data/broker_review
```

Open and log in to the intended MT5 terminal first. Export uses that terminal's
current account/server; it does not load account credentials or switch accounts.
No orders or trading flags are touched. CSVs and matching `<SYM>_<TF>.meta.json`
sidecars record server, symbol, UTC timestamps, export date, requested/actual
coverage, warmup and gap statistics. Account login/password are not recorded.

- Broker-retained history and terminal **Max. bars in chart** can limit available
  data. Load more history or choose a later start when coverage/warmup fails.
  The default warmup is the maximum configured warmup/known indicator period;
  `--warmup-bars N` overrides it (0 explicitly disables it). Extra prefix bars
  are included in **every** feed, including M1 and converters. The last prefix
  candle is not counted as closed without a following broker open.
- Missing M1 coverage stops export rather than silently using H4 stop checks.
  Raw `None`, invalid prices/volumes, duplicates and descending timestamps fail.
  Gaps/empty chunks and leading/trailing coverage are reported, never filled.
  Gaps include normal weekends/holidays/session/DST changes; the exporter does
  **not** certify that a reported gap is harmless or that broker history is complete.
- Queries stream in bounded `--chunk-days` chunks (default 31). Only bars no
  newer than the broker's last closed candle at collection are retained.
- Existing output files are refused by default. Use a fresh review folder.
  `--overwrite` explicitly replaces matching CSVs/sidecars; do not use it on
  `data/` without deciding whether to replace existing vendor histories.
  All feeds are staged/validated before publication; a collection failure
  leaves existing CSVs alone. Publication is per-file, not a multi-file filesystem
  transaction: a disk/rename failure during publication can leave a partial set.

**Before backtesting:** review coverage/source consistency and the extra warmup
prefix. The existing backtester does not use metadata to enforce a separate
trade-start date. Its batch input paths still point at `data/`; a review folder
is not automatically selected. Promoting/replacing files needs an explicit
decision. Do not combine new broker H4/D1 with old vendor H1/M1 or conversion
feeds without addressing their timezone/source differences.

The original vendor workflow (`mkdata --symbol ... [--m1-csv]`) is unchanged.

## Vendor-derived H4/D1 research dataset (explicit alternative, not broker candles)

User-approved research alternative, 2026-10-21. Built directly from existing M1
for all 11 available pairs, including parked AUDJPY; trading selection stays
unchanged (10 enabled). It preserves the source timestamps as stored and groups
at 00:00/04:00/etc. The source timezone is **unverified**: UTC labels are not
proof that these candles match the broker clock. Signals, swaps and fills can
differ from live trading. This is exploratory tooling, not live validation.

Dataset: `data/vendor_derived_2015_2025/` (local-only). Build command, already run:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --research --all-existing --src data --out-dir data/vendor_derived_2015_2025
```

The builder streams consolidated M1 CSVs, not H1. It writes H4/D1 CSVs with
`n_minutes`, per-file coverage/source sidecars, and `manifest.json`. Empty periods
are omitted, never filled; partial periods use observed OHLC only and are retained
and counted. A partial period is not automatically corrupt: weekends, short
sessions and quiet minutes also produce them. The first observed price stands
in for that candle's open; this is an approximate fill model when early minutes
are absent. Reports do not establish that every source gap is harmless.
`--symbol` builds one pair; `--research-timeframes` accepts fixed-duration MT5
names; `--chunk-rows` bounds memory. Existing outputs are refused without explicit
`--overwrite`; sources must remain unchanged. This creates no synthetic pre-2015
warmup; the engine consumes its normal warmup from the beginning of the files.

Backtesting requires **explicit opt-in**. The following is the full-dataset
command for the user to run, NOT executed by the agent:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --data-dir data --research-data-dir data/vendor_derived_2015_2025
```

**Holdout warning:** this command uses 2015-2025, including the last three years
previously reserved as unseen. If that holdout must stay unseen, prepare a
separately date-sliced source snapshot/dataset before running; no holdout split
was created here. Do not call an inspected full-range result out-of-sample.
`docs/TESTLOG.md` records the pending research evaluation design.

Research mode verifies original H1/M1 size/mtime snapshots and derived SHA256
checksums; do not edit source files after building. It requires the manifest's
matching H1/M1 and converter sources. Configured M1 checks cannot silently fall
back when the feed fails to load. Run params save dataset identity/manifest hash;
reports show the research warning and use these exact charts, never a silent
broker/H1-resample substitution. Moved/changed datasets can make old report charts
unavailable. Normal H4/D1 mode still requires broker-exported files; live ignores
the research dataset entirely. No strategy, costs, risk limits or pair selection
were retuned to make the dataset fit.

## Configured dice comparison (user runs after a matching reference exists)

Supports the engine's configured H1/H4 and H4/D1 combinations and its current
shared trend-strategy core, not arbitrary plug-in strategies/timeframes. Both
real and random paths load the same chart frames, use the last completed regime
candle, and share execution-bar duration, costs, exits, sizing and portfolio/pair
limits. `--variant A` randomizes timing and direction; `--variant B` randomizes
timing while following the strategy's LONG/SHORT direction. B requires a valid
direction map. Unsupported modes and balance-scaled references are refused.

After the user runs a matching reference, replace `<RUN_ID>` below:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.dice_probe --real-only --reference backtest_results/<RUN_ID> --data-dir data --research-data-dir data/vendor_derived_2015_2025
```

Only after parity passes and the experiment is pre-declared:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.dice_probe --variant B --seeds 300 --reference backtest_results/<RUN_ID> --data-dir data --research-data-dir data/vendor_derived_2015_2025
```

No dice/real-only command above has been run against actual history in this change.
Every invocation checks reference configuration/source identity first, then
per-pair counts, complete trade rows and pooled totals before any random draws.
H4/D1/research requires an explicit new reference: the old H1/H4 pin is not used.
Zero-trade comparisons are refused. `edge_probe` remains legacy H1/H4-only and
was not adapted; the old dice experiment identifier "D1" is not a timeframe lock.

## Backtest

```powershell
run-backtest.bat
```

or: `$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch`
or: `$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --flat-swaps` for zero swaps

Every new run saves `config.yaml`: a byte-for-byte snapshot of the shared config
loaded at startup (`configs/_base.yaml`, or the selected `--base-config` preset).
Comments, formatting and line endings are preserved. Copy it into a preset or
the active config when you want those original settings back; replacing the active
config also affects future trader launches. Existing run folders are unchanged.
This snapshot does NOT include CLI overrides, per-pair cost files or pair selection;
`params.json` still records the resolved run settings. Check it before reproducing a run.

Every run writes `report.html` next to `summary.csv` (skip note if plotly
is missing). Rebuild for an old folder without re-running backtests:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.report --run backtest_results/<id>
```

## First time

```powershell
uv sync
```

## Connection check (no orders)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.smoke
```

## Bias panel — one snapshot, then exit

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor --once
```

## Bias panel — live loop (repaints only on a new H1 close)

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor
```

Or double-click `start-panel.bat`. Stop with Ctrl+C or by closing the window.
Each cycle covers every enabled account (`USE_DEMO`/`USE_REAL`, demo+real at
once); the header shows `DEMO`, `REAL`, or `DEMO+REAL`.

Faster polling (still repaints only on a new H1 close):

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.monitor --interval 30
```

`NONE DETECTED` means every readable pair is FLAT on H4. `DATA ERROR`
names pairs that could not be read. The panel shows bias only;
entries are not defined yet.

FLAT means no trade bias: the last completed H4 bar failed at least one of
EMA20/50 stack, HR1a close-vs-EMA50, or separation >= 0.3 x ATR14.

## Closed-position records (demo + real)

Each loop cycle appends newly closed positions of `--magic` (default 100001)
to `trades/demo.csv` and `trades/real.csv`:
```text
local_time,broker_open,broker_close,symbol,side,volume,entry_price,close_price,profit,commission,swap,magic,ticket,entry_condition,account
```

Closed positions only (open ones appear when they close). `entry_condition`
comes from `trades/journal.csv` matched on ticket, blank if unknown.
Restart-safe: only tickets above the file's max are appended; manual trades
(other magic numbers) are ignored. Real account is read with history calls
only — the panel can never send orders.

Sample screen:

```text
QuantTrader H4 bias panel (H4 B1, bias only)
local time : 2026-10-16 18:05:12 (Malaysia, UTC+8)
broker time: 2026-10-16 10:00:00 (last H1 close, UTC)
account=DEMO  rule=repaint-on-new-H1-close-only
week DEMO: -2.10% (halt at -15%)

SYMBOL   BIAS ENTRY
EURUSD   UP   GO
USDJPY   FLAT -
```

ENTRY is `GO` or the first failing section-5 rule (`HR2`, `HR3`, `HR4`,
`HR4-guard`, `EXT`, `E1-setup`, `E1-trigger`, `warmup`); `-` when FLAT.

## Weekly loss halt

- `.env`: `WEEKLY_LOSS_PCT=15` — halt new entries once this UTC week's
  realized loss (our magic only) reaches 15% of week-start equity.
- State lives in `memory/weekly_demo.json` + `memory/weekly_real.json`
  (gitignored, per account). A new week snapshots fresh equity and clears halt.
- The panel shows a `week <ACCT>: %` line always and a `HALTED` banner when
  tripped. Halt gates the future live executor; panel and records keep running.
- Week = UTC Monday 00:00 for now (spec 8A says broker-server week; that needs
  a broker GMT-offset setting we don't have yet).

## ATR separation switch

One place decides it; pair files and `.env` cannot override it:

1. `configs/_base.yaml`: `strategy.use_atr_sep` — global default, currently `true`.
2. Backtest CLI `--ma-only` forces `false` for one run (sensitivity sweep).

`false` = MA-only: UP if EMA20 >= EMA50 else DOWN, no HR1, no FLAT
(except warmup). Panel title shows `MA-only` when every pair reads it as off.

## Tests

```powershell
$env:PYTHONPATH="python"; uv run pytest -q
```

## Round-trip plumbing test (opens + closes a real 0.01)

`quant.live --roundtrip` is the only command that can send orders, and only
with `--no-dry-run`. Steps, in this order:

1. Terminal open, logged in. In `.env`, enable **exactly one** account
   (demo for this test — the command refuses to run if both are on).
2. Dry run first (sends nothing, plans only):
```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --roundtrip
```
3. Only you, only on demo — opens 0.01 and closes it seconds later:
```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --roundtrip --no-dry-run
```
4. Confirm: `trades/journal.csv` gains `roundtrip-open` + `roundtrip-close`
   rows; next panel cycle appends the closed position to `trades/demo.csv`.
   If CLOSE ever fails, the console prints the position id — close it by hand.

No signal entries exist yet: without `--roundtrip` the command does nothing.

## SL/TP touch test (broker closes the trade)

`--touch-close` opens 0.01 with close SL+TP attached; first touch wins:

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.live --config configs/EURUSD.yaml --touch-close
```

Dry run first (prints planned SL/TP, sends nothing). Real run (add
`--no-dry-run`, exactly one account enabled) waits up to `--timeout` seconds
(default 180) for the broker to close it, then reports `via TP` or `via SL`.
`--distance-points` sets the bracket width (default 10 points ≈ $0.10);
distances below the broker `stops_level` are clamped up and reported.
No touch in time → market-closes like roundtrip and says so. Same manual-close
warning applies if anything fails mid-flight.

## Backtest batch (offline, no terminal needed)

Build H1 once per symbol from the M1 files (plain CSV or HistData zips;
coverage report included). Add `--m1-csv` the first time (writes
`data/<SYM>_M1.csv`, ~200 MB per pair, gitignored): the backtest needs it for
tick-like position checks, and every hour without M1 rows falls back to H1
checks for that bar.

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.mkdata --symbol EURUSD --m1-csv
```

Build all 11 in parallel (same single-symbol command per job; ~1 GB peak RAM per
job; builds also rewrite H1 byte-identical, audit-verified):

```powershell
foreach ($s in "EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","EURGBP","EURJPY","GBPJPY","AUDJPY") {
  Start-Job -Name "mk_$s" -ScriptBlock {
    param($sym)
    Set-Location "C:\Users\SCSM11\Desktop\Dev Folder\FullStack\Project\QuantTrader"
    $env:PYTHONPATH = "python"; uv run python -m quant.mkdata --symbol $sym --m1-csv
  } -ArgumentList $s | Out-Null
}
Get-Job -Name "mk_*" | Wait-Job | Out-Null
Get-Job -Name "mk_*" | Where-Object State -ne "Completed"   # anything here: rerun singly
Get-Job -Name "mk_*" | Sort-Object Name | Receive-Job -Keep
Get-Job -Name "mk_*" | Remove-Job
(Get-ChildItem data\*_M1.csv).Count                          # expect 11
```

Run the batch (double-click `run-backtest.bat` does the same). Tick pairs on/off
in `configs/scan-selection.yml`. Results land in `backtest_results/<local-time>/`:
`summary.csv`, `funnel.csv` (survivors per rule, spec section 2 order),
`trades_<SYM>.csv`, `params.json` (effective settings for reproducibility).
Enabled pairs without `data/<SYM>_H1.csv` print `SKIP` and the batch continues.
`configs/_base.yaml` `limits.no_trade_ranges` lists recurring no-trade windows
(default: `12-15` to `01-01`); entries whose fill day falls inside are skipped
(funnel `window` column) and open positions keep their stop/trail.

Sweeps (one factor at a time):

```powershell
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --atr-n 14
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --sep-atr 0.0
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --ma-only
$env:PYTHONPATH="python"; uv run python -m quant.backtest --batch --spread-pips 3.0
```

Gate toggles (ablation, spec 11.4): `use_hr2/hr3/hr4/ext/e1_setup/e1_trigger`
in `_base.yaml` (all default true; false = gate auto-passes, own funnel effect).
Size is fixed `--lot` (default 0.01); `--lot 0` sizes from `--risk-usd` instead.
R always divides by actual risk. Pip math reference: `docs/PIP_VALUES.md`
(1 pip = 10 points; 300 points = 30 pips = $3.00 at 0.01 on EURUSD).

Single pair: `--config configs/EURUSD.yaml --data data/EURUSD_H1.csv`.
Known deviations (strategy testing only, not go-live calibration): H4 blocks
anchor at 00:00 UTC, spread fixed 20 points, 5/3-digit tick math, UTC weeks.
Quote-foreign pairs size through converter feeds auto-loaded from `data/`
(JPY via USDJPY, GBP via GBPUSD, ...); SKIP with notice when absent.

## Not built yet

`quant.live` signal entries (only `--roundtrip` / `--touch-close` exist).
Journal rows (`trades/journal.csv`) appear on fills.
