"""Offline backtester on the shared signal core (bias.py + signals.py). No MT5 needed.

Pipeline per pair: load H1 -> build H4 -> bias map -> entry scan (funnel) ->
sizing/cost/risk -> lifecycle simulation -> metrics. Batch mode loops the
universe scan file; results land in backtest_results/<local-time>/ with params.json.

Deviations from live, all documented: H4 blocks anchor at 00:00 UTC (broker
H4 follows server midnight; user accepted the phase shift for variant-vs-
variant testing). Spread is the configured assumption (no per-bar field in
M1 data). Tick specs assume 5/3-digit quotes. Week = UTC.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from quant.bias import SEP_MIN_DEFAULT, h4_bias
from quant.limits import md_in_ranges, parse_no_trade_ranges
from quant.signals import check_entry

MY_TZ = timezone(timedelta(hours=8))  # result stamps use laptop (Malaysia) time
WIN_BARS = 400  # trailing window per signal check (periods <= 50: settled)


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


def tick_spec(symbol: str, price: float, rates: dict[str, float] | None = None,
             ) -> tuple[float, float] | None:
    """(tick_size, usd_per_tick_per_lot). 5/3-digit assumption.

    USD-quoted reads off directly; USD-base divides by its own price; other
    quotes convert through a same-time rate (JPY via USDJPY, GBP via GBPUSD,
    AUD via AUDUSD, NZD via NZDUSD). Anything without a rate returns None.
    """
    pip = 0.01 if "JPY" in symbol else 0.0001
    tick = pip / 10.0
    quote = symbol[3:]
    rates = rates or {}
    if quote == "USD":
        return tick, tick * 100000.0
    if symbol.startswith("USD"):
        return tick, tick * 100000.0 / price  # quote is XXX: USDXXX converts itself
    # quote-foreign: feed holds XXXUSD (direct) or USDXXX (inverted) closes.
    feed = {"JPY": "USDJPY", "GBP": "GBPUSD", "AUD": "AUDUSD",
            "NZD": "NZDUSD", "CAD": "USDCAD", "CHF": "USDCHF"}.get(quote)
    fx = rates.get(feed) if feed else None
    if not fx:
        return None  # no conversion path: needs a second feed for sizing
    if quote == "JPY":
        return tick, tick * 100000.0 / fx
    usd_per_quote = 1.0 / fx if feed.startswith("USD") else fx
    return tick, tick * 100000.0 * usd_per_quote


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


def _asof(series: pd.Series | None, ts) -> float | None:
    """Last converter-feed value at or before ts."""
    if series is None or len(series) == 0:
        return None
    i = series.index.searchsorted(ts, side="right") - 1
    return float(series.iloc[i]) if i >= 0 else None


def _converter_rates(converters: dict[str, pd.Series] | None, ts) -> dict[str, float]:
    """Same-time converter closes ({USDJPY: px, ...}) for quote-foreign sizing."""
    out = {}
    for feed, series in (converters or {}).items():
        v = _asof(series, ts)
        if v is not None:
            out[feed] = v
    return out


def simulate(h1: pd.DataFrame, symbol: str, cands: list[dict], p: dict,
             costs: dict, risk_usd: float, max_cost_ratio: float,
             bias_flip_exit: bool = False, weekend_flat: bool = False,
             mapped: pd.DataFrame | None = None, lot: float | None = None,
             converters: dict[str, pd.Series] | None = None,
             m1: pd.DataFrame | None = None,
             no_trade_ranges: tuple = ()) -> tuple[pd.DataFrame, dict]:
    """Walk candidates in time order; 1 open/pair and 1 entry/day enforced here.

    lot set (e.g. 0.01) fixes size; None sizes from risk_usd. Either way the
    USD3 cap-distance skip and the cost filter still apply, and R uses actual risk.
    jpy carries USDJPY closes for JPY-cross USD conversion (None = unconvertible).
    m1, when given, is the minute feed: stop/target/BE/trail are checked row by
    row on it (tick-like); an hour with no M1 rows falls back to the H1 row.
    no_trade_ranges blocks entries whose fill day falls inside a MM-DD range.
    """
    pip_size = 0.01 if "JPY" in symbol else 0.0001
    point = pip_size / 10.0  # 1 point = 1 tick on 5/3-digit quotes
    spread_px = float(costs.get("spread_points", 20)) * point
    slip_px = float(costs.get("slippage_pips", 0.3)) * pip_size
    commission = float(costs.get("commission_per_lot", 0.0))
    swap_l = float(costs.get("swap_long_per_0_01", 0.0))
    swap_s = float(costs.get("swap_short_per_0_01", 0.0))
    stop_mult = float(p.get("stop_atr", 1.5))
    tp_mult = float(p.get("tp_mult", 3.0))
    be_r = float(p.get("be_trigger_r", 1.0))
    be_buf = float(p.get("be_buffer", 0))
    trail_r = float(p.get("trail_r", 1.0))
    use_be = bool(p.get("use_be", False))
    use_trail = bool(p.get("use_trail", True))
    # One trigger point: the BE leg (when on) fires at be_trigger_r, else the
    # trail at trail_r. Before it the position keeps its initial stop.
    act_r = be_r if use_be else trail_r
    # Minute feed as arrays, so the per-row walk never pays pandas indexing.
    m1_times = m1_open = m1_high = m1_low = m1_close = None
    if m1 is not None and len(m1):
        m1_times = m1["time"].values.astype("datetime64[s]").astype("int64")
        m1_open = m1["open"].to_numpy(float)
        m1_high = m1["high"].to_numpy(float)
        m1_low = m1["low"].to_numpy(float)
        m1_close = m1["close"].to_numpy(float)
    h1_secs = h1["time"].values.astype("datetime64[s]").astype("int64")
    trades = []
    funnel_sized = 0
    window_skips = 0
    open_until = -1
    last_day = None
    for cand in cands:
        t, direction = cand["t"], cand["direction"]
        if t + 1 >= len(h1) or t <= open_until:
            continue
        day = h1["time"].iloc[t].date()
        if day == last_day:
            continue
        if no_trade_ranges and md_in_ranges(
                h1["time"].iloc[t + 1].strftime("%m-%d"), no_trade_ranges):
            window_skips += 1  # fill day sits inside a no-trade window
            continue
        tick = tick_spec(symbol, float(h1["open"].iloc[t + 1]), _converter_rates(
            converters, h1["time"].iloc[t]))
        if tick is None:
            continue  # no USD conversion path for this bar
        tick_size, tick_value = tick
        max_stop = risk_usd / ((tick_value / tick_size) * 0.01)  # USD3 cap distance
        atr_f = float(cand["atr"])
        stop_dist = stop_mult * atr_f
        if stop_dist <= 0 or stop_dist > max_stop:
            continue
        if (spread_px + slip_px) / stop_dist > max_cost_ratio:
            continue
        lots = float(lot) if lot else risk_usd / ((stop_dist / tick_size) * tick_value)
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
        activated, hh, ll = False, entry, entry
        held, day_open = 0, h1["time"].iloc[t + 1].date()
        swap = 0.0
        exit_row = None
        for b in range(t + 1, len(h1)):
            bar = h1.iloc[b]
            op, hi, lo, cl = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
            bar_time = bar["time"]
            cur_day = bar_time.date()
            if cur_day != day_open:  # overnight carry; triple on Wednesday night
                mult = 3.0 if cur_day.weekday() == 3 else 1.0
                swap += (swap_l if long else swap_s) * (lots / 0.01) * mult
                day_open = cur_day
            # Position checks walk the minute feed (tick-like trail); an hour
            # with no M1 rows falls back to the single H1 row. Inside one row
            # the rule is unchanged: the row's extreme feeds the trail, stop
            # wins ties against target, and stop changes take effect next row.
            rows = [(None, op, hi, lo, cl)]
            if m1_times is not None:
                bt = int(h1_secs[b])
                bt -= bt % 3600  # vendor H1 stamps can be :01 (:00 minute missing); anchor at the hour edge
                i0 = int(np.searchsorted(m1_times, bt, side="left"))
                i1 = int(np.searchsorted(m1_times, bt + 3600, side="left"))
                if i1 > i0:
                    rows = [(m1_times[r], m1_open[r], m1_high[r], m1_low[r], m1_close[r])
                            for r in range(i0, i1)]
            px, why, row_when = None, None, None
            for row_t, _, row_hi, row_lo, _ in rows:
                hh, ll = max(hh, row_hi), min(ll, row_lo)  # best price since entry
                eff_sl = sl
                if activated:
                    if use_be:
                        eff_sl = max(eff_sl, entry + be_buf) if long else min(eff_sl, entry - be_buf)
                    if use_trail:
                        # T1: stop = best price - trail_r x initial risk. A level still
                        # on the loss side of entry means the trigger point is not hit.
                        level = hh - trail_r * stop_dist if long else ll + trail_r * stop_dist
                        if (long and level >= entry) or (not long and level <= entry):
                            eff_sl = max(eff_sl, level) if long else min(eff_sl, level)
                hit_sl = (row_lo <= eff_sl) if long else (row_hi >= eff_sl)
                hit_tp = (row_hi >= tp) if long else (row_lo <= tp)
                if hit_sl and hit_tp:
                    px, why, row_when = eff_sl, "stop", row_t  # both inside one row: stop first
                    break
                if hit_sl:
                    px, why, row_when = eff_sl, "stop", row_t
                    break
                if hit_tp:
                    px, why, row_when = tp, "target", row_t
                    break
                if not activated and ((row_hi >= entry + act_r * stop_dist) if long
                                      else (row_lo <= entry - act_r * stop_dist)):
                    activated = True  # stop changes take effect from the next row
            if px is None and bias_flip_exit and mapped is not None:
                bd = mapped["direction"].iloc[b]
                if (long and bd == "SHORT") or (not long and bd == "LONG"):
                    px, why = cl, "bias-flip"
            if px is None and weekend_flat and b + 1 < len(h1):
                nxt = h1["time"].iloc[b + 1]
                if (nxt - bar_time).total_seconds() > 24 * 3600 and bar_time.weekday() == 4:
                    px, why = cl, "weekend"
            if px is not None:
                # Same fixed spread both sides: longs paid it entering, shorts pay it
                # here (buy back on the ask).
                exit_px = px - slip_px if long else px + slip_px + spread_px
                pnl_ticks = ((exit_px - entry) if long else (entry - exit_px)) / tick_size
                pnl = pnl_ticks * tick_value * lots + swap - commission * lots * 2
                exit_time = (str(pd.Timestamp(row_when, unit="s", tz="UTC"))
                             if row_when is not None else str(bar_time))
                trades.append({"symbol": symbol, "direction": direction,
                               "entry_time": str(h1["time"].iloc[t + 1]),
                               "entry": round(entry, 5), "sl": round(sl, 5), "tp": round(tp, 5),
                               "lot": lots, "exit_time": exit_time,
                               "exit": round(exit_px, 5), "exit_type": why,
                               "pnl_usd": round(pnl, 2),
                               "pnl_R": round(pnl / risk_actual, 3) if risk_actual > 0 else 0.0,
                               "swap": round(swap, 2), "atr": round(atr_f, 5),
                               "bars_held": held + 1})
                open_until = b
                break
            held += 1
        else:
            continue
    cols = ["symbol", "direction", "entry_time", "entry", "sl", "tp", "lot",
            "exit_time", "exit", "exit_type", "pnl_usd", "pnl_R", "swap", "atr", "bars_held"]
    return pd.DataFrame(trades, columns=cols), {"sized": funnel_sized, "window": window_skips}


def metrics(trades: pd.DataFrame, months_days: float, n_bars: int) -> dict:
    """Per-pair stats. months_days (data span) and n_bars give the per-month and
    exposure denominators, so a filtered trade list can be re-scored later."""
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
    months = max(months_days / 30.44, 1.0)
    held = float(trades["bars_held"].sum()) if "bars_held" in trades else 0.0
    return {"trades": n, "net_usd": round(float(trades["pnl_usd"].sum()), 2),
            "net_R": round(float(trades["pnl_R"].sum()), 2),
            "expect_R": round(float(trades["pnl_R"].mean()), 3),
            "win_rate": round(len(wins) / n, 3),
            "profit_factor": round(gross_pos / gross_neg, 3) if gross_neg > 0 else float("inf"),
            "max_dd": round(dd, 2),
            "exposure_pct": round(100.0 * held / max(n_bars, 1), 2),
            "per_month": round(n / months, 2)}


def yearly_table(trades: pd.DataFrame) -> pd.DataFrame:
    """Trades, net USD and net R per symbol-year (exit year)."""
    if len(trades) == 0:
        return pd.DataFrame(columns=["symbol", "year", "trades", "net_usd", "net_R"])
    t = trades.copy()
    t["year"] = pd.to_datetime(t["exit_time"], utc=True).dt.year
    g = t.groupby(["symbol", "year"])
    return pd.DataFrame({"symbol": [k[0] for k in g.groups],
                         "year": [k[1] for k in g.groups],
                         "trades": g.size().values,
                         "net_usd": g["pnl_usd"].sum().round(2).values,
                         "net_R": g["pnl_R"].sum().round(2).values,
                         }).sort_values(["symbol", "year"]).reset_index(drop=True)


def total_row(all_trades: pd.DataFrame) -> dict:
    """Portfolio TOTAL across pairs, time-ordered by exit (weights concurrent risk)."""
    t = all_trades.sort_values("exit_time").reset_index(drop=True)
    n = len(t)
    wins = t[t["pnl_usd"] > 0]
    gross_pos = float(wins["pnl_usd"].sum())
    gross_neg = -float(t[t["pnl_usd"] <= 0]["pnl_usd"].sum())
    eq = t["pnl_usd"].cumsum()
    return {"symbol": "TOTAL", "trades": n,
            "net_usd": round(float(t["pnl_usd"].sum()), 2),
            "net_R": round(float(t["pnl_R"].sum()), 2),
            "expect_R": round(float(t["pnl_R"].mean()), 3),
            "win_rate": round(len(wins) / n, 3),
            "profit_factor": round(gross_pos / gross_neg, 3) if gross_neg > 0 else float("inf"),
            "max_dd": round(float((eq.cummax() - eq).max()), 2)}


def _m1_path(h1_path: str | Path) -> Path:
    """data/<SYM>_H1.csv -> sibling data/<SYM>_M1.csv (same directory)."""
    p = Path(h1_path)
    return p.with_name(p.stem.replace("_H1", "_M1") + ".csv")


def _load_m1(h1_path: str | Path, symbol: str) -> pd.DataFrame | None:
    """Minute feed for tick-like position checks; None -> H1 checks per bar."""
    m1p = _m1_path(h1_path)
    if not m1p.exists():
        return None
    try:
        m1 = load_h1(m1p)
    except Exception as exc:  # corrupt/garbled file must not kill the run
        print(f"warn {symbol}: {m1p.name} unreadable ({exc}); H1 checks", flush=True)
        return None
    return m1 if len(m1) else None


def run_pair(symbol: str, h1_path: str | Path, p: dict, costs: dict, args,
             converters: dict[str, pd.Series] | None = None) -> dict:
    h1 = load_h1(h1_path)
    h4 = build_h4(h1)
    funnel, cands = scan_pair(h1, h4, symbol, p)
    mapped = map_bias(h1, h4, bias_frames(h4, p))
    m1 = None
    if str(getattr(args, "position_checks", "M1")).upper() == "M1":
        m1 = _load_m1(h1_path, symbol)
    ranges = tuple(getattr(args, "no_trade_ranges", ()) or ())
    trades, extra = simulate(h1, symbol, cands, p, costs, args.risk_usd,
                             args.max_cost_ratio,
                             bias_flip_exit=bool(p.get("bias_flip_exit", False)),
                             weekend_flat=bool(p.get("weekend_flat", False)),
                             mapped=mapped, lot=args.lot, converters=converters,
                             m1=m1, no_trade_ranges=ranges)
    funnel["sized"] = extra["sized"]
    funnel["window"] = extra.get("window", 0)
    funnel["taken"] = len(trades)
    days = (h1["time"].iloc[-1] - h1["time"].iloc[0]).days
    m = metrics(trades, days, len(h1))
    m["symbol"] = symbol
    m["signals"] = len(cands)
    return {"funnel": funnel, "trades": trades, "metrics": m, "n_bars": len(h1),
            "span_days": days,
            "span": (str(h1["time"].iloc[0]), str(h1["time"].iloc[-1]))}


def resolve_workers(requested: int, n_pairs: int) -> int:
    """1 = linear, 0 = all cores; always capped at the pair count."""
    n = (os.cpu_count() or 1) if requested == 0 else requested
    return max(1, min(n, n_pairs))


def _worker_init() -> None:
    # One BLAS/OpenMP thread per worker, or parallel pairs fight over cores.
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        os.environ[var] = "1"


def _run_one(symbol, h1_path, p, costs, args, converters) -> dict:
    return run_pair(symbol, h1_path, p, costs, args, converters=converters)


def _done_line(sym: str, m: dict) -> str:
    return (f"DONE {sym}: trades={m['trades']} net={m['net_usd']} "
            f"expect={m['expect_R']}R pf={m['profit_factor']} dd={m['max_dd']}")


def run_all(jobs: list[tuple[str, Path]], p: dict, costs: dict, args, converters,
            workers: int) -> tuple[dict[str, dict], dict[str, str]]:
    """Run every pair. One pair never splits across processes. Returns (results, failures)."""
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    if workers <= 1:
        for sym, h1_path in jobs:
            print(f"RUN {sym} <- {h1_path}", flush=True)
            try:
                results[sym] = _run_one(sym, h1_path, p, costs, args, converters)
            except Exception as exc:
                failures[sym] = str(exc)
                print(f"SKIP {sym} - {exc}", flush=True)
                continue
            print(_done_line(sym, results[sym]["metrics"]), flush=True)
        return results, failures
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as pool:
        futures = {}
        for sym, h1_path in jobs:
            print(f"RUN {sym} <- {h1_path}", flush=True)
            futures[pool.submit(_run_one, sym, h1_path, p, costs, args, converters)] = sym
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                results[sym] = fut.result()
            except Exception as exc:  # one bad pair must not lose the others
                failures[sym] = str(exc)
                print(f"SKIP {sym} - {exc}", flush=True)
                continue
            print(_done_line(sym, results[sym]["metrics"]), flush=True)
    return results, failures


def apply_daily_cap(trades_by_sym: dict[str, pd.DataFrame],
                    limit: int) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Portfolio-wide cap: at most `limit` entries per calendar day, all pairs.

    Deterministic post-filter over taken trades. Per day the earliest entries
    (entry_time, then symbol) stay; the rest drop. A dropped pair is not
    re-filled later that day, which is conservative.
    """
    frames = [t for t in trades_by_sym.values() if len(t)]
    if limit <= 0 or not frames:
        return trades_by_sym, []
    df = pd.concat(frames, ignore_index=True)
    day = df["entry_time"].astype(str).str.slice(0, 10)
    drop_idx: list[int] = []
    for _, day_df in df.groupby(day, sort=True):
        if len(day_df) > limit:
            drop_idx += list(day_df.sort_values(["entry_time", "symbol"]).index[limit:])
    if not drop_idx:
        return trades_by_sym, []
    dropped = df.loc[drop_idx, ["symbol", "entry_time"]].to_dict("records")
    drops: dict[str, set[str]] = {}
    for row in dropped:
        drops.setdefault(row["symbol"], set()).add(str(row["entry_time"]))
    out = {sym: t[~t["entry_time"].astype(str).isin(drops.get(sym, set()))].reset_index(drop=True)
           for sym, t in trades_by_sym.items()}
    return out, dropped


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description="Backtester on the shared signal core.")
    ap.add_argument("--config", default=None, help="single pair yaml")
    ap.add_argument("--data", default=None, help="single H1 csv")
    ap.add_argument("--batch", action="store_true", help="loop scan-selection.yml")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--results-dir", default="backtest_results")
    ap.add_argument("--spread-pips", type=float, default=None)
    ap.add_argument("--spread-points", type=float, default=None)
    ap.add_argument("--flat-swaps", action="store_true")
    ap.add_argument("--slippage-pips", type=float, default=None)
    ap.add_argument("--risk-usd", type=float, default=3.0)
    ap.add_argument("--lot", type=float, default=0.01,
                    help="fixed lot size; <=0 sizes from --risk-usd instead")
    ap.add_argument("--max-cost-ratio", type=float, default=0.10)
    ap.add_argument("--atr-n", type=int, default=None)
    ap.add_argument("--sep-atr", type=float, default=None)
    ap.add_argument("--ma-only", action="store_true")
    ap.add_argument("--bias-flip-exit", action="store_true")
    ap.add_argument("--weekend-flat", action="store_true")
    ap.add_argument("--jobs", type=int, default=10,
                    help="pairs run in parallel (capped at pair count); 1 = linear, 0 = all cores")
    args = ap.parse_args(argv)
    if args.jobs < 0:
        ap.error("--jobs must be >= 0")

    from quant.monitor import flatten_strategy, load_pairs, read_selection

    with open(Path(args.config_dir) / "_base.yaml", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    strat = flatten_strategy(base)
    costs = dict((base.get("costs") or {}))
    max_day = int((base.get("limits") or {}).get("max_trades_per_day", 0) or 0)
    try:
        args.no_trade_ranges = tuple(parse_no_trade_ranges(base))
    except ValueError as exc:
        print(f"config error: {exc}", flush=True)
        return 2
    # Stop/target/BE/trail checks read the minute feed when the config says M1.
    args.position_checks = str((base.get("timeframes") or {}).get(
        "position_checks", "M1")).upper()
    if args.bias_flip_exit:
        strat["bias_flip_exit"] = True  # CLI flag forces on; config holds the default
    if args.weekend_flat:
        strat["weekend_flat"] = True
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

    # Quote-foreign pairs convert through a converter feed (JPY via USDJPY,
    # GBP via GBPUSD, ...). USD-quoted and USD-base pairs convert themselves.
    conv_map = {"JPY": "USDJPY", "GBP": "GBPUSD", "AUD": "AUDUSD",
                "NZD": "NZDUSD", "CAD": "USDCAD", "CHF": "USDCHF"}
    need: dict[str, list[str]] = {}
    for s, _ in jobs:
        if s[3:] == "USD" or s.startswith("USD"):
            continue
        feed = conv_map.get(s[3:])
        if feed:
            need.setdefault(feed, []).append(s)
        else:
            print(f"SKIP {s} - no converter feed for quote {s[3:]}", flush=True)
    jobs = [(s, p) for s, p in jobs if s[3:] == "USD" or s.startswith("USD")
            or s in [x for v in need.values() for x in v]]
    converters: dict[str, pd.Series] = {}
    for feed, syms in need.items():
        fp = Path(f"data/{feed}_H1.csv")
        if not fp.exists():
            for s in syms:
                print(f"SKIP {s} - no {feed} converter feed", flush=True)
            jobs = [(s, p) for s, p in jobs if s not in syms]
            continue
        converters[feed] = load_h1(fp).set_index("time")["close"]
    if not jobs:
        print("Nothing to run.", flush=True)
        return 1

    outdir = Path(args.results_dir) / local_stamp()
    outdir.mkdir(parents=True, exist_ok=True)
    workers = resolve_workers(args.jobs, len(jobs))
    params = {
        "strategy": strat, "costs": costs, "risk_usd": args.risk_usd,
        "max_cost_ratio": args.max_cost_ratio, "lot": args.lot,
        "max_trades_per_day": max_day, "workers": workers,
        "no_trade_ranges": args.no_trade_ranges,
        "position_checks": args.position_checks,
        "jobs": [[s, str(p)] for s, p in jobs]}
    params_path = outdir / "params.json"
    params_path.write_text(json.dumps(params, indent=1), encoding="utf-8")

    print(f"running {len(jobs)} pair(s) on {workers} worker(s)", flush=True)
    results, failures = run_all(jobs, strat, costs, args, converters, workers)
    dropped: list[dict] = []
    if max_day > 0 and results:
        capped, dropped = apply_daily_cap({s: r["trades"] for s, r in results.items()}, max_day)
        for sym, kept in capped.items():
            if len(kept) == len(results[sym]["trades"]):
                continue
            res = results[sym]
            res["trades"] = kept
            m = metrics(kept, res["span_days"], res["n_bars"])
            m["symbol"], m["signals"] = sym, res["metrics"]["signals"]
            res["metrics"] = m
            res["funnel"]["taken"] = len(kept)
        if dropped:
            print(f"day-cap {max_day}/day: dropped {len(dropped)} late same-day entries "
                  f"({', '.join(sorted({d['symbol'] for d in dropped}))})", flush=True)
    if failures or dropped:
        params["failed"] = failures
        params["daily_cap_dropped"] = dropped
        params_path.write_text(json.dumps(params, indent=1), encoding="utf-8")

    summaries, funnels, yearlies, all_trades = [], [], [], []
    for sym, _ in jobs:  # input order, so output files do not depend on finish order
        res = results.get(sym)
        if res is None:
            continue
        f = res["funnel"]
        f["symbol"] = sym
        funnels.append(f)
        summaries.append(res["metrics"])
        res["trades"].to_csv(outdir / f"trades_{sym}.csv", index=False)
        yearlies.append(yearly_table(res["trades"]))
        if len(res["trades"]):
            all_trades.append(res["trades"])
    if failures:
        print(f"FAILED: {', '.join(failures)}", flush=True)
    if summaries:
        if all_trades:
            summaries.append(total_row(pd.concat(all_trades, ignore_index=True)))
        pd.DataFrame(summaries).to_csv(outdir / "summary.csv", index=False)
    if funnels:
        pd.concat(funnels, ignore_index=True).to_csv(outdir / "funnel.csv", index=False)
    if yearlies:
        pd.concat(yearlies, ignore_index=True).to_csv(outdir / "yearly.csv", index=False)
    print(f"backtest results -> {outdir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
