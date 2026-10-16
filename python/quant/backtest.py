"""Offline backtester on the shared signal core (bias.py + signals.py). No MT5 needed.

Pipeline per pair: load H1 -> build H4 -> bias map -> entry scan (funnel) ->
sizing/cost/risk -> lifecycle simulation -> metrics. Batch mode loops the
universe scan file; results land in results/<local-time>/ with params.json.

Deviations from live, all documented: H4 blocks anchor at 00:00 UTC (broker
H4 follows server midnight; user accepted the phase shift for variant-vs-
variant testing). Spread is the configured assumption (no per-bar field in
M1 data). Tick specs assume 5/3-digit quotes. Week = UTC.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant.bias import SEP_MIN_DEFAULT, h4_bias
from quant.signals import check_entry

MY_TZ = timezone(timedelta(hours=8))  # result stamps use laptop (Malaysia) time
WIN_BARS = 400  # trailing window per signal check (periods <= 50: settled)
TIME_STOP_BARS = 120


def local_stamp() -> str:
    return datetime.now(MY_TZ).strftime("%Y%m%d_%H%M%S")


def load_h1(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    need = {"time", "open", "high", "low", "close"}
    if missing := need - set(df.columns):
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    if df["time"].duplicated().any():
        raise ValueError(f"{path}: duplicate bar times")
    if not df["time"].is_monotonic_increasing:
        raise ValueError(f"{path}: bars not ascending")
    return df


def build_h4(h1: pd.DataFrame) -> pd.DataFrame:
    """Aggregate H1 to 4H blocks anchored at 00:00 UTC (see module docstring)."""
    h = h1.copy()
    h["bar"] = h["time"].dt.floor("4h")
    g = h.groupby("bar")
    h4 = pd.DataFrame({
        "time": g["time"].apply(lambda s: s.iloc[0]).values,
        "open": g["open"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
    })
    h4["time"] = pd.to_datetime(h4["time"], utc=True)
    return h4.sort_values("time").reset_index(drop=True)


def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def bias_frames(h4: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Per-H4-bar bias direction plus funnel components (same math as h4_bias)."""
    warmup = int(p.get("warmup_bars", 300))
    sep_min = float(p.get("sep_atr", SEP_MIN_DEFAULT))
    hr1 = str(p.get("hr1", "a")).lower()
    use_sep = bool(p.get("use_atr_sep", True))
    e20 = _ema(h4["close"], 20)
    e50 = _ema(h4["close"], 50)
    atr = _atr_wilder(h4["high"], h4["low"], h4["close"], 14)
    rows = []
    for i in range(len(h4)):
        if i < warmup or pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
            rows.append(("NEUTRAL", False, False))
            continue
        a, b, c = float(e20.iloc[i]), float(e50.iloc[i]), float(h4["close"].iloc[i])
        o, hi, lo = float(h4["open"].iloc[i]), float(h4["high"].iloc[i]), float(h4["low"].iloc[i])
        v = float(atr.iloc[i])
        if hr1 == "b":
            hl, hs = min(o, c) > b, max(o, c) < b
        elif hr1 == "c":
            hl, hs = lo > b, hi < b
        else:
            hl, hs = c > b, c < b
        sep = (a - b) / v
        if not use_sep:
            rows.append(("LONG" if a >= b else "SHORT", True, True))
            continue
        stacksep_l = a > b and sep >= sep_min
        stacksep_s = a < b and -sep >= sep_min
        if stacksep_l and hl:
            rows.append(("LONG", True, True))
        elif stacksep_s and hs:
            rows.append(("SHORT", True, True))
        else:
            rows.append(("NEUTRAL", stacksep_l or stacksep_s,
                         (hl and a > b) or (hs and a < b)))
    return pd.DataFrame(rows, columns=["direction", "stacksep", "hr1"])


