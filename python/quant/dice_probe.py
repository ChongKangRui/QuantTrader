"""Dice-entry probe (D1): do the entry rules beat random entries?

Same engine, same exits, same costs, same caps — only the entry moment is
dice. Variant A draws any bar and a random direction (placebo); variant B
draws bias-ON H1 bars and follows the mapped H4 bias (tests entry timing
only). Per pair the dice draw in waves until the recorded trade count
reaches the real run's pre-filter count, then thin uniformly at random to
that target; the same daily cap and portfolio pass run in the engine's
order. Verdict metric = pooled mean R per trade (post-pass); the verdict
rule is pre-decided in docs/TESTLOG.md (D1-B: the real run must beat the
95th percentile of the dice distribution).

Modes:
  --real-only   parity: push the real signals through this pipeline and
                compare against the reference run folder (must match exactly).
  --variant A|B dice runs (parity runs first, every invocation).

No orders, no MT5. Results land in dice_results/<stamp>/.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from quant.backtest import (WIN_BARS, _atr_wilder, _load_m1, apply_daily_cap,
                            bias_frames, build_h4, load_h1, local_stamp,
                            map_bias, portfolio_filter, scan_pair, simulate,
                            total_row)
from quant.limits import parse_no_trade_ranges
from quant.monitor import flatten_strategy, load_pairs, read_selection

CONV_MAP = {"JPY": "USDJPY", "GBP": "GBPUSD", "AUD": "AUDUSD",
            "NZD": "NZDUSD", "CAD": "USDCAD", "CHF": "USDCHF"}

# per-process state: parity workers build one env per task; dice workers get
# their pair chunk via the initializer (spawn re-imports the module, so
# nothing survives unless passed through initargs)
_STATE: dict = {}


def resolve_setup(config_dir: str = "configs") -> dict:
    """Batch-mode config exactly as backtest.main resolves it, minus CLI
    overrides: the pinned reference carries no cost flags by declaration."""
    import yaml

    with open(Path(config_dir) / "_base.yaml", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    strat = flatten_strategy(base)
    limits = dict(base.get("limits") or {})
    risk = dict(base.get("risk") or {})
    scope = dict(risk.get("sizing_scope_usd") or {})
    selection = read_selection(config_dir)
    jobs: list[tuple[str, Path, dict]] = []
    for pr in load_pairs(config_dir):
        sym = pr["symbol"]
        if selection is not None and not selection.get(sym, True):
            continue
        h1_path = Path("data") / f"{sym}_H1.csv"
        if not h1_path.exists():
            print(f"SKIP {sym} - no {h1_path}", flush=True)
            continue
        costs = dict(base.get("costs") or {})
        costs.update(pr.get("costs") or {})
        jobs.append((sym, h1_path, costs))
    # converter feeds for quote-foreign sizing, same wiring as backtest.main
    need: dict[str, list[str]] = {}
    for sym, _, _ in jobs:
        if sym[3:] == "USD" or sym.startswith("USD"):
            continue
        feed = CONV_MAP.get(sym[3:])
        if feed:
            need.setdefault(feed, []).append(sym)
    converters: dict[str, pd.Series] = {}
    for feed, syms in need.items():
        fp = Path("data") / f"{feed}_H1.csv"
        if not fp.exists():
            raise FileNotFoundError(f"{fp}: converter feed missing for "
                                    f"{', '.join(syms)}")
        converters[feed] = load_h1(fp).set_index("time")["close"]
    return {
        "strategy": strat,
        "jobs": jobs,
        "converters": converters,
        "risk_usd": 3.0,
        "max_cost_ratio": float(limits.get("max_cost_ratio", 0.10) or 0.0),
        "scope_low": float(scope.get("low", 0.0) or 0.0),
        "scope_high": float(scope.get("high", 0.0) or 0.0),
        "max_day": int(limits.get("max_trades_per_day", 0) or 0),
        "max_open": int(risk.get("max_total_positions", 0) or 0),
        "max_ccy_net": int(risk.get("max_ccy_net", 0) or 0),
        "weekly_r": float(limits.get("weekly_loss_r", 0.0) or 0.0),
        "position_checks": str((base.get("timeframes") or {}).get(
            "position_checks", "M1")).upper(),
        "no_trade_ranges": tuple(parse_no_trade_ranges(base)),
    }


def env_from_frames(symbol: str, h1: pd.DataFrame, costs: dict, setup: dict,
                    m1: pd.DataFrame | None) -> dict:
    """Per-pair resident state: frames + the ATR series dice candidates need.

    The ATR is the same Wilder formula check_entry uses. check_entry computes
    it over a trailing 400-bar window; with alpha=1/n the seed influence after
    400 bars is ~1e-26, so the full-series values equal the windowed ones to
    float dust (candidates only ever draw at t >= WIN_BARS).
    """
    strat = setup["strategy"]
    h4 = build_h4(h1)
    mapped = map_bias(h1, h4, bias_frames(h4, strat))
    atr = _atr_wilder(h1["high"], h1["low"], h1["close"],
                      int(strat.get("atr_n") or 7)).to_numpy()
    t0 = max(WIN_BARS, int(strat.get("warmup_bars", 300)))
    return {"symbol": symbol, "h1": h1, "h4": h4, "mapped": mapped, "m1": m1,
            "atr": atr, "t0": t0, "costs": costs}


def build_env(symbol: str, h1_path: str | Path, costs: dict, setup: dict) -> dict:
    m1 = None
    if setup["position_checks"] == "M1":
        m1 = _load_m1(h1_path, symbol)
    return env_from_frames(symbol, load_h1(h1_path), costs, setup, m1)


def _simulate(env: dict, cands: list[dict]) -> tuple[pd.DataFrame, dict]:
    """One engine simulate call with run_pair's exact wiring."""
    setup = _STATE["setup"]
    return simulate(env["h1"], env["symbol"], cands, setup["strategy"],
                    env["costs"], setup["risk_usd"], setup["max_cost_ratio"],
                    bias_flip_exit=bool(setup["strategy"].get(
                        "bias_flip_exit", False)),
                    weekend_flat=bool(setup["strategy"].get(
                        "weekend_flat", False)),
                    mapped=env["mapped"], lot=None,
                    converters=setup["converters"], m1=env["m1"],
                    no_trade_ranges=setup["no_trade_ranges"],
                    scope_low=setup["scope_low"],
                    scope_high=setup["scope_high"])


