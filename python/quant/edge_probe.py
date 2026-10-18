"""Bias-only edge probe: does the H4 bias alone predict forward H1 movement?

No trades, no caps, no windows — a measurement, not a simulation. Event sets:
onset = the bar where bias direction changes (verdict set), state = every
bias-on bar (descriptive, R2 enters there), null = random bars with random
direction (machinery sanity). Move = direction-aligned close-to-close change
over the next 24/48/72 H1 bars in H1 ATR units. The verdict rule is fixed in
docs/TESTLOG.md BEFORE results: pooled onset edge >= 0 beyond 2 SE at 48 AND
72 bars; per-pair rows and the 24-bar horizon are information only.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant.backtest import bias_frames, build_h4, load_h1, map_bias

HORIZONS_DEFAULT = (24, 48, 72)


def _pip_default(symbol: str) -> float:
    """Same 5-digit assumption the engine uses in tick_spec()."""
    return 0.01 if "JPY" in symbol else 0.0001


def _load_pip_size(pair_yaml: Path | None, symbol: str) -> float:
    pip = _pip_default(symbol)
    if pair_yaml and pair_yaml.exists():
        try:
            cfg = yaml.safe_load(pair_yaml.read_text(encoding="utf-8")) or {}
            pip = float(cfg.get("pip_size", pip))
        except Exception:
            pass  # fall back to the tick-free default rather than stop the probe
    return pip


def _cost_atr(costs: dict, pip_size: float, atr_mean: float) -> float:
    """Round-trip trading cost (spread once + slippage both ways) in ATR units."""
    spread_pips = float(costs.get("spread_points", 0) or 0) / 10.0
    slip_pips = float(costs.get("slippage_pips", 0) or 0)
    cost_pips = spread_pips + 2.0 * slip_pips
    if atr_mean <= 0:
        return float("nan")
    return cost_pips * pip_size / atr_mean


def _events(direction: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Onset indices (any flip into a non-NEUTRAL direction) and state mask."""
    d = direction.to_numpy()
    flip = np.empty(len(d), dtype=bool)
    flip[0] = False
    flip[1:] = d[1:] != d[:-1]
    onset = np.where(flip & (d != "NEUTRAL"))[0]
    state = np.where(d != "NEUTRAL")[0]
    return onset, state


def _moves(close: np.ndarray, atr: np.ndarray, sites: np.ndarray, signs: np.ndarray,
           k: int) -> tuple[np.ndarray, int]:
    """Direction-aligned k-bar forward moves in ATR units; no lookahead past the end."""
    n = len(close)
    ok = sites + k < n
    ok &= np.isfinite(atr[sites]) & (atr[sites] > 0)
    truncated = int((~ok).sum())
    s, g = sites[ok], signs[ok]
    return (close[s + k] - close[s]) * g / atr[s], truncated


def probe_pair(symbol: str, h1: pd.DataFrame, p: dict, costs: dict, rng: np.random.Generator,
               horizons: tuple[int, ...], pip_size: float) -> list[dict]:
    """Row blobs per kind and horizon: moves in ATR units (direction-aligned)."""
    h4 = build_h4(h1)
    bf = bias_frames(h4, p)
    mapped = map_bias(h1, h4, bf)
    atr = _atr_series(h1, p)
    close = h1["close"].to_numpy(dtype=float)
    atr_arr = atr.to_numpy(dtype=float)
    atr_mean = float(np.nanmean(atr_arr)) if np.isfinite(atr_arr).any() else 0.0
    cost = _cost_atr(costs, pip_size, atr_mean)
    onset, state = _events(mapped["direction"])
    sites_null = rng.integers(0, len(close), size=len(onset))
    signs_null = np.where(rng.random(len(onset)) < 0.5, 1, -1)
    sets = {
        "onset": (onset, np.where(mapped["direction"].to_numpy()[onset] == "SHORT", -1, 1)),
        "state": (state, np.where(mapped["direction"].to_numpy()[state] == "SHORT", -1, 1)),
        "null": (sites_null, signs_null),
    }
    rows = []
    for kind, (sites, signs) in sets.items():
        for k in horizons:
            moves, truncated = _moves(close, atr_arr, sites, signs, k)
            rows.append({"symbol": symbol, "kind": kind, "horizon": k, "n": len(moves),
                         "truncated": truncated, "cost_atr": cost, "moves": moves})
    return rows


def _atr_series(h1: pd.DataFrame, p: dict) -> pd.Series:
    from quant.signals import _atr_wilder

    period = int(p.get("atr_n", 7))
    return _atr_wilder(h1["high"], h1["low"], h1["close"], period)


def pool(rows: list[dict], kind: str, horizon: int) -> dict:
    """Pooled row across pairs: edge per event subtracts that pair's own cost."""
    sel = [r for r in rows if r["kind"] == kind and r["horizon"] == horizon and r["moves"].size]
    if not sel:
        return {"symbol": "POOLED", "kind": kind, "horizon": horizon, "n": 0,
                "truncated": 0, "cost_atr": float("nan"), "moves": np.array([]),
                "mean_move": float("nan"), "mean_edge": float("nan"),
                "se": float("nan"), "lo": float("nan"), "hi": float("nan")}
    moves = np.concatenate([r["moves"] for r in sel])
    costs = np.concatenate([np.full(r["moves"].size, r["cost_atr"]) for r in sel])
    edges = moves - costs
    mean, se = float(edges.mean()), float(edges.std(ddof=1) / np.sqrt(edges.size))
    return {"symbol": "POOLED", "kind": kind, "horizon": horizon,
            "n": int(edges.size), "truncated": sum(r["truncated"] for r in sel),
            "cost_atr": float(np.mean([r["cost_atr"] for r in sel])),
            "moves": moves, "mean_move": float(moves.mean()), "mean_edge": mean,
            "se": se, "lo": mean - 2.0 * se, "hi": mean + 2.0 * se}