def map_bias(h1: pd.DataFrame, h4: pd.DataFrame, bf: pd.DataFrame) -> pd.DataFrame:
    """Last fully completed H4 bar per H1 bar (H4 open + 4h <= H1 time)."""
    h4t = h4["time"].values.astype("datetime64[s]").astype("int64")
    h1t = h1["time"].values.astype("datetime64[s]").astype("int64")
    idx = h4t.searchsorted(h1t - 4 * 3600, side="right") - 1
    out = pd.DataFrame({"direction": "NEUTRAL", "stacksep": False, "hr1": False},
                       index=h1.index)
    ok = idx >= 0
    out.loc[ok, ["direction", "stacksep", "hr1"]] = bf[["direction", "stacksep", "hr1"]].values[idx[ok]]
    return out


def tick_spec(symbol: str, price: float) -> tuple[float, float] | None:
    """(tick_size, usd_per_tick_per_lot). 5/3-digit assumption; crosses unsupported."""
    pip = 0.01 if "JPY" in symbol else 0.0001
    tick = pip / 10.0
    if symbol.endswith("USD"):
        return tick, tick * 100000.0
    if symbol.startswith("USD"):
        return tick, tick * 100000.0 / price
    return None  # cross pair: needs a second feed


def scan_pair(h1: pd.DataFrame, h4: pd.DataFrame, symbol: str, p: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Entry scan. Returns (funnel_counts, candidates). Candidates hold sizing inputs."""
    bf = bias_frames(h4, p)
    assert bf["direction"].iloc[-1] == h4_bias(
        h4, float(p.get("sep_atr", SEP_MIN_DEFAULT)), str(p.get("hr1", "a")),
        bool(p.get("use_atr_sep", True)),
        min_bars=int(p.get("warmup_bars", 300))).direction  # shared-core guard
    mapped = map_bias(h1, h4, bf)
    funnel = {"scanned": 0, "stacksep": 0, "hr1": 0, "hr2": 0, "hr3": 0,
              "hr4": 0, "ext": 0, "e1setup": 0, "e1trigger": 0}
    cands = []
    t0 = max(WIN_BARS, int(p.get("warmup_bars", 300)))
    for t in range(t0, len(h1)):
        direction = mapped["direction"].iloc[t]
        if direction == "NEUTRAL":
            funnel["scanned"] += 1
            continue
        funnel["scanned"] += 1
        funnel["stacksep"] += 1
        if not mapped["hr1"].iloc[t]:
            continue
        funnel["hr1"] += 1
        win = h1.iloc[max(0, t - WIN_BARS + 1):t + 1]
        res = check_entry(win, "LONG" if direction == "LONG" else "SHORT", p)
        for key, col in (("HR2", "hr2"), ("HR3", "hr3"), ("HR4", "hr4"),
                         ("HR4-guard", "hr4"), ("EXT", "ext"),
                         ("E1-setup", "e1setup"), ("E1-trigger", "e1trigger")):
            if res["checks"].get(key):
                funnel[col] += 1
            else:
                break
        if res["signal"]:
            cands.append({"t": t, "direction": direction, "atr": res["atr"],
                          "time": h1["time"].iloc[t]})
    return pd.DataFrame([funnel]), cands


def simulate(h1: pd.DataFrame, symbol: str, cands: list[dict], p: dict,
             costs: dict, risk_usd: float, max_cost_ratio: float,
             bias_flip_exit: bool = False, weekend_flat: bool = False,
             mapped: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Walk candidates in time order; 1 open/pair and 1 entry/day enforced here."""
    tick = tick_spec(symbol, float(h1["close"].iloc[-1]))
    if tick is None:
        raise ValueError(f"{symbol}: cross pairs need a second feed for sizing")
    tick_size, tick_value = tick
    point = tick_size  # 1 point = 1 tick on 5/3-digit quotes
    spread_px = float(costs.get("spread_points", 20)) * point
    pip_size = 0.01 if "JPY" in symbol else 0.0001
    slip_px = float(costs.get("slippage_pips", 0.3)) * pip_size
    commission = float(costs.get("commission_per_lot", 0.0))
    swap_l = float(costs.get("swap_long_per_0_01", 0.0))
    swap_s = float(costs.get("swap_short_per_0_01", 0.0))
    stop_mult = float(p.get("stop_atr", 1.5))
    tp_mult = float(p.get("tp_mult", 3.0))
    be_r = float(p.get("be_trigger_r", 1.0))
    be_buf = float(p.get("be_buffer", 0))
    trail_mult = float(p.get("trail_atr", 1.5))
    atr_h1 = _atr_wilder(h1["high"], h1["low"], h1["close"], int(p.get("atr_n", 7)))
    max_stop = risk_usd / ((tick_value / tick_size) * 0.01)  # USD3 cap distance
    trades = []
    funnel_sized = 0
    open_until = -1
    last_day = None
    for cand in cands:
        t, direction = cand["t"], cand["direction"]
        if t + 1 >= len(h1) or t <= open_until:
            continue
        day = h1["time"].iloc[t].date()
        if day == last_day:
            continue
        atr_f = float(cand["atr"])
        stop_dist = stop_mult * atr_f
        if stop_dist <= 0 or stop_dist > max_stop:
            continue
        if (spread_px + slip_px) / stop_dist > max_cost_ratio:
            continue
        lots = risk_usd / ((stop_dist / tick_size) * tick_value)
        lots = int(lots // 0.01) * 0.01
        if lots < 0.01:
            continue
        funnel_sized += 1
        last_day = day
        fill = float(h1["open"].iloc[t + 1])
        long = direction == "LONG"
        entry = fill + spread_px if long else fill  # longs pay the spread
        sl = entry - stop_dist if long else entry + stop_dist
        tp = entry + tp_mult * stop_dist if long else entry - tp_mult * stop_dist
        risk_actual = (stop_dist / tick_size) * tick_value * lots
        be_on, trail_on, hh, ll = False, False, entry, entry
        held, day_open = 0, h1["time"].iloc[t + 1].date()
        swap = 0.0
        exit_row = None
        for b in range(t + 1, len(h1)):
            bar = h1.iloc[b]
            op, hi, lo, cl = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
            cur_day = bar["time"].date()
            if cur_day != day_open:  # overnight carry; triple on Wednesday night
                mult = 3.0 if cur_day.weekday() == 3 else 1.0
                swap += (swap_l if long else swap_s) * (lots / 0.01) * mult
                day_open = cur_day
            atr_now = float(atr_h1.iloc[b])
            eff_sl = sl
            if be_on:
                eff_sl = max(eff_sl, entry + be_buf) if long else min(eff_sl, entry - be_buf)
            if trail_on and atr_now > 0:
                hh, ll = max(hh, hi), min(ll, lo)
                ch = (hh if long else ll)
                trail = ch - trail_mult * atr_now if long else ch + trail_mult * atr_now
                eff_sl = max(eff_sl, trail) if long else min(eff_sl, trail)
            hit_sl = (lo <= eff_sl) if long else (hi >= eff_sl)
            hit_tp = (hi >= tp) if long else (lo <= tp)
            px, why = None, None
            if hit_sl and hit_tp:
                px, why = eff_sl, "stop"  # both inside one bar: stop first
            elif hit_sl:
                px, why = eff_sl, "stop"
            elif hit_tp:
                px, why = tp, "target"
            if px is None and bias_flip_exit and mapped is not None:
                bd = mapped["direction"].iloc[b]
                if (long and bd == "SHORT") or (not long and bd == "LONG"):
                    px, why = cl, "bias-flip"
            if px is None and held + 1 >= TIME_STOP_BARS:
                px, why = cl, "time-stop"
            if px is None and weekend_flat and b + 1 < len(h1):
                nxt = h1["time"].iloc[b + 1]
                if (nxt - bar["time"]).total_seconds() > 24 * 3600 and bar["time"].weekday() == 4:
                    px, why = cl, "weekend"
            if px is not None:
                exit_px = px - slip_px if long else px + slip_px
                pnl_ticks = ((exit_px - entry) if long else (entry - exit_px)) / tick_size
                pnl = pnl_ticks * tick_value * lots + swap - commission * lots * 2
                trades.append({"symbol": symbol, "direction": direction,
                               "entry_time": str(h1["time"].iloc[t + 1]),
                               "entry": round(entry, 5), "sl": round(sl, 5), "tp": round(tp, 5),
                               "lot": lots, "exit_time": str(bar["time"]),
                               "exit": round(exit_px, 5), "exit_type": why,
                               "pnl_usd": round(pnl, 2),
                               "pnl_R": round(pnl / risk_actual, 3) if risk_actual > 0 else 0.0,
                               "swap": round(swap, 2), "atr": round(atr_f, 5),
                               "bars_held": held + 1})
                open_until = b
                break
            held += 1
            if not be_on:
                reached = (hi >= entry + be_r * stop_dist) if long else (lo <= entry - be_r * stop_dist)
                if reached:
                    be_on, trail_on = True, True  # take effect from the next bar
        else:
            continue
    cols = ["symbol", "direction", "entry_time", "entry", "sl", "tp", "lot",
            "exit_time", "exit", "exit_type", "pnl_usd", "pnl_R", "swap", "atr", "bars_held"]
    return pd.DataFrame(trades, columns=cols), {"sized": funnel_sized}


def metrics(trades: pd.DataFrame, h1: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net_usd": 0.0, "net_R": 0.0, "expect_R": 0.0,
                "win_rate": 0.0, "profit_factor": 0.0, "max_dd": 0.0,
                "exposure_pct": 0.0, "per_month": 0.0}
    wins = trades[trades["pnl_usd"] > 0]
    gross_pos = float(wins["pnl_usd"].sum())
    gross_neg = -float(trades[trades["pnl_usd"] <= 0]["pnl_usd"].sum())
    eq = trades["pnl_usd"].cumsum()
    dd = float((eq.cummax() - eq).max())
    months = max((h1["time"].iloc[-1] - h1["time"].iloc[0]).days / 30.44, 1.0)
    held = float(trades["bars_held"].sum()) if "bars_held" in trades else 0.0
    return {"trades": n, "net_usd": round(float(trades["pnl_usd"].sum()), 2),
            "net_R": round(float(trades["pnl_R"].sum()), 2),
            "expect_R": round(float(trades["pnl_R"].mean()), 3),
            "win_rate": round(len(wins) / n, 3),
            "profit_factor": round(gross_pos / gross_neg, 3) if gross_neg > 0 else float("inf"),
            "max_dd": round(dd, 2),
            "exposure_pct": round(100.0 * held / max(len(h1), 1), 2),
            "per_month": round(n / months, 2)}


def run_pair(symbol: str, h1_path: str | Path, p: dict, costs: dict, args) -> dict:
    h1 = load_h1(h1_path)
    h4 = build_h4(h1)
    funnel, cands = scan_pair(h1, h4, symbol, p)
    mapped = map_bias(h1, h4, bias_frames(h4, p))
    trades, extra = simulate(h1, symbol, cands, p, costs, args.risk_usd,
                             args.max_cost_ratio, args.bias_flip_exit,
                             args.weekend_flat, mapped)
    funnel["sized"] = extra["sized"]
    funnel["taken"] = len(trades)
    m = metrics(trades, h1)
    m["symbol"] = symbol
    m["signals"] = len(cands)
    return {"funnel": funnel, "trades": trades, "metrics": m,
            "span": (str(h1["time"].iloc[0]), str(h1["time"].iloc[-1]))}


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description="Backtester on the shared signal core.")
    ap.add_argument("--config", default=None, help="single pair yaml")
    ap.add_argument("--data", default=None, help="single H1 csv")
    ap.add_argument("--batch", action="store_true", help="loop scan-selection.yml")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--spread-pips", type=float, default=None)
    ap.add_argument("--spread-points", type=float, default=None)
    ap.add_argument("--flat-swaps", action="store_true")
    ap.add_argument("--slippage-pips", type=float, default=None)
    ap.add_argument("--risk-usd", type=float, default=3.0)
    ap.add_argument("--max-cost-ratio", type=float, default=0.10)
    ap.add_argument("--atr-n", type=int, default=None)
    ap.add_argument("--sep-atr", type=float, default=None)
    ap.add_argument("--ma-only", action="store_true")
    ap.add_argument("--bias-flip-exit", action="store_true")
    ap.add_argument("--weekend-flat", action="store_true")
    args = ap.parse_args(argv)

    from quant.monitor import load_pairs, read_selection

    with open(Path(args.config_dir) / "_base.yaml", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    strat = dict((base.get("strategy") or {}))
    costs = dict((base.get("costs") or {}))
    if args.atr_n is not None:
        strat["atr_n"] = args.atr_n
    if args.sep_atr is not None:
        strat["sep_atr"] = args.sep_atr
    if args.ma_only:
        strat["use_atr_sep"] = False
    if args.spread_pips is not None:
        costs["spread_points"] = args.spread_pips * 10.0
    if args.spread_points is not None:
        costs["spread_points"] = args.spread_points
    if args.slippage_pips is not None:
        costs["slippage_pips"] = args.slippage_pips
    if args.flat_swaps:
        costs["swap_long_per_0_01"] = 0.0
        costs["swap_short_per_0_01"] = 0.0

    jobs: list[tuple[str, Path]] = []
    if args.batch:
        pairs = load_pairs(args.config_dir)
        selection = read_selection(args.config_dir)
        disabled = []
        for pr in pairs:
            sym = pr["symbol"]
            if selection is not None and not selection.get(sym, True):
                disabled.append(sym)
                continue
            h1_path = Path(f"data/{sym}_H1.csv")
            if not h1_path.exists():
                print(f"SKIP {sym} - no {h1_path}", flush=True)
                continue
            jobs.append((sym, h1_path))
        if disabled:
            print(f"disabled in scan-selection.yml: {', '.join(disabled)}", flush=True)
    else:
        if not args.config or not args.data:
            print("Need --config + --data, or --batch.", flush=True)
            return 2
        cfg = yaml.safe_load(open(args.config, encoding="utf-8")) or {}
        jobs.append((str(cfg.get("symbol") or Path(args.config).stem), Path(args.data)))
    if not jobs:
        print("Nothing to run.", flush=True)
        return 1

    outdir = Path(args.results_dir) / local_stamp()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "params.json").write_text(json.dumps({
        "strategy": strat, "costs": costs, "risk_usd": args.risk_usd,
        "max_cost_ratio": args.max_cost_ratio, "bias_flip_exit": args.bias_flip_exit,
        "weekend_flat": args.weekend_flat,
        "jobs": [[s, str(p)] for s, p in jobs]}, indent=1), encoding="utf-8")

    summaries, funnels = [], []
    for sym, h1_path in jobs:
        print(f"RUN {sym} <- {h1_path}", flush=True)
        try:
            res = run_pair(sym, h1_path, strat, costs, args)
        except Exception as exc:
            print(f"SKIP {sym} - {exc}", flush=True)
            continue
        f = res["funnel"]
        f["symbol"] = sym
        funnels.append(f)
        m = res["metrics"]
        summaries.append(m)
        res["trades"].to_csv(outdir / f"trades_{sym}.csv", index=False)
        print(f"DONE {sym}: trades={m['trades']} net={m['net_usd']} "
              f"expect={m['expect_R']}R pf={m['profit_factor']} dd={m['max_dd']}", flush=True)
    if summaries:
        pd.DataFrame(summaries).to_csv(outdir / "summary.csv", index=False)
    if funnels:
        pd.concat(funnels, ignore_index=True).to_csv(outdir / "funnel.csv", index=False)
    print(f"results -> {outdir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