def eligible_bars(env: dict, variant: str) -> np.ndarray:
    """Bars a dice entry may land on: t+1 must exist (fill bar) and the ATR
    must be valid (check_entry rejects NaN/nonpositive ATR). Variant B keeps
    only bias-ON bars — NEUTRAL has no direction to align with."""
    atr = env["atr"]
    idx = np.arange(env["t0"], len(env["h1"]) - 1)
    idx = idx[np.isfinite(atr[idx]) & (atr[idx] > 0)]
    if variant == "B":
        dirs = env["mapped"]["direction"].to_numpy()[idx]
        idx = idx[dirs != "NEUTRAL"]
    return idx


class _Stream:
    """One (seed, pair) dice stream: a shuffled bar pool plus, for variant A,
    pre-drawn directions aligned to pool positions. One numpy stream keeps
    every draw reproducible."""

    def __init__(self, env: dict, variant: str, rng: np.random.Generator):
        self.env = env
        self.pool = rng.permutation(eligible_bars(env, variant))
        if variant == "A":
            self.dirs = np.where(rng.random(self.pool.size) < 0.5,
                                 "LONG", "SHORT")
        else:
            self.dirs = env["mapped"]["direction"].to_numpy()[self.pool]
        self.pos = 0

    def draw(self, count: int) -> list[dict]:
        """Next `count` candidates, sorted in time order (simulate walks
        candidates in time order for the open/day rules)."""
        count = max(0, min(count, len(self.pool) - self.pos))
        start, atr = self.pos, self.env["atr"]
        self.pos += count
        out = [{"t": int(self.pool[start + k]),
                "direction": str(self.dirs[start + k]),
                "atr": float(atr[self.pool[start + k]]),
                "time": self.env["h1"]["time"].iloc[self.pool[start + k]]}
               for k in range(count)]
        out.sort(key=lambda c: c["t"])
        return out

    @property
    def left(self) -> int:
        return len(self.pool) - self.pos