def verdict(pools: list[dict], verdict_horizons: tuple[int, int] = (48, 72)) -> str:
    """Pre-decided rule (docs/TESTLOG.md): CONFIRMED iff pooled onset mean_edge
    > 0 AND mean_edge - 2*SE > 0 at BOTH verdict horizons."""
    under_cost, within_noise = [], []
    for k in verdict_horizons:
        row = next((r for r in pools if r["kind"] == "onset" and r["horizon"] == k), None)
        if row is None or row["n"] == 0:
            under_cost.append(k)
        elif row["mean_edge"] - 2.0 * row["se"] > 0:
            continue  # this horizon clears the line
        elif row["mean_edge"] > 0:
            within_noise.append(k)
        else:
            under_cost.append(k)
    if not under_cost and not within_noise:
        return "CONFIRMED"
    if under_cost and not within_noise:
        return f"NOT CONFIRMED (edge below cost at {under_cost})"
    if within_noise and not under_cost:
        return f"NOT CONFIRMED (positive but within noise at {within_noise})"
    return f"NOT CONFIRMED (below cost at {under_cost}, within noise at {within_noise})"


def _fmt_row(r: dict) -> str:
    return (f"{r['kind']:>6} {r['symbol']:>7} k={r['horizon']:>2} n={r['n']:>5} "
            f"trunc={r['truncated']:>4} move={r['mean_move']:+.3f} "
            f"cost={r['cost_atr']:.3f} edge={r['mean_edge']:+.4f} "
            f"[{r['lo']:+.4f}, {r['hi']:+.4f}]")


def _pair_jobs(args) -> list[tuple[str, Path, float, dict]]:
    """(symbol, h1_path, pip_size, pair-cost overrides) like backtest main."""
    if args.batch:
        from quant.monitor import load_pairs, read_selection

        pairs = load_pairs(args.config_dir)
        selection = read_selection(args.config_dir)
        jobs = []
        for pr in pairs:
            sym = pr["symbol"]
            if selection is not None and not selection.get(sym, True):
                continue
            path = Path(args.data_dir) / f"{sym}_H1.csv"
            if not path.exists():
                print(f"SKIP {sym} - no {path}", flush=True)
                continue
            jobs.append((sym, path,
                         _load_pip_size(Path(args.config_dir) / f"{pr['name']}.yaml", sym),
                         dict(pr.get("costs") or {})))
        return jobs
    if not args.config or not args.data:
        raise SystemExit("Need --config + --data, or --batch.")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    sym = str(cfg.get("symbol") or Path(args.config).stem)
    return [(sym, Path(args.data), _load_pip_size(Path(args.config), sym),
             dict(cfg.get("costs") or {}))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bias-only edge probe (no trades).")
    ap.add_argument("--config", default=None, help="single pair yaml")
    ap.add_argument("--data", default=None, help="single H1 csv")
    ap.add_argument("--batch", action="store_true", help="loop scan-selection.yml")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--horizons", default="24,48,72")
    ap.add_argument("--csv", default=None, help="optional csv out")
    args = ap.parse_args(argv)
    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())

    with open(Path(args.config_dir) / "_base.yaml", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    from quant.monitor import flatten_strategy

    strat = flatten_strategy(base)
    costs = dict(base.get("costs") or {})
    jobs = _pair_jobs(args)
    if not jobs:
        print("Nothing to probe.", flush=True)
        return 1

    rows: list[dict] = []
    for i, (sym, path, pip, pair_costs) in enumerate(jobs):
        rng = np.random.default_rng([args.seed, i])
        h1 = load_h1(path)
        # per-pair live costs (spreadcheck calibration) on top of the base block
        pc = dict(costs)
        pc.update(pair_costs)
        rows.extend(probe_pair(sym, h1, strat, pc, rng, horizons, pip))

    pools = [pool(rows, kind, k) for kind in ("onset", "state", "null") for k in horizons]
    print("per-pair rows are INFORMATION ONLY (single-pair means are noise).", flush=True)
    for r in rows:
        if r["n"]:
            mean = float(r["moves"].mean())
            print(f"{r['kind']:>6} {r['symbol']:>7} k={r['horizon']:>2} n={r['n']:>5} "
                  f"trunc={r['truncated']:>4} move={mean:+.3f} cost={r['cost_atr']:.3f}",
                  flush=True)
    print("--- pooled across pairs (verdict material for onset only) ---", flush=True)
    for r in pools:
        tag = ""  # kind/horizon printed explicitly; 24-bar and state/null are info only
        note = "info only" if not (r["kind"] == "onset" and r["horizon"] in (48, 72)) else "verdict"
        print(f"{_fmt_row(r)}  {note}", flush=True)
    v = verdict(pools)
    print(f"probe verdict: {v}", flush=True)

    if args.csv:
        table = pd.DataFrame([{k: (np.round(v, 6).item() if isinstance(v, np.ndarray) else v)
                              for k, v in r.items() if k != "moves"} for r in rows + pools])
        table.to_csv(args.csv, index=False)
        print(f"probe table -> {args.csv}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
