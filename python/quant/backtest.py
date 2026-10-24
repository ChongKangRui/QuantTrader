"""Offline backtester on the shared signal core (bias.py + signals.py). No MT5 needed.

Pipeline per pair: load H1 -> build the H1/H4 grid or load broker H4/D1 bars
for the H4/D1 variant -> bias map ->
entry scan (funnel) -> sizing/cost/risk -> lifecycle simulation -> metrics.
Batch mode loops the universe scan file; results land in
backtest_results/<local-time>/ with params.json and an exact config.yaml snapshot.

Deviations from live: the legacy H1/H4 grid anchors at 00:00 UTC;
H4/D1 uses broker CSVs. Spread is the configured assumption (no per-bar
field in M1 data). Tick specs assume 5/3-digit quotes. Week = UTC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from quant.bias import SEP_MIN_DEFAULT, bias_periods, h4_bias
from quant.limits import md_in_ranges, parse_no_trade_ranges, read_entry_hours, entry_time_allowed
from quant.rules import (combine_stop, cost_ok, size_stop_to_scope, scaled_lots,
                         scope_lots, step_risk as _step_risk,
                         stop_sizing_conflict, read_sizing)
from quant.signals import check_entry, crossover_signals, validate_crossover, opposite_crossover

_YAML_COMMENT = re.compile(r"^\s*([A-Za-z_][\w]*)\s*:.*#\s*(.+?)\s*$")


def yaml_notes(path) -> dict:
    """Flat {yaml_key: inline comment} map from a config file (best effort).

    Lets params.json carry the same one-line meaning the yaml shows, so a run
    folder stays readable without opening the yaml. Full-line comments and
    values without comments are skipped; only unique leaf key names map.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    notes: dict[str, str] = {}
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        m = _YAML_COMMENT.match(line)
        if m:
            notes[m.group(1)] = m.group(2).strip()
    return notes

MY_TZ = timezone(timedelta(hours=8))  # result stamps use laptop (Malaysia) time
WIN_BARS = 400  # trailing window per signal check (periods <= 50: settled)
SIMULATION_TIMING = "position_accounting_v3"  # Separate corrected check-time costs/exposure from old runs.


def local_stamp() -> str:
    return datetime.now(MY_TZ).strftime("%Y%m%d_%H%M%S")


def backtest_run_name(execution: str, regime: str) -> str:
    """Name a run from its validated chart roles, bias first and execution second."""
    # Use D in folder names only; saved timeframe settings still retain D1.
    bias_label = "D" if regime == "D1" else regime
    return f"{local_stamp()}_{bias_label}_{execution}"


def add_profit_factor_suffix(run_dir: Path, profit_factor: float | None) -> Path:
    """Label this new run before comparison, report and ledger save its final name."""
    label = (f"{profit_factor:.2f}" if profit_factor is not None
             and profit_factor >= 0 else "NA")
    destination = run_dir.with_name(f"{run_dir.name}_PF{label}")
    try:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to overwrite {destination}")
        run_dir.rename(destination)
    except OSError as exc:
        print(f"profit-factor folder suffix skipped: {exc}", flush=True)
        return run_dir
    return destination


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


