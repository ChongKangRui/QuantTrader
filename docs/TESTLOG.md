# Test Log — every run, one row

The single index of what we tried and what it did. Newest first.
Full numbers live in each `backtest_results/<run-id>/` (params.json is the truth); this is the readable tier.

## Pass line (fixed before each run — do not move after seeing results)

- Acceptance = STRATEGY.md §12 + `configs/_base.yaml benchmarks:` (graded verdict: PASS/WARN/FAIL per run).
- Probe verdict (pre-decided 2026-10-17): CONFIRMED iff pooled onset mean edge ≥ 0 AND mean − 2×SE > 0 at **both** 48 and 72 bars. 24-bar horizon = info only, never used to pick a horizon afterwards. Per-pair rows = information only, never verdict material.
- One rule change per run. The variant count is the row count below.

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
