# Test Log — every run, one row

The single index of what we tried and what it did. Newest first.
Full numbers live in each `backtest_results/<run-id>/` (params.json is the truth); this is the readable tier.

## Pass line (fixed before each run — do not move after seeing results)

- Acceptance = STRATEGY.md §12 + `configs/_base.yaml benchmarks:` (graded verdict: PASS/WARN/FAIL per run).
- Probe verdict (pre-decided 2026-10-17): CONFIRMED iff pooled onset mean edge ≥ 0 AND mean − 2×SE > 0 at **both** 48 and 72 bars. 24-bar horizon = info only, never used to pick a horizon afterwards. Per-pair rows = information only, never verdict material.
- One rule change per run. The variant count is the row count below.

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
