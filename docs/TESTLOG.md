# Test Log — every run, one row

The single index of what we tried and what it did. Newest first.
Full numbers live in each `backtest_results/<run-id>/` (params.json is the truth); this is the readable tier.

## Pass line (fixed before each run — do not move after seeing results)

- Acceptance = STRATEGY.md §12 + `configs/_base.yaml benchmarks:` (graded verdict: PASS/WARN/FAIL per run).
- Probe verdict (pre-decided 2026-10-17): CONFIRMED iff pooled onset mean edge ≥ 0 AND mean − 2×SE > 0 at **both** 48 and 72 bars. 24-bar horizon = info only, never used to pick a horizon afterwards. Per-pair rows = information only, never verdict material.
- One rule change per run. The variant count is the row count below.

## D1 dice probe — pre-declaration (2026-10-18, written BEFORE any dice run)

Question: do the entry rules beat dice, or does the reference result sit inside dice luck?

- Reference (pinned): `20261018_173936_prefix` (renamed 2026-10-19 to label it
  pre-fix — originally `20261018_173936`, identical to 174249/174651) — batch, **no cost flags** (params.json: slippage 0, per-pair spreads+swaps, scope 2.5–3.6, max_total_positions **5**, ccy net 2, weekly halt 15%, M1 checks, cap 20/day). Reference figures: 2064 trades, −54.84 USD, −0.013R pooled. **This pin is stale until the post-fix batch re-run replaces it** (dice parity intentionally fails against it now).
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