def dice_pair_trades(env: dict, variant: str, target: int,
                     rng: np.random.Generator, first_wave_mult: float = 4.0,
                     topup_mult: float = 2.0,
                     max_waves: int = 20) -> tuple[pd.DataFrame, dict]:
    """Adaptive waves: draw -> simulate the full cumulative candidate set
    from scratch (the open-position rule interleaves, so each new candidate
    can change which earlier ones get skipped) -> repeat until the recorded
    trade count reaches the target, then thin uniformly at random to the
    target (never first-in-time: that would favour early years)."""
    stream = _Stream(env, variant, rng)
    cands: list[dict] = []
    trades = pd.DataFrame()
    extra: dict = {}
    waves = 0
    while waves < max_waves:
        if waves == 0:
            want = int(first_wave_mult * target) if target > 0 else 0
        else:
            want = int(max(50, topup_mult * (target - len(trades))))
        take = stream.draw(want)
        if not take:
            break
        cands += take
        cands.sort(key=lambda c: c["t"])
        trades, extra = _simulate(env, cands)
        waves += 1
        if len(trades) >= target or stream.left <= 0:
            break
    drawn = len(cands)
    if len(trades) > target:
        pick = np.sort(rng.choice(len(trades), size=target, replace=False))
        trades = trades.iloc[pick].reset_index(drop=True)
    diag = {"symbol": env["symbol"], "target": target, "waves": waves,
            "drawn": drawn, "kept": len(trades),
            "shortfall": max(target - len(trades), 0), **extra}
    return trades, diag


# ---------------------------------------------------------------------------
# portfolio assembly — the engine's post-filters, in the engine's order


def apply_filters(trades_by_sym: dict[str, pd.DataFrame], setup: dict
                  ) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict]]:
    capped, cap_drops = apply_daily_cap(trades_by_sym, setup["max_day"])
    kept, pf_drops = portfolio_filter(
        capped, setup["max_open"], setup["max_ccy_net"], setup["weekly_r"])
    return kept, cap_drops, pf_drops


def pooled_stats(trades_by_sym: dict[str, pd.DataFrame]) -> dict:
    frames = [t for t in trades_by_sym.values() if len(t)]
    if not frames:
        return {"trades": 0, "net_usd": 0.0, "swap_usd": 0.0, "net_R": 0.0,
                "expect_R": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
                "max_dd": 0.0}
    row = total_row(pd.concat(frames, ignore_index=True))
    return {k: row[k] for k in ("trades", "net_usd", "swap_usd", "net_R",
                                "expect_R", "win_rate", "profit_factor",
                                "max_dd")}


def _real_one(sym: str, h1_path: str, costs: dict, setup: dict
              ) -> tuple[str, pd.DataFrame, int]:
    """One pair through the real pipeline: scan -> simulate (pre-cap/pass)."""
    _STATE["setup"] = setup
    env = build_env(sym, h1_path, costs, setup)
    _, cands = scan_pair(env["h1"], env["h4"], sym, setup["strategy"])
    trades, _ = _simulate(env, cands)
    return sym, trades, len(trades)


def check_parity(kept_counts: dict[str, int], total: dict, reference: Path
                 ) -> tuple[bool, dict]:
    """Compare the real-pipeline output against the pinned reference folder."""
    ref_total = pd.read_csv(reference / "summary.csv").set_index(
        "symbol").loc["TOTAL"]
    diffs: list[str] = []
    for sym, n_kept in kept_counts.items():
        ref_csv = reference / f"trades_{sym}.csv"
        ref_n = (sum(1 for _ in open(ref_csv, encoding="utf-8")) - 1
                 if ref_csv.exists() else 0)
        if n_kept != ref_n:
            diffs.append(f"{sym}: kept {n_kept} vs {ref_n}")
    for key in ("trades", "net_usd", "expect_R", "swap_usd"):
        got, want = float(total[key]), float(ref_total[key])
        if abs(got - want) > 0.005:
            diffs.append(f"TOTAL {key}: {got} vs {want}")
    return not diffs, {"diffs": diffs, "total": total,
                       "reference": {"trades": int(ref_total["trades"]),
                                     "net_usd": float(ref_total["net_usd"]),
                                     "expect_R": float(ref_total["expect_R"])}}


# ---------------------------------------------------------------------------
# dice phases. Phase 1 (parity): one shared pool, one task per pair. Phase 2
# (dice): one pinned single-worker executor per pair chunk so every pair's
# frames load exactly once and stay resident across all seeds; seeds stay
# sequential in the parent because the daily cap and the portfolio pass need
# all pairs of a seed in one place.


def _worker_init(chunk: list[tuple[str, str, dict]], setup: dict,
                 seed_index: dict[str, int]) -> None:
    _STATE["setup"] = setup
    _STATE["seed_index"] = seed_index
    _STATE["env"] = {sym: build_env(sym, h1_path, costs, setup)
                     for sym, h1_path, costs in chunk}