def build_htf(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Aggregate base bars into `hours` blocks anchored at 00:00 UTC (module
    docstring). H4 = build_htf(h1, 4); D1 = build_htf(h1, 24)."""
    h = df.copy()
    h["bar"] = h["time"].dt.floor(f"{hours}h")
    g = h.groupby("bar")
    out = pd.DataFrame({
        "time": g["time"].apply(lambda s: s.iloc[0]).values,
        "open": g["open"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
    })
    out["time"] = pd.to_datetime(out["time"], utc=True)
    return out.sort_values("time").reset_index(drop=True)


def build_h4(h1: pd.DataFrame) -> pd.DataFrame:
    """4H blocks — the default regime grid (H4->D1 variant builds via build_htf)."""
    return build_htf(h1, 4)


def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def read_evaluation_window(base: dict, *, enabled=None, start=None, end=None) -> dict:
    """Optional offline boundaries; preparation prices never become earlier trades."""
    cfg = base.get("backtest_evaluation") or {}
    if not isinstance(cfg, dict):
        raise ValueError("backtest_evaluation must be a mapping")
    on = cfg.get("enabled", False) if enabled is None else enabled
    if enabled is None and (start is not None or end is not None):
        on = True
    preparation = cfg.get("require_preparation", True)
    if not isinstance(on, bool) or not isinstance(preparation, bool):
        raise ValueError("evaluation enabled/require_preparation must be true or false")
    if not on:
        return {"enabled": False}
    first = start if start is not None else cfg.get("start")
    last = end if end is not None else cfg.get("end")
    if first is None or last is None:
        raise ValueError("enabled evaluation requires start and exclusive end")
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    if pd.isna(first) or pd.isna(last):
        raise ValueError("evaluation dates cannot be NaT")
    first = first.tz_localize("UTC") if first.tzinfo is None else first.tz_convert("UTC")
    last = last.tz_localize("UTC") if last.tzinfo is None else last.tz_convert("UTC")
    if first >= last:
        raise ValueError("evaluation start must be before exclusive end")
    return {"enabled": True, "start": first.isoformat(), "end": last.isoformat(),
            "require_preparation": preparation}


def evaluation_tape(frame: pd.DataFrame, window: dict | None, bar_hours: int) -> pd.DataFrame:
    """Retain preparation, but never let a candle beyond the end affect a trade."""
    if not (window or {}).get("enabled"):
        return frame
    end = pd.Timestamp(window["end"])
    out = frame.loc[frame["time"] < end].reset_index(drop=True)
    if out.empty or not (out["time"] >= pd.Timestamp(window["start"])).any():
        raise ValueError("no execution candles in evaluation window")
    if (out["time"] + pd.Timedelta(hours=bar_hours) > end).any():
        raise ValueError("evaluation end cuts an execution candle; choose a broker candle boundary")
    return out


def validate_preparation(execution: pd.DataFrame, regime: pd.DataFrame, p: dict,
                         window: dict | None) -> None:
    if not (window or {}).get("enabled") or not window.get("require_preparation", True):
        return
    start = pd.Timestamp(window["start"])
    for name, frame in (("execution", execution), ("regime", regime)):
        # A following broker open proves closure; a forming prefix candle cannot count.
        count = int(((frame["time"] < start) & (frame["time"].shift(-1) <= start)).sum())
        if count < int(p.get("warmup_bars", 300)):
            raise ValueError(f"insufficient closed {name} preparation candles before evaluation start")


def candidate_in_evaluation(frame: pd.DataFrame, t: int, window: dict | None) -> bool:
    if not (window or {}).get("enabled"):
        return True
    return (0 <= t + 1 < len(frame)
            and pd.Timestamp(window["start"]) <= frame["time"].iloc[t + 1] < pd.Timestamp(window["end"]))


def evaluation_equity(curve: pd.DataFrame, window: dict, account_usd: float) -> pd.DataFrame:
    if not window.get("enabled"):
        return curve
    start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
    times = pd.to_datetime(curve["time"], utc=True)
    curve = curve[(times >= start) & (times <= end)]
    # The starting account must count even if the first fill immediately pays costs.
    baseline = pd.DataFrame([{"time": start, "usd": account_usd}])
    return pd.concat([baseline, curve], ignore_index=True).sort_values("time", kind="stable")


def bias_frames(h4: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Per-regime-bar bias direction plus funnel components (same math as h4_bias)."""
    warmup = int(p.get("warmup_bars", 300))
    sep_min = float(p.get("sep_atr", SEP_MIN_DEFAULT))
    hr1 = str(p.get("hr1", "a")).lower()
    use_sep = bool(p.get("use_atr_sep", True))
    e_fast_n, e_slow_n, atr_n = bias_periods(p)
    e_fast = _ema(h4["close"], e_fast_n)
    e_slow = _ema(h4["close"], e_slow_n)
    atr = _atr_wilder(h4["high"], h4["low"], h4["close"], atr_n)
    rows = []
    for i in range(len(h4)):
        if i < warmup or pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
            rows.append(("NEUTRAL", False, False))
            continue
        a, b, c = float(e_fast.iloc[i]), float(e_slow.iloc[i]), float(h4["close"].iloc[i])
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


def map_bias(h1: pd.DataFrame, h4: pd.DataFrame, bf: pd.DataFrame,
             reg_hours: int = 4, exec_hours: int = 0,
             broker_bars: bool = False) -> pd.DataFrame:
    """Last completed regime bar as of the execution bar's signal close.

    For broker bars, the next regime bar's open proves the previous bar closed.
    exec_hours=0 keeps the old start-of-bar mapping for direct callers.
    """
    h4t = h4["time"].values.astype("datetime64[s]").astype("int64")
    h1t = h1["time"].values.astype("datetime64[s]").astype("int64")
    if exec_hours > 0 and exec_hours == reg_hours:
        # Both decisions use this same closed candle, never a later candle across a gap.
        idx = pd.Index(h4t).get_indexer(h1t)
    elif broker_bars:
        # Sunday and holiday broker bars may be shorter than 24 hours.
        completed = h4t[1:]
        idx = completed.searchsorted(h1t + exec_hours * 3600, side="right") - 1
    else:
        idx = h4t.searchsorted(h1t + (exec_hours - reg_hours) * 3600,
                               side="right") - 1
    out = pd.DataFrame({"direction": "NEUTRAL", "stacksep": False, "hr1": False},
                       index=h1.index)
    ok = idx >= 0
    if ok.any():
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
    if not fx or not np.isfinite(fx) or fx <= 0:
        return None  # no conversion path: needs a second feed for sizing
    if quote == "JPY":
        return tick, tick * 100000.0 / fx
    usd_per_quote = 1.0 / fx if feed.startswith("USD") else fx
    return tick, tick * 100000.0 * usd_per_quote


def scan_pair(h1: pd.DataFrame, h4: pd.DataFrame, symbol: str, p: dict,
               reg_hours: int = 4, exec_hours: int = 0,
              broker_bars: bool = False, evaluation_window: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Entry scan. Returns (funnel_counts, candidates). Candidates hold sizing inputs."""
    bf = bias_frames(h4, p)
    # shared-core guard: the frame math and the single-bar core must agree,
    # including the same configured bias periods
    bias_fast, bias_slow, bias_atr = bias_periods(p)
    assert bf["direction"].iloc[-1] == h4_bias(
        h4, float(p.get("sep_atr", SEP_MIN_DEFAULT)), str(p.get("hr1", "a")),
        bool(p.get("use_atr_sep", True)), min_bars=int(p.get("warmup_bars", 300)),
        ema_fast=bias_fast, ema_slow=bias_slow,
        atr_n=bias_atr).direction  # shared-core guard
    mapped = map_bias(h1, h4, bf, reg_hours=reg_hours, exec_hours=exec_hours,
                      broker_bars=broker_bars)
    funnel = {"scanned": 0, "stacksep": 0, "hr1": 0, "hr2": 0, "hr3": 0,
              "hr4": 0, "ext": 0, "w1": 0, "e1setup": 0, "e1trigger": 0}
    cands = []
    crossover = validate_crossover(p)
    cross_records = crossover_signals(h1, p)[0] if crossover else None
    t0 = max(1 if crossover else WIN_BARS, int(p.get("warmup_bars", 300)))
    for t in range(t0, len(h1)):
        if not candidate_in_evaluation(h1, t, evaluation_window):
            continue
        direction = mapped["direction"].iloc[t]
        if direction == "NEUTRAL":
            funnel["scanned"] += 1
            continue
        funnel["scanned"] += 1
        funnel["stacksep"] += 1
        if not mapped["hr1"].iloc[t]:
            continue
        funnel["hr1"] += 1
        if crossover:
            record = cross_records[t]
            signal = record["signal"] and direction == record["direction"]
            res = {**record, "signal": signal,
                   "checks": {code: signal for code in ("HR2", "HR3", "HR4", "HR4-guard",
                                                         "EXT", "W1", "E1-setup", "E1-trigger")}}
        else:
            win = h1.iloc[max(0, t - WIN_BARS + 1):t + 1]
            res = check_entry(win, "LONG" if direction == "LONG" else "SHORT", p)
        for key, col in (("HR2", "hr2"), ("HR3", "hr3"), ("HR4", "hr4"),
                         ("HR4-guard", "hr4"), ("EXT", "ext"), ("W1", "w1"),
                         ("E1-setup", "e1setup"), ("E1-trigger", "e1trigger")):
            if res["checks"].get(key):
                funnel[col] += 1
            else:
                break
        if res["signal"]:
            cands.append({"t": t, "direction": direction, "atr": res["atr"],
                            "time": h1["time"].iloc[t],
                            "entry_reason": res.get("entry_reason", "unknown")})
            if crossover:
                cands[-1]["crossover_time"] = res["crossover_time"]
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


def _bar_durations(open_seconds: np.ndarray, bar_hours: int) -> np.ndarray:
    """Observed execution intervals; exclude gaps and clip short broker sessions."""
    ends = open_seconds + bar_hours * 3600
    ends[:-1] = np.minimum(ends[:-1], open_seconds[1:])
    return ends - open_seconds


def simulate(h1: pd.DataFrame, symbol: str, cands: list[dict], p: dict,
             costs: dict, risk_usd: float, max_cost_ratio: float,
             bias_flip_exit: bool = False, weekend_flat: bool = False,
             mapped: pd.DataFrame | None = None, lot: float | None = None,
             converters: dict[str, pd.Series] | None = None,
             m1: pd.DataFrame | None = None,
             no_trade_ranges: tuple = (), *,
             scope_low: float = 0.0, scope_high: float = 0.0,
             bar_hours: int = 1, stop_sizing: dict | None = None,
               default_lot: float | None = None, coarse_exit_at_close: bool = False,
                entry_hours: dict | None = None, independent_candidates: bool = False,
                 position_bars: pd.DataFrame | None = None, position_hours: int = 1,
                 evaluation_window: dict | None = None
             ) -> tuple[pd.DataFrame, dict]:
    """Simulate candidate lifecycles; independent mode defers admission to the portfolio.

    Sizing: start at default_lot and add 0.01 lots until actual 1R reaches
    scope_low; the trade is refused when that lot
    overshoots scope_high or when the base lot already risks more than
    scope_high. A fixed `lot` is a diagnostic override and still must land
    inside [scope_low, scope_high]. With the scope off and no fixed lot, the
    explicit base is used; old callers without one retain legacy risk_usd
    target sizing. R uses actual risk in either mode.
    stop_sizing (risk.stop_sizing in _base.yaml) swaps that: with
    widen_stop_to_scope on, the lot is FIXED and the stop (and with it the
    target) is widened until that lot risks scope_low, refused when the
    widening needs more than max_stop_atr x ATR.
    jpy carries USDJPY closes for JPY-cross USD conversion (None = unconvertible).
    m1, when given, is the minute feed: stop/target/BE/trail are checked row by
    row on it (tick-like); an execution bar with no M1 rows falls back to that
    bar's own OHLC row. bar_hours is the execution grid's bar size (H4->D1 = 4).
    Range-based exits book at check-row close. coarse_exit_at_close is retained
    for caller compatibility; false no longer permits early outcome booking.
    no_trade_ranges blocks entries whose fill day falls inside a MM-DD range.
    position_bars supplies explicit broker H1 checks instead of M1. Missing
    execution intervals fail; hourly extremes only change the next hour's stop.
    """
    h1 = evaluation_tape(h1, evaluation_window, bar_hours)
    if mapped is not None:
        mapped = mapped.iloc[:len(h1)]
    hours = read_entry_hours({"entry_hours": entry_hours} if entry_hours is not None else {})
    validate_crossover(p)
    exit_crosses = crossover_signals(h1, p)[0] if p.get("use_crossover_exit", False) else None
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
    be_buf = float(p.get("be_buffer", 0)) * pip_size
    trail_r = float(p.get("trail_r", 1.0))
    use_be = bool(p.get("use_be", False))
    use_trail = bool(p.get("use_trail", True))
    # One trigger point: the BE leg (when on) fires at be_trigger_r, else the
    # trail at trail_r. Before it the position keeps its initial stop.
    act_r = be_r if use_be else trail_r
    # Check feed as arrays, so minute/hourly walks avoid pandas indexing per row.
    m1_times = m1_open = m1_high = m1_low = m1_close = None
    if position_bars is not None and m1 is not None:
        raise ValueError("choose broker position bars or M1, not both")
    check_feed = position_bars if position_bars is not None else m1
    check_seconds = position_hours * 3600 if position_bars is not None else 60
    if position_bars is not None and position_bars.empty:
        raise ValueError(f"{symbol}: required broker H1 position checks are empty")
    if check_feed is not None and len(check_feed):
        m1_times = check_feed["time"].values.astype("datetime64[s]").astype("int64")
        m1_open = check_feed["open"].to_numpy(float)
        m1_high = check_feed["high"].to_numpy(float)
        m1_low = check_feed["low"].to_numpy(float)
        m1_close = check_feed["close"].to_numpy(float)
    h1_secs = h1["time"].values.astype("datetime64[s]").astype("int64")
    durations = _bar_durations(h1_secs, bar_hours)
    elapsed = np.r_[0, np.cumsum(durations)]
    trades = []
    funnel_sized = 0
    window_skips = 0
    hours_skips = 0
    # named gates so the funnel never hides WHY candidates die (the old "sized" lump)
    open_skips = day_skips = tick_skips = scope_skips = cost_skips = lot_skips = 0
    stop_cap_skips = 0
    lot_fallbacks = 0
    open_until = -1
    last_day = None
    for cand in cands:
        t, direction = cand["t"], cand["direction"]
        if not candidate_in_evaluation(h1, t, evaluation_window):
            continue  # Preparation candidates consume no sizing, position or quota state.
        if t + 1 >= len(h1) or (not independent_candidates and t <= open_until):
            open_skips += 1  # a position is still open or bars overlap
            continue
        if not entry_time_allowed(h1["time"].iloc[t + 1], hours):
            hours_skips += 1
            continue
        # A boundary fill belongs to its trading day, not the preparation signal day.
        day_index = t + 1 if (evaluation_window or {}).get("enabled") else t
        day = h1["time"].iloc[day_index].date()
        if not independent_candidates and day == last_day:
            day_skips += 1  # one entry per pair per day
            continue
        if no_trade_ranges and md_in_ranges(
                h1["time"].iloc[t + 1].strftime("%m-%d"), no_trade_ranges):
            window_skips += 1  # fill day sits inside a no-trade window
            continue
        tick = tick_spec(symbol, float(h1["open"].iloc[t + 1]), _converter_rates(
            converters, h1["time"].iloc[t + 1]))
        if tick is None:
            tick_skips += 1  # no USD conversion path for this bar
            continue
        tick_size, tick_value = tick
        atr_f = float(cand["atr"])
        stop_dist = stop_mult * atr_f
        lots = 0.0
        lot_fallback = False
        # Widen first; optional lot fallback keeps the original strategy stop.
        widen = bool((stop_sizing or {}).get("widen_stop_to_scope"))
        if widen:
            fixed_lot = float(lot or (default_lot if default_lot is not None
                                     else (stop_sizing or {}).get("fixed_lot", 0.01)))
            stop_dist, lots, why, lot_fallback = size_stop_to_scope(
                stop_dist, atr_f, tick_size, tick_value, scope_low, scope_high,
                fixed_lot, float((stop_sizing or {}).get("max_stop_atr") or 0.0),
                bool((stop_sizing or {}).get("increase_lots_if_widening_fails")))
            if why == "stop-cap":
                stop_cap_skips += 1  # the needed stop is too far from price
                continue
            if why == "scope":
                scope_skips += 1
                continue
            if lots < 0.01:
                lot_skips += 1  # below the broker minimum lot
                continue
        # shared core: the live trader runs the identical math (quant/rules.py)
        if stop_dist <= spread_px or not cost_ok(stop_dist, spread_px, slip_px, max_cost_ratio):
            cost_skips += 1  # round-trip cost too large vs the stop distance
            continue
        if not widen:
            lots, _risk_fixed, why = scope_lots(
                _step_risk(stop_dist, tick_size, tick_value),
                scope_low, scope_high, fixed_lot=float(lot) if lot else 0.0,
                risk_target_usd=risk_usd, default_lot=default_lot)
            if why == "scope":
                scope_skips += 1
                continue
            if why == "lot":
                lot_skips += 1
                continue
        funnel_sized += 1
        lot_fallbacks += int(lot_fallback)
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
        swap_events = []

        def accrue_swap(when):
            nonlocal swap, day_open
            cur_day = when.date()
            if cur_day != day_open:
                # Retain the observed UTC-date approximation: Thursday carries Wednesday's triple.
                mult = 3.0 if cur_day.weekday() == 3 else 1.0
                carry = (swap_l if long else swap_s) * (lots / 0.01) * mult
                swap += carry
                swap_events.append([str(when), carry])
                day_open = cur_day

        exit_row = None
        for b in range(t + 1, len(h1)):
            bar = h1.iloc[b]
            op, hi, lo, cl = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
            bar_time = bar["time"]
            accrue_swap(bar_time)
            # Explicit broker H1 checks never fall back; only legacy M1 permits
            # an execution candle with no minute rows to use its own OHLC.
            # Check the stop known before this row; its extremes can only
            # tighten the next row's stop. Stop wins ties against target.
            rows = [(None, op, hi, lo, cl)]
            if m1_times is not None:
                bt = int(h1_secs[b])
                if position_bars is None:
                    bt -= bt % 3600  # vendor stamps can be :01; broker checks keep exact boundaries
                i0 = int(np.searchsorted(m1_times, bt, side="left"))
                check_end = bt + bar_hours * 3600
                if position_bars is not None and b + 1 < len(h1):
                    # Short broker sessions must not consume the next execution candle's hours.
                    check_end = min(check_end, int(h1_secs[b + 1]))
                i1 = int(np.searchsorted(m1_times, check_end, side="left"))
                if position_bars is not None and i1 == i0:
                    raise ValueError(f"{symbol}: no broker H1 position checks for {bar_time}")
                if i1 > i0:
                    # The execution open is known even if the first minute is absent.
                    rows = [(int(h1_secs[b]), op, op, op, op)] + [
                            (m1_times[r], m1_open[r], m1_high[r], m1_low[r], m1_close[r])
                            for r in range(i0, i1)]
            px, why, row_when = None, None, None
            if (exit_crosses is not None and b > t + 1
                    and opposite_crossover(exit_crosses[b - 1], direction,
                                           h1["time"].iloc[t + 1], bar_hours)):
                # The previous candle is closed; exit now without reading this candle's range.
                eff_open_sl = combine_stop(sl, entry, stop_dist, hh if long else ll,
                                           long, use_be, be_buf, use_trail, trail_r) if activated else sl
                close_open = op if long else op + spread_px
                hit_open_sl = close_open <= eff_open_sl if long else close_open >= eff_open_sl
                hit_open_tp = close_open >= tp if long else close_open <= tp
                px = tp if hit_open_tp and not hit_open_sl else close_open
                why = "stop" if hit_open_sl else "target" if hit_open_tp else "crossover"
                row_when = int(h1_secs[b])
                rows = []
            for row_t, row_op, row_hi, row_lo, _ in rows:
                if row_t is not None:
                    accrue_swap(pd.Timestamp(row_t, unit="s", tz="UTC"))
                eff_sl = sl
                if activated:
                    # shared core: BE + T1 overlays (quant/rules.combine_stop)
                    eff_sl = combine_stop(sl, entry, stop_dist, hh if long else ll,
                                          long, use_be, be_buf, use_trail, trail_r)
                # Short protective orders execute on ask; long orders execute on bid.
                close_op = row_op if long else row_op + spread_px
                close_hi = row_hi if long else row_hi + spread_px
                close_lo = row_lo if long else row_lo + spread_px
                open_sl = close_op <= eff_sl if long else close_op >= eff_sl
                open_tp = close_op >= tp if long else close_op <= tp
                if open_sl or open_tp:
                    # A gapped stop fills at the available open, not the unreachable stop.
                    px, why = (close_op, "stop") if open_sl else (tp, "target")
                    row_when = int(h1_secs[b]) if row_t is None else int(row_t)
                    break
                hit_sl = (close_lo <= eff_sl) if long else (close_hi >= eff_sl)
                hit_tp = (close_hi >= tp) if long else (close_lo <= tp)
                # Range outcomes become known at the check candle's close, never its open.
                row_close = None if row_t is None else row_t + check_seconds
                if hit_sl and hit_tp:
                    px, why, row_when = eff_sl, "stop", row_close  # Stop wins ambiguous ties.
                    break
                if hit_sl:
                    px, why, row_when = eff_sl, "stop", row_close
                    break
                if hit_tp:
                    px, why, row_when = tp, "target", row_close
                    break
                hh, ll = max(hh, row_hi), min(ll, row_lo)  # Known after this row closes.
                if not activated and ((row_hi >= entry + act_r * stop_dist) if long
                                      else (row_lo <= entry - act_r * stop_dist)):
                    activated = True  # stop changes take effect from the next row
            if px is None and bias_flip_exit and mapped is not None:
                bd = mapped["direction"].iloc[b]
                if (long and bd == "SHORT") or (not long and bd == "LONG"):
                    px, why = cl if long else cl + spread_px, "bias-flip"
            if px is None and weekend_flat and b + 1 < len(h1):
                nxt = h1["time"].iloc[b + 1]
                if (nxt - bar_time).total_seconds() > 24 * 3600 and bar_time.weekday() == 4:
                    px, why = cl if long else cl + spread_px, "weekend"
            if px is None and independent_candidates and b == len(h1) - 1:
                # Keep the final open candidate visible to admission; mark it at tape end.
                px, why = cl if long else cl + spread_px, "end-of-data"
            if px is not None:
                # px is already the executable bid/ask; charge slippage, not spread again.
                exit_px = px - slip_px if long else px + slip_px
                pnl_ticks = ((exit_px - entry) if long else (entry - exit_px)) / tick_size
                # Keep the old argument for callers, but never book OHLC outcomes at open.
                coarse_time = bar_time + pd.Timedelta(hours=bar_hours)
                exit_time = (str(pd.Timestamp(row_when, unit="s", tz="UTC"))
                             if row_when is not None else str(coarse_time))
                # A range exit booked at midnight must include that boundary too.
                accrue_swap(pd.Timestamp(exit_time))
                exit_second = int(pd.Timestamp(exit_time).timestamp())
                exposure_seconds = (elapsed[b] - elapsed[t + 1]
                                    + min(max(exit_second - h1_secs[b], 0), durations[b]))
                exit_tick = tick_spec(symbol, exit_px, _converter_rates(converters, pd.Timestamp(exit_time)))
                if exit_tick is None:
                    raise ValueError(f"{symbol}: USD conversion unavailable at exit {exit_time}")
                pnl = pnl_ticks * exit_tick[1] * lots + swap - commission * lots * 2
                trades.append({"symbol": symbol, "direction": direction,
                               "entry_time": str(h1["time"].iloc[t + 1]),
                               "entry": round(entry, 5), "sl": round(sl, 5), "tp": round(tp, 5),
                               "lot": lots, "exit_time": exit_time,
                               "exit": round(exit_px, 5), "exit_type": why,
                               "pnl_usd": round(pnl, 2),
                               "pnl_R": round(pnl / risk_actual, 3) if risk_actual > 0 else 0.0,
                                "swap": round(swap, 2), "atr": round(atr_f, 5),
                                "entry_commission": commission * lots,
                                "short_spread_usd": 0.0 if long else spread_px / tick_size * tick_value * lots,
                                 "swap_events": json.dumps(swap_events),
                                 "entry_bid": fill, "spread_price": spread_px,
                                 "quote_notional": 100000.0 * lots,
                                "bars_held": held + 1,
                                "exposure_seconds": float(exposure_seconds),
                                "risk_usd": round(risk_actual, 2),
                                "tp_usd": round(tp_mult * risk_actual, 2),
                                "entry_reason": cand.get("entry_reason", "unknown"),
                                 "signal_bar_time": str(h1["time"].iloc[t])})
                if independent_candidates and p.get("use_crossover_memory", False):
                    trades[-1]["crossover_time"] = cand["crossover_time"]
                open_until = b
                break
            held += 1
        else:
            continue
    cols = ["symbol", "direction", "entry_time", "entry", "sl", "tp", "lot",
            "exit_time", "exit", "exit_type", "pnl_usd", "pnl_R", "swap", "atr",
              "bars_held", "exposure_seconds", "risk_usd", "tp_usd", "entry_reason", "signal_bar_time",
              "entry_commission", "short_spread_usd", "swap_events",
              "entry_bid", "spread_price", "quote_notional"]
    if independent_candidates and p.get("use_crossover_memory", False):
        cols.append("crossover_time")
    return pd.DataFrame(trades, columns=cols), {
        "sized": funnel_sized, "window": window_skips, "entry_hours": hours_skips, "open": open_skips,
        "day": day_skips, "tick": tick_skips, "scope": scope_skips,
        "cost": cost_skips, "lot": lot_skips, "stopcap": stop_cap_skips,
        "lot_fallback": lot_fallbacks}


def metrics(trades: pd.DataFrame, months_days: float, n_bars: int, *,
            available_seconds: float | None = None) -> dict:
    """Per-pair stats. months_days (data span) and n_bars give the per-month and
    legacy exposure denominators. New exposure uses held/available seconds in
    observed execution intervals, excluding gaps; filtering keeps that denominator."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net_usd": 0.0, "swap_usd": 0.0, "net_R": 0.0,
                "commission_usd": 0.0,
                "expect_R": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "max_dd": 0.0,
                "exposure_pct": 0.0, "per_month": 0.0}
    wins = trades[trades["pnl_usd"] > 0]
    gross_pos = float(wins["pnl_usd"].sum())
    gross_neg = -float(trades[trades["pnl_usd"] <= 0]["pnl_usd"].sum())
    # equity starts at 0 (the account baseline), so a first-trade loss is DD too
    eq = pd.concat([pd.Series([0.0]), trades["pnl_usd"].cumsum()], ignore_index=True)
    dd = float((eq.cummax() - eq).max())
    months = max(months_days / 30.44, 1.0)
    held = float(trades["bars_held"].sum()) if "bars_held" in trades else 0.0
    exposure = 100.0 * held / max(n_bars, 1)  # Legacy artifacts retain their bar-count estimate.
    if available_seconds is not None and "exposure_seconds" in trades:
        exposure = (100.0 * float(trades["exposure_seconds"].sum()) / available_seconds
                    if available_seconds > 0 else 0.0)
    return {"trades": n, "net_usd": round(float(trades["pnl_usd"].sum()), 2),
            "commission_usd": (round(2 * float(trades["entry_commission"].sum()), 2)
                               if "entry_commission" in trades else None),
            "swap_usd": round(float(trades["swap"].sum()), 2) if "swap" in trades else 0.0,
            "net_R": round(float(trades["pnl_R"].sum()), 2),
            "expect_R": round(float(trades["pnl_R"].mean()), 3),
            "win_rate": round(len(wins) / n, 3),
            "profit_factor": round(gross_pos / gross_neg, 3) if gross_neg > 0 else float("inf"),
            "max_dd": round(dd, 2),
            "exposure_pct": round(exposure, 2),
            "per_month": round(n / months, 2)}


def yearly_table(trades: pd.DataFrame, evaluation_window: dict | None = None) -> pd.DataFrame:
    """Trades, net USD and net R per symbol-year (exit year)."""
    if len(trades) == 0:
        return pd.DataFrame(columns=["symbol", "year", "trades", "net_usd", "net_R"])
    t = trades.copy()
    exits = pd.to_datetime(t["exit_time"], utc=True)
    if (evaluation_window or {}).get("enabled"):
        end = pd.Timestamp(evaluation_window["end"])
        # A close/terminal mark at the exclusive boundary belongs to the interval just ended.
        exits = exits.mask(exits == end, end - pd.Timedelta(nanoseconds=1))
    t["year"] = exits.dt.year
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
    # months span: first entry to last exit (entry column can be absent in test frames)
    t_exit = pd.to_datetime(t["exit_time"], utc=True)
    t_entry = pd.to_datetime(t["entry_time"], utc=True) if "entry_time" in t.columns else t_exit
    months = max((t_exit.max() - t_entry.min()).days / 30.44, 0.5)
    eq0 = pd.concat([pd.Series([0.0]), eq], ignore_index=True)  # DD counts the first loss too
    return {"symbol": "TOTAL", "trades": n,
            "commission_usd": (round(2 * float(t["entry_commission"].sum()), 2)
                               if "entry_commission" in t else None),
            "net_usd": round(float(t["pnl_usd"].sum()), 2),
            "swap_usd": round(float(t["swap"].sum()), 2) if "swap" in t else 0.0,
            "net_R": round(float(t["pnl_R"].sum()), 2),
            "expect_R": round(float(t["pnl_R"].mean()), 3),
            "win_rate": round(len(wins) / n, 3),
            "profit_factor": round(gross_pos / gross_neg, 3) if gross_neg > 0 else float("inf"),
            "max_dd": round(float((eq0.cummax() - eq0).max()), 2),
            "per_month": round(n / months, 2)}


def _band(val: float, thr: dict | None, lower_better: bool = False) -> str:
    """PASS/WARN/FAIL from benchmark thresholds {good, ok}: either may be absent
    (single threshold gives PASS/FAIL only). Absolute-tie: PASS sits at `good`,
    WARN strictly worse than good but still inside `ok`. NA when unset or NaN."""
    if thr is None or val != val:
        return "NA"
    good, ok = thr.get("good"), thr.get("ok")
    if good is None and ok is None:
        return "NA"

    def inside_level(t: float) -> bool:
        return val <= float(t) if lower_better else val >= float(t)

    if good is None:
        return "PASS" if inside_level(ok) else "FAIL"
    if inside_level(good):
        return "PASS"
    if ok is None or not inside_level(ok):
        return "FAIL"
    return "WARN"


def grade_benchmarks(m: dict, bench: dict, portfolio: bool = False,
                     min_year_R: float | None = None) -> dict:
    """Acceptance bands from `_base.yaml benchmarks:`. Verdict = worst band of
    the graded metrics (WARN-first reporting; a FAIL is loud). 0-trade rows are
    NA, not FAIL — no trades is no evidence, not a broken strategy."""
    out: dict = {}
    account = float(bench.get("account_usd", 0) or 0)
    dd_pct = float("nan")
    if account > 0:
        dd_pct = float(m.get("max_dd", 0) or 0) / account * 100
    out["max_dd_pct"] = round(dd_pct, 2) if dd_pct == dd_pct else dd_pct
    if int(m.get("trades", 0) or 0) == 0:
        out["verdict"] = "NA"
        return out
    # per-pair DD% is informational only (each pair does not own its own 100 USD);
    # the drawdown bands grade the shared account -> TOTAL (portfolio) rows only
    out["pf_band"] = _band(float(m.get("profit_factor", 0) or 0), bench.get("profit_factor"))
    out["expect_band"] = _band(float(m.get("expect_R", 0) or 0), bench.get("expect_r"))
    if portfolio and bench.get("max_dd_pct"):
        out["dd_band"] = _band(dd_pct, bench.get("max_dd_pct"), lower_better=True)
    if portfolio and bench.get("per_month"):
        out["freq_band"] = _band(float(m.get("per_month", 0) or 0), bench["per_month"])
    if portfolio and bench.get("worst_year_r") and min_year_R is not None:
        out["year_band"] = _band(min_year_R, bench["worst_year_r"])
    rank = {"FAIL": 2, "WARN": 1, "PASS": 0}
    bands = [v for k, v in out.items() if k.endswith("_band") and v in rank]
    out["verdict"] = max(bands, key=rank.get) if bands else "NA"
    return out


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


def _broker_bar_path(h1_path: str | Path, symbol: str, tf: str) -> Path:
    """Broker-exported higher-timeframe CSV beside the H1 input."""
    path = Path(h1_path).with_name(f"{symbol}_{tf}.csv")
    meta = path.with_suffix(".meta.json")
    if meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get(
            "source_type") == "vendor_derived_research":
        raise ValueError("derived research candles require explicit --research-data-dir")
    return path


def load_chart_frames(symbol: str, h1_path: str | Path, exec_hours: int = 1,
                       reg_hours: int = 4, research_data_dir=None, broker_data_dir=None):
    """Shared backtest/dice grids; only explicit research mode accepts derived files."""
    from quant.monitor import TF_COMBOS, TF_HOURS

    names = {v: k for k, v in TF_HOURS.items()}
    if broker_data_dir:
        from quant.broker_data import chart_path
        if research_data_dir or (exec_hours, reg_hours) not in TF_COMBOS:
            raise ValueError("broker CSV mode requires a supported timeframe combo without research substitution")
        execution_tf, regime_tf = names[exec_hours], names[reg_hours]
        path = chart_path(broker_data_dir, symbol, execution_tf)
        if Path(h1_path).resolve() != path.resolve():
            raise ValueError(f"broker-only tape must be the matching {execution_tf} export, not another source")
        execution = load_h1(path)
        return execution, execution, load_h1(chart_path(broker_data_dir, symbol, regime_tf)), True
    h1 = load_h1(h1_path)
    if research_data_dir:
        from quant.mkdata import research_chart_path
        def chart(hours):
            return load_h1(research_chart_path(research_data_dir, symbol, names[hours], h1_path))
        return h1, chart(exec_hours), chart(reg_hours), True
    if exec_hours == reg_hours:
        execution = h1 if exec_hours == 1 else load_h1(
            _broker_bar_path(h1_path, symbol, names[exec_hours]))
        return h1, execution, execution, True
    broker_bars = reg_hours == 24
    if broker_bars:
        return (h1, h1 if exec_hours == 1 else load_h1(_broker_bar_path(h1_path, symbol, "H4")),
                load_h1(_broker_bar_path(h1_path, symbol, "D1")), True)
    return h1, h1 if exec_hours == 1 else build_htf(h1, exec_hours), build_htf(h1, reg_hours), False


def run_pair(symbol: str, h1_path: str | Path, p: dict, costs: dict, args,
             converters: dict[str, pd.Series] | None = None) -> dict:
    # Validated execution/regime hours include both H1 and H4 Daily-bias entries.
    exec_hours = int(getattr(args, "exec_hours", 1) or 1)
    reg_hours = int(getattr(args, "reg_hours", 4) or 4)
    h1, exec_df, reg_df, broker_bars = load_chart_frames(
        symbol, h1_path, exec_hours, reg_hours, getattr(args, "research_data_dir", None),
        getattr(args, "broker_data_dir", None))
    window = getattr(args, "evaluation_window", None)
    h1 = evaluation_tape(h1, window, exec_hours if getattr(args, "broker_data_dir", None) else 1)
    exec_df = evaluation_tape(exec_df, window, exec_hours)
    validate_preparation(exec_df, reg_df, p, window)
    funnel, cands = scan_pair(exec_df, reg_df, symbol, p,
                               reg_hours=reg_hours, exec_hours=exec_hours,
                              broker_bars=broker_bars, evaluation_window=window)
    bframes = bias_frames(reg_df, p)
    mapped = map_bias(exec_df, reg_df, bframes, reg_hours=reg_hours,
                      exec_hours=exec_hours, broker_bars=broker_bars)
    m1 = None
    position_bars = load_position_bars(symbol, exec_df, getattr(args, "broker_data_dir", None),
                                       str(getattr(args, "position_checks", "M1")).upper(), exec_hours)
    if str(getattr(args, "position_checks", "M1")).upper() == "M1":
        m1 = _load_m1(h1_path, symbol)
        if getattr(args, "research_data_dir", None) and m1 is None:
            raise ValueError("research mode requires the original M1 checks; no silent fallback")
    ranges = tuple(getattr(args, "no_trade_ranges", ()) or ())
    trades, extra = simulate(exec_df, symbol, cands, p, costs, args.risk_usd,
                             args.max_cost_ratio,
                             bias_flip_exit=bool(p.get("bias_flip_exit", False)),
                             weekend_flat=bool(p.get("weekend_flat", False)),
                             mapped=mapped, lot=args.lot, converters=converters,
                              m1=m1, no_trade_ranges=ranges,
                              entry_hours=getattr(args, "entry_hours", None),
                             scope_low=getattr(args, "scope_low", 0.0),
                             scope_high=getattr(args, "scope_high", 0.0),
                             bar_hours=exec_hours,
                             stop_sizing=getattr(args, "stop_sizing", None),
                             default_lot=getattr(args, "default_lot", None),
                              coarse_exit_at_close=bool(getattr(args, "broker_data_dir", None)),
                                independent_candidates=True, position_bars=position_bars,
                                evaluation_window=window)
    funnel["sized"] = extra["sized"]
    funnel["window"] = extra.get("window", 0)
    funnel["entry_hours"] = extra.get("entry_hours", 0)
    for key in ("open", "day", "tick", "scope", "cost", "lot", "stopcap", "lot_fallback"):
        funnel[key] = extra.get(key, 0)  # every named gate lands in funnel.csv
    funnel["taken"] = len(trades)
    measured = exec_df
    days = (h1["time"].iloc[-1] - h1["time"].iloc[0]).days
    if (window or {}).get("enabled"):
        measured = exec_df[exec_df["time"] >= pd.Timestamp(window["start"])]
        days = (pd.Timestamp(window["end"]) - pd.Timestamp(window["start"])).total_seconds() / 86400
    available_seconds = float(_bar_durations(_epoch_s(measured["time"]), exec_hours).sum())
    m = metrics(trades, days, len(measured), available_seconds=available_seconds)
    m["symbol"] = symbol
    m["signals"] = len(cands)
    result = {"funnel": funnel, "trades": trades, "metrics": m, "n_bars": len(measured),
            "available_seconds": available_seconds,
            "span_days": days,
            "span": ((window["start"], window["end"]) if (window or {}).get("enabled")
                     else (str(h1["time"].iloc[0]), str(h1["time"].iloc[-1]))),
            # the regime chart's per-bar direction, straight from the frame the
            # scan just used — the report shades its regime view with this
            "reg_bias": ([str(t) for t in reg_df["time"]],
                          [str(v) for v in bframes["direction"]],
                          [bool(v) for v in bframes["hr1"]])}
    if getattr(args, "compare_results", False):
        from quant.ledger import data_identity
        try:
            result["comparison_inputs"] = {
                "raw": data_identity(h1), "execution": data_identity(exec_df),
                "regime": data_identity(reg_df), "broker_bars": broker_bars,
                "minute_checks": data_identity(m1) if m1 is not None else None,
                "converters": {s: data_identity(feed) for s, feed in sorted((converters or {}).items())}}
            result["comparison_costs"] = dict(costs)
            if position_bars is not None:
                result["comparison_inputs"]["position_bars"] = data_identity(position_bars)
        except Exception as exc:
            result["comparison_error"] = str(exc)  # Reporting must never discard a valid pair result.
    return result


def load_position_bars(symbol: str, execution: pd.DataFrame, broker_root,
                       checks: str, exec_hours: int) -> pd.DataFrame | None:
    """Load finer, checksum-pinned broker checks; never substitute vendor/coarse bars."""
    if not broker_root:
        return None
    from quant.broker_data import chart_path, resolve_position_checks

    execution_tf = {1: "H1", 4: "H4", 24: "D1"}[exec_hours]
    resolve_position_checks({"backtest_data": {"position_checks": checks}}, execution_tf)
    if checks == execution_tf:
        return None
    hourly = load_h1(chart_path(broker_root, symbol, checks))
    # Every observed execution candle needs at least one actual hourly check.
    # Partial broker sessions remain flagged by the source manifest, never filled.
    times = hourly["time"].to_numpy()
    starts = execution["time"].to_numpy()
    ends = (execution["time"] + pd.Timedelta(hours=exec_hours)).to_numpy()
    if hourly.empty or (np.searchsorted(times, ends) == np.searchsorted(times, starts)).any():
        raise ValueError(f"{symbol}: broker H1 position-check coverage missing for execution candles")
    return hourly


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


def run_all(jobs: list[tuple[str, Path, dict]], p: dict, args, converters,
            workers: int) -> tuple[dict[str, dict], dict[str, str]]:
    """Run every pair. Jobs are (symbol, csv path, per-pair costs). One pair never
    splits across processes. Returns (results, failures)."""
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    if workers <= 1:
        for sym, h1_path, costs in jobs:
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
        for sym, h1_path, costs in jobs:
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


def write_bias_maps(outdir: Path, results: dict[str, dict]) -> None:
    """Run artifact bias_<SYM>.csv: (time, direction, hr1) of the regime grid.

    Emitted from each pair's own regime frame, so the report shades its regime
    view with exactly what the engine believed while scanning. Pairs that
    failed before the scan simply get no file (report shows no shading).
    """
    for sym, res in results.items():
        rb = res.pop("reg_bias", None)
        if rb is None:
            continue
        pd.DataFrame({"time": rb[0], "direction": rb[1], "hr1": rb[2]}
                     ).to_csv(outdir / f"bias_{sym}.csv", index=False)


def _epoch_s(col: pd.Series) -> np.ndarray:
    # Pandas datetime storage units vary; normalize to seconds before extracting integers.
    return pd.to_datetime(pd.Series(col), utc=True).dt.as_unit("s").astype("int64").to_numpy()


def _quote_usd_values(symbol: str, prices: np.ndarray, times: np.ndarray,
                      converters: dict[str, pd.Series] | None) -> np.ndarray:
    """USD per quote-currency unit using only rates available at each mark."""
    from quant.rules import USD_CONVERSION_FEEDS

    quote = symbol[3:]
    if quote == "USD":
        return np.ones(len(times))
    if symbol.startswith("USD"):
        return 1.0 / prices
    feed = USD_CONVERSION_FEEDS.get(quote)
    series = (converters or {}).get(feed)
    if series is None or series.empty:
        return np.full(len(times), np.nan)
    feed_times = _epoch_s(pd.Series(series.index))
    indices = np.searchsorted(feed_times, times, side="right") - 1
    rates = np.where(indices >= 0, series.to_numpy(float)[np.maximum(indices, 0)], np.nan)
    return 1.0 / rates if feed.startswith("USD") else rates


def mtm_equity(trades_by_sym: dict[str, pd.DataFrame],
               h1_by_sym: dict[str, pd.DataFrame],
               account_usd: float, *, accrue_costs: bool = False,
               converters: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    """Mark-to-market over supplied closed-price tapes (H1 legacy, H4 broker).

    Tape timestamps must be close-availability times; optional open_time/open
    adds prices known at candle open. New trades use quote notional and as-of
    USD conversion. Legacy rows retain initial-risk-based marks. Realized P/L
    lands at the exit (pnl_usd, all costs included). accrue_costs also books entry
    commission, short ask-spread valuation, and recorded overnight swap events.
    Legacy callers default to price-only marks. Runs without risk_usd degrade to the
    closed-trade curve, which keeps the starting 100 USD baseline.
    """
    pairs = [s for s in trades_by_sym if len(trades_by_sym[s]) and s in h1_by_sym]
    if not pairs:
        return pd.DataFrame(columns=["time", "usd"])
    # At a shared boundary the new known open supersedes the previous close.
    tapes = {}
    for s in pairs:
        source = h1_by_sym[s]
        tape = pd.DataFrame({"time": source["time"], "price": source["close"]})
        if "open_time" in source:
            tape = pd.concat([tape, pd.DataFrame({"time": source["open_time"], "price": source["open"]})])
        tapes[s] = tape.sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    g = np.unique(np.concatenate([_epoch_s(tapes[s]["time"]) for s in pairs]))
    if accrue_costs:
        # Preserve fills beyond the final price mark (e.g. a final-bar minute exit).
        g = np.unique(np.concatenate([g] + [
            _epoch_s(trades_by_sym[s][column]) for s in pairs
            for column in ("entry_time", "exit_time")]))
        swap_times = [int(pd.Timestamp(when).timestamp()) for s in pairs
                      for events in trades_by_sym[s].get("swap_events", [])
                      for when, _ in json.loads(events)]
        if swap_times:
            g = np.unique(np.concatenate([g, np.asarray(swap_times, dtype=np.int64)]))
    if converters:
        # A conversion-rate change can move USD equity even when the pair is flat.
        extra = np.concatenate([_epoch_s(pd.Series(feed.index)) for feed in converters.values()])
        g = np.unique(np.concatenate([g, extra[(extra >= g[0]) & (extra <= g[-1])]]))
    eq = np.full(g.size, float(account_usd))
    for s in pairs:
        h1 = tapes[s]
        p_times = _epoch_s(h1["time"])
        closes = h1["price"].to_numpy(dtype=float)
        idx = np.searchsorted(p_times, g, side="right") - 1
        px = np.where(idx >= 0, closes[np.clip(idx, 0, None)], np.nan)
        t = trades_by_sym[s]
        n = len(t)
        entries = _epoch_s(t["entry_time"])
        exits = _epoch_s(t["exit_time"])
        entry = t["entry"].to_numpy(dtype=float)
        stop = np.abs(entry - t["sl"].to_numpy(dtype=float))
        # 0 risk (old runs) or a zero stop contributes no mark
        risk = np.nan_to_num(t["risk_usd"].to_numpy(dtype=float)
                             if "risk_usd" in t.columns else np.zeros(n))
        signs = np.where(t["direction"].to_numpy() == "LONG", 1.0, -1.0)
        # unrealized: R-multiple at the last pair bar <= t, inside [entry, exit);
        # per-trade loop keeps memory flat for runs with thousands of trades
        unreal = np.zeros(g.size)
        for i in range(n):
            if stop[i] == 0 or risk[i] == 0:
                continue
            m = (g >= entries[i]) & (g < exits[i])
            if not m.any():
                continue
            row = t.iloc[i]
            # A pre-entry close cannot value a newly opened trade across a gap.
            bid_at_entry = float(row.get("entry_bid", entry[i] - (
                float(row.get("spread_price", 0)) if signs[i] > 0 else 0)))
            mark_times = np.where(idx >= 0, p_times[np.maximum(idx, 0)], -1)
            trade_px = np.where(mark_times <= entries[i], bid_at_entry, px)
            with np.errstate(divide="ignore", invalid="ignore"):
                r = signs[i] * (trade_px - entry[i]) / stop[i]
            if "quote_notional" in t.columns:
                close_px = trade_px + (float(row["spread_price"]) if signs[i] < 0 and accrue_costs else 0)
                conversion = _quote_usd_values(s, close_px, g, converters)
                if not np.isfinite(conversion[m]).all() or (conversion[m] <= 0).any():
                    raise ValueError(f"{s}: USD conversion unavailable for open-position marks")
                values = signs[i] * (close_px - entry[i]) * float(row["quote_notional"]) * conversion
            else:
                values = np.where(np.isfinite(r), r, 0.0) * risk[i]
            unreal += np.where(m, values, 0.0)
            if accrue_costs:
                # Entry commission and short-side ask valuation are not in bid-price marks.
                fee = float(t.iloc[i].get("entry_commission", 0))
                short_spread = 0.0 if "quote_notional" in t.columns else float(row.get("short_spread_usd", 0))
                unreal[m] -= fee + short_spread
                for when, amount in json.loads(t.iloc[i].get("swap_events", "[]")):
                    at = pd.Timestamp(when).timestamp()
                    unreal[m & (g >= at)] += float(amount)
        eq += unreal
        # realized: each pnl_usd applies from its exit bar onward
        order = np.argsort(exits)
        step_idx = np.searchsorted(g, exits[order], side="left")
        valid = step_idx < g.size
        step = np.zeros(g.size)
        np.add.at(step, step_idx[valid], t["pnl_usd"].to_numpy(dtype=float)[order][valid])
        eq += np.cumsum(step)
    return pd.DataFrame({"time": pd.to_datetime(g, unit="s", utc=True), "usd": eq})


def portfolio_filter(trades_by_sym: dict[str, pd.DataFrame], max_open: int,
                     max_ccy_net: int, weekly_r: float, *,
                     max_trades_per_pair_per_week: int = 0,
                     disable_pair_after_daily_loss: bool = False,
                     max_trades_per_week: int = 0,
                      max_trades_per_day: int = 0, crossover_max_entries: int = 0,
                      one_entry_per_pair_per_day: bool = False,
                      balance_sizing: dict | None = None
                     ) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Portfolio pass over the per-pair trade lists (time-ordered, all pairs).

    Enforces the locked portfolio rules the per-pair simulation cannot see:
      - max_open: max concurrent open trades portfolio-wide (0 = off)
      - max_ccy_net: |net currency count| per currency (long EURUSD = +EUR/-USD;
        short = mirror; keeps one-sided currency stacks thin) (0 = off)
      - weekly_r: once a week's CLOSED R total is a loss of that many R, no new
        entries until the next Monday 00:00 UTC (0 = off). Units are each
        trade's own risk multiple (pnl_R in the trades frames), per STRATEGY
        8A weekly_loss_r — R, NOT % of equity: the %-equity form flips sign
        once closed equity hits zero (the threshold turns positive), so the
        account state can never reach this rule.
      - optional pair weekly entry cap and daily net-loss block (UTC calendar).
        Only accepted entries count; only their exits can trigger a loss block.
       - optional daily/weekly portfolio caps, in this pass so rejects cost no quota.
    Deterministic: candidates by (entry_time, symbol); an exit at the same
    timestamp is applied BEFORE entries (frees the slot). Exits book R to the
    week of their own timestamp (deal-time booking, like live counts deals
    >= monday_ts); an entry-only rollover once let an early-week exit vanish
    into the discarded previous week.
    Returns (kept frames by symbol, dropped records).
    """
    from quant.limits import pair_entry_reason

    if balance_sizing is not None:
        trades_by_sym = {s: df.copy() for s, df in trades_by_sym.items()}
    if max_open <= 0 and max_ccy_net <= 0 and weekly_r <= 0 \
            and max_trades_per_pair_per_week <= 0 \
            and not disable_pair_after_daily_loss and max_trades_per_day <= 0 \
            and max_trades_per_week <= 0 and crossover_max_entries <= 0 \
            and not one_entry_per_pair_per_day and balance_sizing is None:
        return dict(trades_by_sym), []
    cands = []
    for sym, df in trades_by_sym.items():
        if not len(df):
            continue
        for idx, t in df.iterrows():
            cands.append((sym, int(idx), str(t["entry_time"]), str(t["exit_time"]),
                          str(t.get("direction", "")), float(t["pnl_R"])))
    # one event per trade: exits (0) sort before entries (1) at equal timestamps
    evs = []
    for sym, idx, tin, tout, direction, pnl_r in cands:
        evs.append((_ts_utc(tin), 1, sym, idx, direction, pnl_r))
        evs.append((_ts_utc(tout), 0, sym, idx, direction, pnl_r))
    evs.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    active: dict = {}          # (sym, idx) -> direction
    kept: dict[str, list[int]] = {}
    dropped: list[dict] = []
    ccy: dict = {}
    week_key = None
    week_r = 0.0                # CLOSED R booked this week (exits only)
    week_count = 0
    halted = False
    pair_counts: dict = {}
    loss_days: set = set()
    day_counts: dict = {}
    crossover_counts: dict = {}
    pair_days: set = set()
    balance = float(balance_sizing["start_balance"]) if balance_sizing else 0.0

    def _drop(sym, idx, tin, reason):
        dropped.append({"symbol": sym, "entry_time": tin[:16], "reason": reason})

    for t, kind, sym, idx, direction, pnl_r in evs:
        # week rolls on EVERY event, by that event's own timestamp: exits book
        # to their own week, deal-time, like live counts deals >= monday_ts.
        # (Rollover on entries only let a Monday/early-week exit land in the
        # dead previous-week bucket — the next entry reset the loss away.)
        wk = t.normalize() - pd.Timedelta(days=t.weekday())  # Monday 00:00 UTC
        if wk != week_key:
            week_key = wk
            week_r = 0.0
            week_count = 0
            halted = False
            pair_counts.clear()
        if kind == 0:  # exit: free the slot, book the R, run the halt check
            direction = active.pop((sym, idx), None)
            if direction is None:
                continue  # was dropped at entry — it never held currency exposure
            base, quote = sym[:3].upper(), sym[3:].upper()
            sgn = 1 if direction == "LONG" else -1
            ccy[base] = ccy.get(base, 0) - sgn
            ccy[quote] = ccy.get(quote, 0) + sgn
            week_r += pnl_r
            if balance_sizing is not None:
                balance += float(trades_by_sym[sym].at[idx, "pnl_usd"])
            # Only accepted, closed trades can block their pair; USD includes costs.
            if disable_pair_after_daily_loss and float(
                    trades_by_sym[sym].at[idx, "pnl_usd"]) < 0:
                loss_days.add((sym, t.date()))
            if weekly_r > 0 and week_r <= -weekly_r:
                halted = True
            continue
        # entry decision (exits at the same timestamp have already run)
        hh_mm = t.strftime("%Y-%m-%d %H:%M")
        cycle = None
        if one_entry_per_pair_per_day or crossover_max_entries > 0:
            if any(key[0] == sym for key in active):
                _drop(sym, idx, hh_mm, "pair_open")
                continue
        if one_entry_per_pair_per_day and (sym, t.date()) in pair_days:
            _drop(sym, idx, hh_mm, "pair_day")
            continue
        if crossover_max_entries > 0:
            cross_time = trades_by_sym[sym].at[idx, "crossover_time"]
            if pd.isna(cross_time) or _ts_utc(str(cross_time)) >= t:
                raise ValueError("crossover entry needs a confirmed earlier crossover_time")
            cycle = (sym, str(cross_time))
            if crossover_counts.get(cycle, 0) >= crossover_max_entries:
                _drop(sym, idx, hh_mm, "crossover_cap")
                continue
        reason = pair_entry_reason(
            pair_counts.get(sym, 0), (sym, t.date()) in loss_days,
            max_trades_per_pair_per_week, disable_pair_after_daily_loss)
        if reason:
            _drop(sym, idx, hh_mm, reason)
            continue
        if halted:
            _drop(sym, idx, hh_mm, "weekly_halt")
            continue
        if max_trades_per_week > 0 and week_count >= max_trades_per_week:
            _drop(sym, idx, hh_mm, "cap_week")
            continue
        if max_trades_per_day > 0 and day_counts.get(t.date(), 0) >= max_trades_per_day:
            _drop(sym, idx, hh_mm, "cap_day")
            continue
        if max_open > 0 and len(active) >= max_open:
            _drop(sym, idx, hh_mm, "open_max")
            continue
        base, quote = sym[:3].upper(), sym[3:].upper()
        sgn = 1 if direction == "LONG" else -1
        d_base, d_quote = ccy.get(base, 0) + sgn, ccy.get(quote, 0) - sgn
        if max_ccy_net > 0 and (abs(d_base) > max_ccy_net or abs(d_quote) > max_ccy_net):
            _drop(sym, idx, hh_mm, "ccy")
            continue
        if balance_sizing is not None:
            # Size only a proposed accepted entry, using previously realized balance.
            scaled, refused = scale_lots_to_balance(
                {sym: trades_by_sym[sym].loc[[idx]]}, balance_sizing["pct"],
                balance_sizing["scope_low"], balance_sizing["scope_high"], balance,
                balance_sizing["default_lot"])
            if refused:
                _drop(sym, idx, hh_mm, refused[0]["reason"])
                continue
            for column in scaled[sym].columns:
                trades_by_sym[sym].at[idx, column] = scaled[sym].at[idx, column]
        active[(sym, idx)] = direction
        if cycle is not None:
            crossover_counts[cycle] = crossover_counts.get(cycle, 0) + 1
        kept.setdefault(sym, []).append(idx)
        pair_days.add((sym, t.date()))
        pair_counts[sym] = pair_counts.get(sym, 0) + 1
        week_count += 1
        day_counts[t.date()] = day_counts.get(t.date(), 0) + 1
        ccy[base], ccy[quote] = d_base, d_quote
    out_frames = {}
    for sym, df in trades_by_sym.items():
        ids = kept.get(sym, [])
        out_frames[sym] = df[df.index.isin(ids)].reset_index(drop=True) if ids else df.iloc[0:0]
    return out_frames, dropped


def _ts_utc(s: str) -> pd.Timestamp:
    v = pd.Timestamp(s)
    return v.tz_localize("UTC") if v.tzinfo is None else v


def scale_lots_to_balance(trades_by_sym: dict[str, pd.DataFrame],
                          pct: float, scope_low: float, scope_high: float,
                          start_balance: float, default_lot: float = 0.01
                          ) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Account-global lot scaling (risk.scale_lot_with_balance ON).

    One forward walk over ALL pairs by timestamp: exits book before entries at
    the same stamp; the balance starts at the account seed and changes only on
    closed trades (realized). Each entry re-aims its 1R at pct% of that
    balance through rules.scaled_lots (0.01 snapping + the SAME scope fence).
    Every kept trade keeps its pnl_R exactly (R is lot-invariant); the USD
    fields scale with the lot: pnl_usd = pnl_R x new 1R, and swap, risk_usd,
    tp_usd x lot ratio (commission is already inside pnl_usd, so it scales
    with it). risk_usd MUST rescale: the MTM equity curve marks open trades
    at R x risk_usd, and stale risk would corrupt max_dd_mtm.
    Entry sizing uses only the trade's recorded initial risk and lot size.
    Older rows without valid initial risk remain unscaled, never inferred from P/L.
    Returns (frames by symbol, dropped records like the portfolio pass).
    """
    out: dict[str, pd.DataFrame] = {s: df.copy() for s, df in trades_by_sym.items()}
    evs = []
    for sym, df in out.items():
        if not len(df):
            continue
        for idx, t in df.iterrows():
            evs.append((_ts_utc(str(t["entry_time"])), 1, sym, int(idx)))
            evs.append((_ts_utc(str(t["exit_time"])), 0, sym, int(idx)))
    evs.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    balance = float(start_balance)
    dropped: list[dict] = []
    unscaled = 0
    for ts, kind, sym, idx in evs:  # noqa: F841 (ts read via ordering only)
        if kind == 0:  # exit: book realized, deal-time like the weekly halt
            if idx in out[sym].index:  # an entry refused mid-walk has no exit row
                balance += float(out[sym].at[idx, "pnl_usd"])
            continue
        lot_old = float(out[sym].at[idx, "lot"])
        if lot_old <= 0:
            continue
        initial_risk = float(out[sym].loc[idx].get("risk_usd", float("nan")))
        if not np.isfinite(initial_risk) or initial_risk <= 0 or not np.isfinite(lot_old):
            unscaled += 1
            continue
        step0 = initial_risk / (lot_old / 0.01)
        aim = pct / 100.0 * balance
        lots_new, risk_new, why = scaled_lots(
            step0, aim, scope_low, scope_high, default_lot)
        if why is not None:
            dropped.append({"symbol": sym, "entry_time": str(out[sym].at[idx, "entry_time"])[:16],
                            "reason": f"scale-{why}"})
            out[sym] = out[sym].drop(index=idx)
            continue
        factor = lots_new / lot_old
        pnl_r = float(out[sym].at[idx, "pnl_R"])
        out[sym].at[idx, "lot"] = lots_new
        out[sym].at[idx, "pnl_usd"] = round(pnl_r * risk_new, 2)
        out[sym].at[idx, "risk_usd"] = round(risk_new, 2)  # MTM marks read this
        out[sym].at[idx, "tp_usd"] = round(float(out[sym].at[idx, "tp_usd"]) * factor, 2)
        out[sym].at[idx, "swap"] = round(float(out[sym].at[idx, "swap"]) * factor, 2)
        for column in ("entry_commission", "short_spread_usd", "quote_notional"):
            if column in out[sym]:
                out[sym].at[idx, column] = float(out[sym].at[idx, column]) * factor
        if "swap_events" in out[sym]:
            out[sym].at[idx, "swap_events"] = json.dumps([
                [when, amount * factor] for when, amount in json.loads(out[sym].at[idx, "swap_events"])])
    if unscaled:
        print(f"scale pass: {unscaled} trade(s) left unscaled (no 0.01-risk info)",
              flush=True)
    return out, dropped


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


def _cli_costs(args) -> dict:
    """Only the CLI-provided cost overrides; they beat base and pair yamls so
    sensitivity sweeps stay global even where pair yamls carry live spreads."""
    out: dict = {}
    if args.spread_pips is not None:
        out["spread_points"] = args.spread_pips * 10.0
    if args.spread_points is not None:
        out["spread_points"] = args.spread_points
    if args.slippage_pips is not None:
        out["slippage_pips"] = args.slippage_pips
    if args.flat_swaps:
        out["swap_long_per_0_01"] = 0.0
        out["swap_short_per_0_01"] = 0.0
    return out


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description="Backtester on the shared signal core.")
    ap.add_argument("--config", default=None, help="single pair yaml")
    ap.add_argument("--data", default=None, help="single H1 csv")
    ap.add_argument("--batch", action="store_true", help="loop scan-selection.yml")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--base-config", default=None,
                    help="select a shared preset without changing configs/_base.yaml")
    ap.add_argument("--results-dir", default="backtest_results")
    ap.add_argument("--compare-results", action=argparse.BooleanOptionalAction, default=None,
                    help="compare completed comparable runs and mark BEST.txt (default: on)")
    ap.add_argument("--comparison-max-dd-pct", type=float, default=None,
                    help="best-run drawdown ceiling; default = backtest_comparison or benchmarks max_dd_pct.ok")
    ap.add_argument("--spread-pips", type=float, default=None)
    ap.add_argument("--spread-points", type=float, default=None)
    ap.add_argument("--flat-swaps", action="store_true")
    ap.add_argument("--slippage-pips", type=float, default=None)
    ap.add_argument("--risk-usd", type=float, default=3.0,
                    help="legacy fixed target; only used when the sizing scope is off")
    ap.add_argument("--lot", type=float, default=None,
                    help="fixed diagnostic lot; default = size by risk.sizing_scope_usd")
    ap.add_argument("--scope-low", type=float, default=None,
                    help="override risk.sizing_scope_usd.low from _base.yaml")
    ap.add_argument("--scope-high", type=float, default=None,
                    help="override risk.sizing_scope_usd.high from _base.yaml")
    ap.add_argument("--scale-lots", action="store_true",
                    help="force risk.scale_lot_with_balance ON (compounding sizing)")
    ap.add_argument("--balance-risk-pct", type=float, default=None,
                    help="override risk.balance_risk_pct (%% of balance per trade when scaling)")
    ap.add_argument("--widen-stop", action="store_true",
                    help="force risk.stop_sizing.widen_stop_to_scope ON: fixed lot, "
                         "stop widened until the lot reaches the scope floor")
    ap.add_argument("--default-lot", "--stop-lot", dest="default_lot", type=float, default=None,
                    help="override risk.default_lot (base size; --stop-lot is a legacy alias)")
    ap.add_argument("--stop-max-atr", type=float, default=None,
                    help="override risk.stop_sizing.max_stop_atr (widening cap, x ATR)")
    ap.add_argument("--max-cost-ratio", type=float, default=None,
                    help="override limits.max_cost_ratio from _base.yaml")
    ap.add_argument("--max-total-positions", type=int, default=None,
                    help="override risk.max_total_positions (portfolio pass; 0 = off)")
    ap.add_argument("--max-ccy-net", type=int, default=None,
                    help="override risk.max_ccy_net (currency exposure cap; 0 = off)")
    ap.add_argument("--weekly-loss-r", type=float, default=None,
                    help="override limits.weekly_loss_r (backtest weekly halt in R, "
                         "STRATEGY 8A; 0 = off)")
    ap.add_argument("--atr-n", type=int, default=None)
    ap.add_argument("--sep-atr", type=float, default=None)
    ap.add_argument("--ma-only", action="store_true")
    ap.add_argument("--bias-flip-exit", action="store_true")
    ap.add_argument("--weekend-flat", action="store_true")
    ap.add_argument("--jobs", type=int, default=10,
                    help="pairs run in parallel (capped at pair count); 1 = linear, 0 = all cores")
    ap.add_argument("--data-dir", default="data", help="batch H1/M1 and converter source directory")
    ap.add_argument("--research-data-dir", default=None,
                    help="explicit opt-in to a labelled vendor-derived research manifest")
    ap.add_argument("--broker-data-dir", default=None, help="override backtest_data.broker_csv_dir")
    ap.add_argument("--evaluation-window", action=argparse.BooleanOptionalAction, default=None,
                    help="enable/disable offline trading and performance date boundaries")
    ap.add_argument("--evaluation-start", default=None, help="inclusive UTC trading start; earlier prices prepare indicators")
    ap.add_argument("--evaluation-end", default=None, help="exclusive UTC end; must not cut an execution candle")
    args = ap.parse_args(argv)
    if args.jobs < 0:
        ap.error("--jobs must be >= 0")

    from quant.monitor import (TF_HOURS, base_config_path, flatten_strategy, load_pairs,
                               read_selection, read_timeframes)

    preset = {"base_config": args.base_config} if args.base_config else {}
    base_path = base_config_path(args.config_dir, args.base_config)
    try:
        # Capture the loaded source once so later edits cannot change the snapshot.
        base_bytes = base_path.read_bytes()
        base = yaml.safe_load(base_bytes.decode("utf-8-sig")) or {}
        from quant.performance import PerformanceSettings
        PerformanceSettings.from_dict(base.get("performance"))
        strat = flatten_strategy(base)
        args.evaluation_window = read_evaluation_window(base, enabled=args.evaluation_window,
                                                       start=args.evaluation_start, end=args.evaluation_end)
        crossover = validate_crossover(strat)
        from quant.ledger import comparison_settings
        comparison_cfg = comparison_settings(base, args.compare_results, args.comparison_max_dd_pct)
        args.compare_results = comparison_cfg["enabled"]
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"config error: {exc}", flush=True)
        return 2
    costs = dict((base.get("costs") or {}))
    max_day = int((base.get("limits") or {}).get("max_trades_per_day", 0) or 0)
    from quant.limits import read_pair_limits
    pair_limits = read_pair_limits(base.get("limits") or {})
    args.entry_hours = read_entry_hours(base.get("limits") or {})
    pair_limits_on = any(pair_limits.values())
    bench = dict(base.get("benchmarks") or {})
    # portfolio-pass knobs (locked rules the per-pair sim cannot see); 0 = off
    risk_cfg = dict(base.get("risk") or {})
    if args.max_total_positions is None:
        args.max_total_positions = int(risk_cfg.get("max_total_positions") or 0)
    if args.max_ccy_net is None:
        args.max_ccy_net = int(risk_cfg.get("max_ccy_net") or 0)
    if args.weekly_loss_r is None:
        args.weekly_loss_r = float((base.get("limits") or {}).get(
            "weekly_loss_r", 0.0) or 0.0)
    # the cost gate lives in _base.yaml limits (visible config), CLI overrides it
    if args.max_cost_ratio is None:
        args.max_cost_ratio = float(
            (base.get("limits") or {}).get("max_cost_ratio", 0.10) or 0.0)
    scope = dict((base.get("risk") or {}).get("sizing_scope_usd") or {})
    # sizing scope: actual 1R must land inside [low, high] USD; 0 disables a side
    if args.scope_low is None:
        args.scope_low = float(scope.get("low", 0.0) or 0.0)
    if args.scope_high is None:
        args.scope_high = float(scope.get("high", 0.0) or 0.0)
    # scaled sizing: aim = balance_risk_pct % of the account balance; CLI forces ON
    risk_all = dict(base.get("risk") or {})
    if args.balance_risk_pct is None:
        args.balance_risk_pct = float(risk_all.get("balance_risk_pct") or 0.0)
    if bool(risk_all.get("scale_lot_with_balance") or False):
        args.scale_lots = True
    if args.scale_lots and args.balance_risk_pct <= 0:
        print("config error: scale_lot_with_balance needs risk.balance_risk_pct > 0",
              flush=True)
        return 2
    if args.scale_lots and (pair_limits_on or crossover):
        # Do not enable previously unsupported combinations as part of a bug fix.
        print("config error: balance scaling with entry limits remains gated pending a validated "
              "unified sizing/admission pass; use fixed-dollar sizing or disable entry limits, "
              "including crossover memory",
              flush=True)
        return 2
    # stop sizing: widen the stop instead of trading more lots (off by default)
    if args.default_lot is not None:
        risk_all["default_lot"] = args.default_lot
    try:
        args.default_lot, stop_sizing = read_sizing(risk_all)
    except (TypeError, ValueError) as exc:
        print(f"config error: {exc}", flush=True)
        return 2
    if args.widen_stop:
        stop_sizing["widen_stop_to_scope"] = True
    if args.stop_max_atr is not None:
        stop_sizing["max_stop_atr"] = args.stop_max_atr
    if stop_sizing.get("widen_stop_to_scope"):
        conflict = stop_sizing_conflict(stop_sizing, bool(args.scale_lots))
        if conflict:
            print(f"config error: {conflict}", flush=True)
            return 2
    args.stop_sizing = stop_sizing
    try:
        args.no_trade_ranges = tuple(parse_no_trade_ranges(base))
    except ValueError as exc:
        print(f"config error: {exc}", flush=True)
        return 2
    # Stop/target/BE/trail checks read the minute feed when the config says M1.
    args.position_checks = str((base.get("timeframes") or {}).get(
        "position_checks", "M1")).upper()
    # Daily-bias combinations require exported Daily bars; broker mode loads exact charts.
    try:
        args.exec_tf, args.reg_tf = read_timeframes(args.config_dir, **preset)
    except ValueError as exc:
        print(f"config error: {exc}", flush=True)
        return 2
    args.exec_hours = TF_HOURS[args.exec_tf]
    args.reg_hours = TF_HOURS[args.reg_tf]
    from quant.broker_data import (resolve_broker_dir, dataset_info, chart_path, closed_converter,
                                   resolve_position_checks)
    try:
        args.broker_data_dir = resolve_broker_dir(base, args.research_data_dir, args.broker_data_dir)
        if args.broker_data_dir:
            args.position_checks = resolve_position_checks(base, args.exec_tf)
        broker = dataset_info(args.broker_data_dir, args.exec_tf, args.position_checks) if args.broker_data_dir else None
        if broker:
            print(broker["warning"], flush=True)
            for warning in broker["coverage_warnings"]:
                print(f"COVERAGE WARNING: {warning}", flush=True)
    except (ValueError, OSError, KeyError) as exc:
        print(f"broker data error: {exc}", flush=True)
        return 2
    research = None
    if args.research_data_dir:
        from quant.mkdata import research_info, RESEARCH_WARNING
        try:
            research = research_info(args.research_data_dir)
        except (ValueError, OSError, KeyError) as exc:
            print(f"research data error: {exc}", flush=True)
            return 2
        print(RESEARCH_WARNING, flush=True)
    if args.bias_flip_exit:
        strat["bias_flip_exit"] = True  # CLI flag forces on; config holds the default
    if args.weekend_flat:
        strat["weekend_flat"] = True
    if args.atr_n is not None:
        strat["entry_atr_period"] = args.atr_n
    if args.sep_atr is not None:
        strat["sep_atr"] = args.sep_atr
    if args.ma_only:
        strat["use_atr_sep"] = False
    costs.update(_cli_costs(args))

    # jobs carry per-pair costs: base + pair yaml + CLI (CLI always wins last)
    jobs: list[tuple[str, Path, dict]] = []
    pair_costs_recorded: dict[str, dict] = {}
    if args.batch:
        pairs = load_pairs(args.config_dir, **preset)
        selection = read_selection(args.config_dir)
        disabled = []
        for pr in pairs:
            sym = pr["symbol"]
            if selection is not None and not selection.get(sym, True):
                disabled.append(sym)
                continue
            h1_path = Path(args.broker_data_dir or args.data_dir) / f"{sym}_{args.exec_tf if broker else 'H1'}.csv"
            if not h1_path.exists():
                if broker:
                    print(f"broker data error: missing enabled pair {sym}: {h1_path}", flush=True)
                    return 2
                print(f"SKIP {sym} - no {h1_path}", flush=True)
                continue
            pc = dict(costs)
            pc.update(pr.get("costs") or {})
            pc.update(_cli_costs(args))
            if pr.get("costs"):
                pair_costs_recorded[sym] = dict(pr["costs"])
            jobs.append((sym, h1_path, pc))
        if disabled:
            print(f"disabled in scan-selection.yml: {', '.join(disabled)}", flush=True)
    else:
        if not args.config or (not args.data and not broker):
            print("Need --config + --data, or --batch.", flush=True)
            return 2
        cfg = yaml.safe_load(open(args.config, encoding="utf-8")) or {}
        sym = str(cfg.get("symbol") or Path(args.config).stem)
        pc = dict(costs)
        pc.update(cfg.get("costs") or {})
        pc.update(_cli_costs(args))
        if cfg.get("costs"):
            pair_costs_recorded[sym] = dict(cfg["costs"])
        jobs.append((sym, Path(args.data) if args.data else Path(args.broker_data_dir) / f"{sym}_{args.exec_tf}.csv", pc))
    if not jobs:
        print("Nothing to run.", flush=True)
        return 1

    if broker:
        try:
            for sym, tape, _ in jobs:
                if tape.resolve() != chart_path(args.broker_data_dir, sym, args.exec_tf).resolve():
                    raise ValueError(f"{sym}: broker mode requires its {args.exec_tf} file, not another source")
                chart_path(args.broker_data_dir, sym, args.reg_tf)
                chart_path(args.broker_data_dir, sym, args.position_checks)
        except (ValueError, OSError, KeyError) as exc:
            print(f"broker data error: {exc}", flush=True)
            return 2
    elif args.research_data_dir:
        from quant.mkdata import research_chart_path
        try:
            for sym, h1_path, _ in jobs:
                for tf in {args.exec_tf, args.reg_tf}:
                    research_chart_path(args.research_data_dir, sym, tf, h1_path)
        except (ValueError, OSError, KeyError) as exc:
            print(f"research data error: {exc}", flush=True)
            return 2
    elif args.reg_tf == "D1" or args.exec_tf == args.reg_tf == "H4":
        required_charts = tuple(tf for tf in ("H4", "D1")
                                if tf in (args.exec_tf, args.reg_tf))
        missing = [str(path) for sym, h1_path, _ in jobs
                   for tf in required_charts
                   if not (path := _broker_bar_path(h1_path, sym, tf)).exists()]
        if missing:
            print(f"config error: {args.exec_tf}/{args.reg_tf} needs broker-exported CSVs beside H1: "
                  + ", ".join(missing), flush=True)
            return 2

    # Quote-foreign pairs convert through a converter feed (JPY via USDJPY,
    # GBP via GBPUSD, ...). USD-quoted and USD-base pairs convert themselves.
    from quant.rules import USD_CONVERSION_FEEDS
    conv_map = USD_CONVERSION_FEEDS
    need: dict[str, list[str]] = {}
    for s, _, _ in jobs:
        if s[3:] == "USD" or s.startswith("USD"):
            continue
        feed = conv_map.get(s[3:])
        if feed:
            need.setdefault(feed, []).append(s)
        else:
            print(f"SKIP {s} - no converter feed for quote {s[3:]}", flush=True)
    jobs = [(s, p, c) for s, p, c in jobs if s[3:] == "USD" or s.startswith("USD")
            or s in [x for v in need.values() for x in v]]
    converters: dict[str, pd.Series] = {}
    for feed, syms in need.items():
        if broker:
            try:
                converters[feed] = closed_converter(args.broker_data_dir, feed, args.position_checks)
            except (ValueError, OSError, KeyError) as exc:
                print(f"broker converter error: {exc}", flush=True)
                return 2
            continue
        fp = Path(args.data_dir) / f"{feed}_H1.csv"
        if not fp.exists():
            for s in syms:
                print(f"SKIP {s} - no {feed} converter feed", flush=True)
            jobs = [(s, p, c) for s, p, c in jobs if s not in syms]
            continue
        if args.research_data_dir:
            try:
                research_chart_path(args.research_data_dir, feed, args.reg_tf, fp)
            except (ValueError, OSError, KeyError) as exc:
                print(f"research converter error: {exc}", flush=True)
                return 2
        converter = load_h1(fp)
        converters[feed] = pd.Series(converter["close"].to_numpy(),
                                     index=converter["time"] + pd.Timedelta(hours=1))
    if not jobs:
        print("Nothing to run.", flush=True)
        return 1

    outdir = Path(args.results_dir) / backtest_run_name(args.exec_tf, args.reg_tf)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        # Preserve comments, whitespace, line endings and any BOM without YAML reformatting.
        (outdir / "config.yaml").write_bytes(base_bytes)
    except OSError as exc:
        print(f"config snapshot error: {exc}", flush=True)
        return 2
    workers = resolve_workers(args.jobs, len(jobs))
    params = {
        "performance": base.get("performance") or {}, "equity_cost_timing": "accrued",
        "run_status": "running", "backtest_comparison": comparison_cfg,
        "broker_data": broker, "raw_tape_tf": args.exec_tf if broker else "H1",
        "coarse_exit_timing": "bar_close",
        "simulation_timing": SIMULATION_TIMING,
        "evaluation_window": args.evaluation_window,
        "swap_timing": "observed_utc_date_check_rows",
        "exposure_timing": "observed_execution_seconds",
        "research_data": research, "data_dir": str(Path(args.data_dir).resolve()),
        "strategy": strat, "costs": costs, "risk_usd": args.risk_usd,
        "base_config": str(base_path),
        "max_cost_ratio": args.max_cost_ratio,
        "sizing_scope_usd": {"low": args.scope_low, "high": args.scope_high},
        "scale_lot_with_balance": bool(args.scale_lots),
        "balance_risk_pct": float(args.balance_risk_pct),
        "stop_sizing": stop_sizing,
        "default_lot": args.default_lot,
        "lot": args.lot,
        "max_trades_per_day": max_day, "workers": workers,
        **pair_limits,
        "no_trade_ranges": args.no_trade_ranges,
        "entry_hours": args.entry_hours,
        "position_checks": args.position_checks,
        "timeframes": {"execution": args.exec_tf, "regime": args.reg_tf},
        "benchmarks": bench,
        "pair_costs": pair_costs_recorded,
        "jobs": [[s, str(path)] for s, path, _ in jobs]}
    # the yaml's own one-line comments travel into every run folder
    notes = yaml_notes(base_path)
    params["notes"] = {"_source": str(base_path), **notes}
    params_path = outdir / "params.json"
    params_path.write_text(json.dumps(params, indent=1), encoding="utf-8")

    print(f"running {len(jobs)} pair(s) on {workers} worker(s)", flush=True)
    results, failures = run_all(jobs, strat, args, converters, workers)
    write_bias_maps(outdir, results)  # per-run shading artifact for the report
    dropped: list[dict] = []
    # Admission and optional balance sizing share one chronological event walk.
    params["portfolio"] = {
        "max_total_positions": max(args.max_total_positions, 0),
        "max_ccy_net": max(args.max_ccy_net, 0),
        "weekly_loss_r": max(args.weekly_loss_r, 0.0)}
    params["portfolio"].update(pair_limits)
    if crossover:
        params["portfolio"]["crossover_max_entries"] = strat.get("crossover_max_entries", 2)
    kept_pf, pf_dropped = portfolio_filter(
        {s: r["trades"] for s, r in results.items()},
        params["portfolio"]["max_total_positions"], params["portfolio"]["max_ccy_net"],
        params["portfolio"]["weekly_loss_r"], **pair_limits,
        max_trades_per_day=max_day, one_entry_per_pair_per_day=not crossover,
        balance_sizing=({"pct": args.balance_risk_pct, "scope_low": args.scope_low,
                         "scope_high": args.scope_high, "default_lot": args.default_lot,
                         "start_balance": float(bench.get("account_usd") or 0) or 100.0}
                        if args.scale_lots else None),
        **({"crossover_max_entries": strat.get("crossover_max_entries", 2)} if crossover else {}))
    if args.scale_lots:
        params["scale_dropped"] = [d for d in pf_dropped if d["reason"].startswith("scale-")]
    changed = {s for s in kept_pf if args.scale_lots or len(kept_pf[s]) != len(results[s]["trades"])}
    for sym in sorted(changed):
        res = results[sym]
        res["trades"] = kept_pf[sym]
        m = metrics(kept_pf[sym], res["span_days"], res["n_bars"],
                    available_seconds=res.get("available_seconds"))
        m["symbol"], m["signals"] = sym, res["metrics"]["signals"]
        res["metrics"] = m
        res["funnel"]["taken"] = len(kept_pf[sym])
    if pf_dropped:
        params["portfolio"]["dropped"] = pf_dropped
        reasons: dict[str, int] = {}
        for d in pf_dropped:
            reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
        print(f"portfolio pass: dropped {len(pf_dropped)} entries "
              f"({', '.join(f'{k}={v}' for k, v in sorted(reasons.items()))}); "
              f"affected pairs: {', '.join(sorted(changed))}", flush=True)
    elif params["portfolio"]["weekly_loss_r"] or params["portfolio"]["max_ccy_net"] \
            or params["portfolio"]["max_total_positions"]:
        print("portfolio pass: no entries dropped", flush=True)
    if failures or dropped or pf_dropped:
        params["failed"] = failures
        params["daily_cap_dropped"] = dropped
    # Always persist the portfolio settings, including when no entries were dropped.
    params_path.write_text(json.dumps(params, indent=1), encoding="utf-8")

    # MTM account curve: hourly equity over open + closed positions, TOTAL only
    curve = None
    comparison_mtm_symbols = []
    taken = {s: r["trades"] for s, r in results.items() if len(r["trades"])}
    if taken:
        h1_by_sym, account_usd = {}, float(bench.get("account_usd") or 0) or 100.0
        for sym, h1_path, _ in jobs:
            if sym in taken:
                try:
                    h1_by_sym[sym] = load_h1(h1_path)
                    h1_by_sym[sym] = evaluation_tape(h1_by_sym[sym], args.evaluation_window,
                                                    args.exec_hours if broker else 1)
                    if args.compare_results:
                        try:
                            from quant.ledger import data_identity
                            # Ranking must not use changed prices or only a subset of traded pairs.
                            expected = results[sym]["comparison_inputs"]["raw"]
                            if data_identity(h1_by_sym[sym]) == expected:
                                comparison_mtm_symbols.append(sym)
                        except Exception as exc:
                            params.setdefault("comparison_input_errors", {})[sym] = str(exc)
                    # All CLOSE marks become available at completion, not candle open.
                    h1_by_sym[sym]["open_time"] = h1_by_sym[sym]["time"]
                    h1_by_sym[sym]["time"] += pd.Timedelta(hours=args.exec_hours if broker else 1)
                    if args.evaluation_window.get("enabled"):
                        h1_by_sym[sym] = h1_by_sym[sym][h1_by_sym[sym]["open_time"] >=
                                                      pd.Timestamp(args.evaluation_window["start"])]
                except Exception:
                    pass
        usable = {s: taken[s] for s in taken if s in h1_by_sym}
        if usable:
            curve = mtm_equity(usable, h1_by_sym, account_usd, accrue_costs=True, converters=converters)
            curve = evaluation_equity(curve, args.evaluation_window, account_usd)
            params["performance_equity_complete"] = set(usable) == set(taken)
            curve.to_csv(outdir / "equity_curve.csv", index=False)
            if args.compare_results:
                params["comparison_mtm_symbols"] = sorted(comparison_mtm_symbols)

    summaries, funnels, yearlies, all_trades = [], [], [], []
    run_profit_factor = None
    for sym, _, _ in jobs:  # input order, so output files do not depend on finish order
        res = results.get(sym)
        if res is None:
            continue
        f = res["funnel"]
        f["symbol"] = sym
        funnels.append(f)
        summaries.append({**res["metrics"], **grade_benchmarks(res["metrics"], bench)})
        res["trades"].to_csv(outdir / f"trades_{sym}.csv", index=False)
        yearlies.append(yearly_table(res["trades"], args.evaluation_window))
        if len(res["trades"]):
            all_trades.append(res["trades"])
    if failures:
        print(f"FAILED: {', '.join(failures)}", flush=True)
    if summaries:
        if all_trades:
            trow = total_row(pd.concat(all_trades, ignore_index=True))
            if args.evaluation_window.get("enabled"):
                days = (pd.Timestamp(args.evaluation_window["end"]) - pd.Timestamp(args.evaluation_window["start"])).total_seconds() / 86400
                trow["per_month"] = round(trow["trades"] / max(days / 30.44, 1.), 2)
            run_profit_factor = trow["profit_factor"]
            gsrc = trow
            if curve is not None and len(curve):
                # drawdown bands grade the mark-to-market curve (closed-only DD stays visible)
                dd_mtm = float((curve["usd"].cummax() - curve["usd"]).max())
                if args.compare_results:
                    params["comparison_mtm_drawdown_usd"] = dd_mtm
                trow["max_dd_mtm"] = round(dd_mtm, 2)
                trow["max_dd_mtm_pct"] = round(
                    100.0 * dd_mtm / float(bench.get("account_usd") or 0 or 100.0), 1)
                gsrc = {**trow, "max_dd": dd_mtm, "max_dd_pct": trow["max_dd_mtm_pct"]}
            year_all = pd.concat(yearlies, ignore_index=True)
            min_year = (float(year_all.groupby("year")["net_R"].sum().min())
                        if len(year_all) else None)
            grade = grade_benchmarks(gsrc, bench, portfolio=True, min_year_R=min_year)
            summaries.append({**trow, **grade})
            print(f"benchmarks TOTAL: {grade['verdict']} "
                  f"(dd MTM {grade.get('max_dd_pct')}% {grade.get('dd_band')}, "
                  f"pf {trow['profit_factor']} {grade.get('pf_band')}, "
                  f"expect {trow['expect_R']}R {grade.get('expect_band')})", flush=True)
        pd.DataFrame(summaries).to_csv(outdir / "summary.csv", index=False)
    if funnels:
        pd.concat(funnels, ignore_index=True).to_csv(outdir / "funnel.csv", index=False)
    if yearlies:
        pd.concat(yearlies, ignore_index=True).to_csv(outdir / "yearly.csv", index=False)
    # A completion stamp is written only after final costs, admission, sizing and summaries.
    from quant import ledger
    params["run_status"] = "failed" if failures else "completed"
    params["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    if args.compare_results and not failures:
        try:
            params["comparison_context"] = ledger.comparison_context(params, results)
        except (KeyError, TypeError, ValueError) as exc:
            params["comparison_error"] = str(exc)
    params_path.write_text(json.dumps(params, indent=1), encoding="utf-8")
    if not failures:
        outdir = add_profit_factor_suffix(outdir, run_profit_factor)
    if args.compare_results:
        try:
            ledger.compare_run(outdir)
        except Exception as exc:
            print(f"comparison: skipped ({exc})", flush=True)
    # report is best-effort: a missing plotly or any renderer error only prints
    from quant.report import try_write_report
    try_write_report(outdir)
    # run ledger: append is best-effort too — a broken row must not fail the run
    try:
        ledger.append(outdir)
    except Exception as exc:
        print(f"ledger: append failed ({exc})", flush=True)
    print(f"backtest results -> {outdir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