def _worker_seed(seed_idx: int, variant: str, targets: dict[str, int],
                 seed_base: int, first_wave_mult: float, topup_mult: float,
                 max_waves: int) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    by_sym, diags = {}, []
    for sym, env in _STATE["env"].items():
        target = int(targets.get(sym, 0))
        if target <= 0:
            by_sym[sym] = pd.DataFrame()
            continue
        rng = np.random.default_rng([seed_base, seed_idx,
                                     _STATE["seed_index"][sym]])
        trades, diag = dice_pair_trades(env, variant, target, rng,
                                        first_wave_mult, topup_mult, max_waves)
        by_sym[sym] = trades
        diag["seed"] = seed_idx
        diags.append(diag)
    return by_sym, diags


def run_seeds(executors: list[ProcessPoolExecutor], setup: dict, variant: str,
              targets: dict[str, int], seeds: int, seed_base: int,
              outdir: Path, first_wave_mult: float, topup_mult: float,
              max_waves: int, first_seed: int = 0) -> pd.DataFrame:
    rows: list[dict] = []
    all_diags: list[dict] = []
    t_start = time.perf_counter()
    for pos, i in enumerate(range(first_seed, first_seed + seeds)):
        by_sym: dict[str, pd.DataFrame] = {}
        diags: list[dict] = []
        for ex in executors:
            res = ex.submit(_worker_seed, i, variant, targets, seed_base,
                            first_wave_mult, topup_mult, max_waves).result()
            by_sym.update(res[0])
            diags += res[1]
        kept, _, _ = apply_filters(by_sym, setup)
        total = pooled_stats(kept)
        pre = pooled_stats(by_sym)
        rows.append({"seed": i, "variant": variant, **total,
                     "expect_R_pre": pre["expect_R"],
                     "trades_pre": pre["trades"]})
        all_diags += diags
        pd.DataFrame(rows).to_csv(outdir / "seeds.csv", index=False)
        rate = (time.perf_counter() - t_start) / (pos + 1)
        print(f"seed {i + 1}/{first_seed + seeds}: trades={total['trades']} "
              f"net={total['net_usd']} expect={total['expect_R']}R "
              f"({rate:.1f}s/seed, eta {rate * (first_seed + seeds - i - 1):.0f}s)",
              flush=True)
    pd.DataFrame(all_diags).to_csv(outdir / "dice_pairs.csv", index=False)
    return pd.DataFrame(rows)


def verdict_line(real_expect: float, dice_expect: np.ndarray,
                 pct: float = 0.95) -> dict:
    """Pre-decided rule (TESTLOG D1): CONFIRMED iff real > dice P95."""
    if len(dice_expect) == 0:
        return {"real_expect_R": real_expect, "dice_p95": None,
                "percentile_of_real": None, "n_seeds": 0, "confirmed": False}
    p95 = float(np.quantile(dice_expect, pct))
    rank = float((dice_expect < real_expect).mean() * 100)
    return {"real_expect_R": real_expect, "dice_p95": round(p95, 4),
            "percentile_of_real": round(rank, 1),
            "n_seeds": int(len(dice_expect)),
            "confirmed": bool(real_expect > p95)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="D1 dice-entry probe (no orders): rules vs dice, same engine.")
    ap.add_argument("--variant", choices=("A", "B"), default="B")
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--first-seed", type=int, default=0,
                    help="first seed index (streams are per-index, so a "
                         "resumed run's rows merge with the earlier ones)")
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--jobs", type=int, default=5,
                    help="parallel pair workers; 0 = all cores")
    ap.add_argument("--first-wave-mult", type=float, default=4.0)
    ap.add_argument("--topup-mult", type=float, default=2.0)
    ap.add_argument("--max-waves", type=int, default=20)
    ap.add_argument("--pct", type=float, default=0.95,
                    help="verdict percentile (pre-declared: 0.95)")
    ap.add_argument("--reference", default="backtest_results/20261018_173936_prefix")
    ap.add_argument("--real-only", action="store_true",
                    help="parity + target counts only, no dice")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--results-root", default="dice_results")
    args = ap.parse_args(argv)
    if args.seeds < 1:
        ap.error("--seeds must be >= 1")

    setup = resolve_setup(args.config_dir)
    outdir = Path(args.results_root) / (
        f"{local_stamp()}_real" if args.real_only else local_stamp())
    outdir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(args.jobs if args.jobs else (os.cpu_count() or 1),
                         len(setup["jobs"])))

    # phase 1 — parity, every invocation: dice targets come from it, and a
    # pipeline that does not reproduce the reference must not roll dice
    print("PARITY: running real signals through the dice pipeline "
          f"({workers} workers)...", flush=True)
    by_sym: dict[str, pd.DataFrame] = {}
    targets: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_real_one, sym, str(path), costs, setup): sym
                for sym, path, costs in setup["jobs"]}
        for fut in futs:
            sym, trades, n_pre = fut.result()
            by_sym[sym] = trades
            targets[sym] = n_pre
            print(f"real {sym}: pre-pass trades={n_pre}", flush=True)
    kept, cap_drops, pf_drops = apply_filters(by_sym, setup)
    total = pooled_stats(kept)
    ok, detail = check_parity({s: len(t) for s, t in kept.items()}, total,
                              Path(args.reference))
    (outdir / "parity.json").write_text(
        json.dumps({"pass": ok, **detail, "targets": targets}, indent=1),
        encoding="utf-8")
    print(f"PARITY {'PASS' if ok else 'FAIL'}: trades={total['trades']} "
          f"net={total['net_usd']} expect={total['expect_R']}R "
          f"(cap drops {len(cap_drops)}, pass drops {len(pf_drops)})", flush=True)
    if not ok:
        for d in detail["diffs"][:10]:
            print(f"  diff: {d}", flush=True)
        print("Parity failed. Suspect the reference run first (older code): "
              "re-run it with the current code before assuming a probe bug.",
              flush=True)
        return 1
    if args.real_only:
        print(f"targets -> {outdir / 'parity.json'}", flush=True)
        return 0

    config = {"variant": args.variant, "seeds": args.seeds,
              "seed_base": args.seed_base, "pct": args.pct,
              "first_wave_mult": args.first_wave_mult,
              "topup_mult": args.topup_mult, "max_waves": args.max_waves,
              "reference": args.reference, "targets": targets,
              "setup": {k: v for k, v in setup.items()
                        if k not in ("jobs", "converters")}}
    (outdir / "config.json").write_text(json.dumps(config, indent=1),
                                        encoding="utf-8")
    # phase 2 — dice: pinned executors, pairs round-robin over chunks
    seed_index = {sym: i for i, (sym, _, _) in enumerate(setup["jobs"])}
    live = [(sym, str(path), costs) for sym, path, costs in setup["jobs"]
            if targets[sym] > 0]
    chunks: list[list[tuple[str, str, dict]]] = [[] for _ in
                                                  range(min(workers, len(live)))]
    for i, job in enumerate(live):
        chunks[i % len(chunks)].append(job)
    executors = [ProcessPoolExecutor(max_workers=1, initializer=_worker_init,
                                     initargs=(chunk, setup, seed_index))
                 for chunk in chunks]
    try:
        print(f"D1-{args.variant}: {args.seeds} seeds, targets {targets}, "
              f"{len(chunks)} pair workers", flush=True)
        seeds_df = run_seeds(executors, setup, args.variant, targets,
                             args.seeds, args.seed_base, outdir,
                             args.first_wave_mult, args.topup_mult,
                             args.max_waves, first_seed=args.first_seed)
    finally:
        for ex in executors:
            ex.shutdown()

    verdict = verdict_line(float(total["expect_R"]),
                           seeds_df["expect_R"].to_numpy(), args.pct)
    money_bar = bool(total["expect_R"] >= 0.10)
    (outdir / "verdict.json").write_text(json.dumps(
        {"d1": verdict, "money_bar_0_10R": money_bar,
         "rule": f"D1-B CONFIRMED iff real pooled expect_R > dice P{args.pct}"},
        indent=1), encoding="utf-8")
    print(f"VERDICT D1-{args.variant}: "
          f"{'CONFIRMED' if verdict['confirmed'] else 'WITHIN DICE NOISE'} "
          f"(real {verdict['real_expect_R']}R vs dice "
          f"P{args.pct} {verdict['dice_p95']}R, percentile "
          f"{verdict['percentile_of_real']}); money bar >= +0.10R: "
          f"{'MET' if money_bar else 'NOT MET'}", flush=True)
    _write_histogram(outdir, seeds_df, float(total["expect_R"]), args.variant)
    print(f"dice results -> {outdir}", flush=True)
    return 0


def _write_histogram(outdir: Path, seeds_df: pd.DataFrame,
                     real_expect: float, variant: str) -> None:
    """Best-effort plotly histogram of the dice expectancy distribution."""
    try:
        import plotly.express as px
    except Exception as exc:
        print(f"histogram skipped ({exc})", flush=True)
        return
    fig = px.histogram(seeds_df, x="expect_R", nbins=40,
                       title=f"D1-{variant}: dice pooled expectancy per seed "
                             f"(real run marked at {real_expect}R)")
    fig.add_vline(x=real_expect, line_width=2, line_dash="dash")
    fig.write_html(outdir / "histogram.html")
    print("histogram -> histogram.html", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
