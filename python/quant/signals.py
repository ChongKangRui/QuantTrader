"""Execution-chart entry core (STRATEGY.md sections 5-7, 16). No MT5 import.

E1 pullback-resume plus the hard rules only (HR2/HR3/HR4/extension cap),
plus the optional W1 wick-sweep gate (off until its config switch is on).
E2/E3 and every optional filter stay out until ablation. Evaluates at the
signal-bar close; the caller re-checks against the actual fill (spec: fill-time
re-check lives in the backtest/execution layers, which know the fill price).
"""
from __future__ import annotations

import pandas as pd

from quant.bias import bias_from_values, bias_periods

# Section-5 parameter table. Callers override per key from config.
# use_* flags switch gates off for ablation (off = gate auto-passes).
DEFAULTS = {
    "entry_atr_period": 7,
    "entry_ema_fast_period": 20,
    "entry_ema_slow_period": 50,
    "warmup_bars": 300,
    "stop_atr": 1.5,
    "tp_mult": 3.0,
    "ext_atr": 1.5,
    "edge_atr": 1.5,
    "pivot_n": 3,
    "hl_guard": True,
    "use_hr2": True,
    "use_hr3": True,
    "use_hr4": True,
    "use_ext": True,
    "use_e1_setup": True,
    "use_e1_trigger": True,
    "use_w1": False,          # W1 wick sweep: new experiment, off until enabled
    "w1_open_side": False,    # W1 extra: candle opens on the trade side
    "w1_pen_atr": 0.0,        # W1 min wick depth beyond the fast EMA (ATR)
    "w1_cross_into_gap": False,  # Optional pullback cross, closing between the EMAs
    "use_recovery_entry": False,  # Separate mode; replaces the other entry gates
    "recovery_use_zone_memory": False,  # Close inside the EMA gap; one recovery chance
    "recovery_use_wick": True,     # Allow EMA touches to arm/refresh the setup
    "recovery_expiry_bars": 4,    # Subsequent closed candles allowed after a touch
    "recovery_cancel_beyond_slow": True,
    "use_crossover_memory": False,
    "use_crossover_exit": False,
    "crossover_max_entries": 2,
    "crossover_history_bars": 6000,
    "min_body_ratio": 0.5,
    "max_body_atr": 1.5,
    "lookback": 12,
    "touch_atr": 0.5,
    "breakdown_atr": 1.0,
    "be_trigger_r": 1.0,
    "be_buffer": 0,
    "trail_r": 1.0,
}

# Funnel order for the first-failure code (spec section 2).
FAIL_ORDER = ["HR2", "HR3", "HR4", "HR4-guard", "EXT", "W1", "E1-setup", "E1-trigger"]


def _ema(s: pd.Series, period: int) -> pd.Series:
    # Same math as quant.bias (standard exponential MA, causal: row i uses closes <= i).
    return s.ewm(span=period, adjust=False).mean()


def _atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def pivot_lows(low: pd.Series, n: int) -> list[tuple[int, float]]:
    """Confirmed pivot lows: low[i] strictly below the n bars on each side."""
    v = low.to_numpy()
    out = []
    for i in range(n, len(v) - n):
        if v[i] < v[i - n:i].min() and v[i] < v[i + 1:i + 1 + n].min():
            out.append((i, float(v[i])))
    return out


def pivot_highs(high: pd.Series, n: int) -> list[tuple[int, float]]:
    v = high.to_numpy()
    out = []
    for i in range(n, len(v) - n):
        if v[i] > v[i - n:i].max() and v[i] > v[i + 1:i + 1 + n].max():
            out.append((i, float(v[i])))
    return out


ENTRY_REASON_LABELS = {
    "wick_touch": "Wick touch", "cross_candle": "Cross candle",
    "pullback_cross": "Pullback cross into EMA gap",
    "recovery_break": "Remembered pullback / previous-candle break",
    "legacy_w1": "Legacy W1", "other": "Other entry rules",
    "dice_a": "Random timing + direction", "dice_b": "Random timing / strategy direction",
    "unknown": "Unknown",
}


def _result(signal: bool, fail: str | None, checks: dict, level=None, atr=None,
            entry_reason: str = "unknown") -> dict:
    return {"signal": signal, "fail": fail, "checks": checks, "level": level,
             "atr": atr, "entry_reason": entry_reason}


def _recovery_step(i, high, low, close, ef, es, previous_edge, sign, armed_at,
                   expiry, cancel_beyond_slow, use_wick, use_zone_memory):
    """One closed candle; shared by historical replay and persisted crossover memory."""
    if sign * (ef - es) <= 0:
        return False, None
    beyond_slow = sign * (close - es) < 0
    if cancel_beyond_slow and beyond_slow:
        return False, None
    if not use_zone_memory and armed_at is not None and i - armed_at > expiry:
        armed_at = None
    if armed_at is not None and sign * (close - previous_edge) > 0:
        return True, None
    if use_zone_memory:
        if min(ef, es) <= close <= max(ef, es):
            armed_at = i
        elif not beyond_slow:
            armed_at = None
    elif sign * (close - ef) < 0 or (use_wick and low <= ef <= high):
        armed_at = i
    return False, armed_at


def _recovery_break(bars: pd.DataFrame, fast: pd.Series, slow: pd.Series,
                    side: str, expiry: int, cancel_beyond_slow: bool,
                    use_wick: bool, use_zone_memory: bool = False) -> bool:
    """Replay closed candles so pending setups and consumption survive restarts."""
    sign = 1 if side == "LONG" else -1
    armed_at = None
    result = False
    values = list(zip(bars["high"], bars["low"], bars["close"], fast, slow))
    for i, (high, low, close, ef, es) in enumerate(values):
        previous_edge = values[i - 1][0 if sign == 1 else 1] if i else close
        result, armed_at = _recovery_step(
            i, high, low, close, ef, es, previous_edge, sign, armed_at,
            expiry, cancel_beyond_slow, use_wick, use_zone_memory)
    return result


def validate_crossover(params: dict) -> bool:
    """Opt-in controls must fail loudly instead of silently granting more entries."""
    enabled = params.get("use_crossover_memory", False)
    exit_enabled = params.get("use_crossover_exit", False)
    if not isinstance(exit_enabled, bool):
        raise ValueError("use_crossover_exit must be true or false")
    if exit_enabled and not enabled:
        raise ValueError("use_crossover_exit requires use_crossover_memory")
    if not isinstance(enabled, bool):
        raise ValueError("use_crossover_memory must be true or false")
    if not enabled:
        return False
    p = {**DEFAULTS, **params}
    if p["use_recovery_entry"] is not True:
        raise ValueError("use_crossover_memory requires use_recovery_entry: true")
    for key in ("crossover_max_entries", "crossover_history_bars", "warmup_bars",
                "entry_ema_fast_period", "entry_ema_slow_period", "entry_atr_period",
                "bias_atr_period", "recovery_expiry_bars"):
        value = p.get(key, 14 if key == "bias_atr_period" else None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    if p["entry_ema_fast_period"] >= p["entry_ema_slow_period"]:
        raise ValueError("crossover EMA fast period must be smaller than slow period")
    if p["crossover_history_bars"] < max(p["warmup_bars"], p["entry_ema_slow_period"]) + 1:
        raise ValueError("crossover_history_bars must exceed warmup and the slow EMA period")
    for key in ("recovery_use_zone_memory", "recovery_cancel_beyond_slow", "recovery_use_wick"):
        if not isinstance(p[key], bool):
            raise ValueError(f"{key} must be true or false")
    return True


def opposite_crossover(record: dict, direction: str, opened_at, bar_hours: int) -> bool:
    """Only a confirmed opposite cross occurring after entry may close the position."""
    crossed = record.get("crossover_time")
    opposite = "SHORT" if direction == "LONG" else "LONG"
    return bool(crossed and record.get("direction") == opposite
                and pd.Timestamp(crossed) + pd.Timedelta(hours=bar_hours) > pd.Timestamp(opened_at))


def crossover_signals(bars: pd.DataFrame, params: dict,
                      memory: dict | None = None) -> tuple[list[dict], dict]:
    """Replay only closed candles; incremental EMA/ATR and pullbacks survive window rollover."""
    if not validate_crossover(params):
        raise ValueError("crossover_signals requires use_crossover_memory")
    p = {**DEFAULTS, **params}
    settings = {k: p.get(k) for k in (
        "entry_ema_fast_period", "entry_ema_slow_period", "entry_atr_period",
        "warmup_bars",
        "recovery_use_zone_memory", "recovery_expiry_bars", "recovery_use_wick",
        "recovery_cancel_beyond_slow")}
    state = dict(memory or {})
    # Older memory included regime-only settings; execution state does not depend on them.
    old_settings = {k: v for k, v in state.get("settings", {}).items()
                    if k not in ("bias_atr_period", "use_atr_sep", "sep_atr", "hr1")}
    if state and old_settings != settings:
        raise ValueError("crossover settings changed; restore matching memory/settings")
    state["settings"] = settings
    if bars.empty:
        raise ValueError("crossover closed-bar history unavailable")
    times = pd.to_datetime(bars["time"], utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("crossover history must have unique ascending times")
    if state.get("last_time") and pd.Timestamp(state["last_time"]) not in set(times):
        raise ValueError("crossover history does not overlap saved memory; increase crossover_history_bars")
    records = []
    for row, when in zip(bars.itertuples(index=False), times):
        stamp = when.isoformat()
        if state.get("last_time") and when <= pd.Timestamp(state["last_time"]):
            continue
        o, hi, lo, c = (float(getattr(row, k)) for k in ("open", "high", "low", "close"))
        if not all(pd.notna(v) and float("-inf") < v < float("inf") for v in (o, hi, lo, c)):
            raise ValueError("crossover history contains invalid prices")
        count = state.get("count", 0) + 1
        if count == 1:
            state["first_time"] = stamp
        prev_close = state.get("close", c)
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        for key, value, alpha in (
            ("fast", c, 2 / (p["entry_ema_fast_period"] + 1)),
            ("slow", c, 2 / (p["entry_ema_slow_period"] + 1)),
            ("atr", tr, 1 / p["entry_atr_period"])):
            state[key] = value if key not in state else alpha * value + (1 - alpha) * state[key]
        ef, es = state["fast"], state["slow"]
        sign = 1 if ef > es else -1 if ef < es else 0
        previous_sign = state.get("sign", 0)
        if sign and previous_sign and sign != previous_sign:
            state["armed_at"] = None
            if count > max(p["warmup_bars"], p["entry_ema_slow_period"]):
                state["crossover_time"] = stamp
                state["direction"] = "LONG" if sign == 1 else "SHORT"
        if sign:
            state["sign"] = sign  # Equality does not invent an opposite crossover.
        previous_edge = state.get("high" if sign == 1 else "low", c)
        signal, state["armed_at"] = _recovery_step(
            count, hi, lo, c, ef, es, previous_edge, sign or 1, state.get("armed_at"),
            p["recovery_expiry_bars"], p["recovery_cancel_beyond_slow"],
            p["recovery_use_wick"], p["recovery_use_zone_memory"])
        ready = count > max(p["warmup_bars"], p["entry_atr_period"]) and state["atr"] > 0
        result = {"time": stamp, "crossover_time": state.get("crossover_time"),
                   "direction": state.get("direction"),
                   "signal": bool(signal and ready and state.get("crossover_time")
                                  and sign == (1 if state.get("direction") == "LONG" else -1)),
                  "atr": state["atr"], "entry_reason": "recovery_break"}
        state.update(count=count, close=c, high=hi, low=lo, last_time=stamp, latest=result)
        records.append(result)
    return records, state


def check_entry(h1: pd.DataFrame, direction: str, params: dict | None = None) -> dict:
    """Entry gates on closed execution bars. t = last row (signal bar)."""
    p = {**DEFAULTS, **(params or {})}
    if validate_crossover(p):
        if h1 is None or h1.empty:
            return _result(False, "warmup", {})
        _, memory = crossover_signals(h1, p)
        latest = memory["latest"]
        signal = latest["signal"] and direction.upper() == latest["direction"]
        fail = None if signal else "crossover-memory" if not latest["crossover_time"] else "W1"
        return _result(signal, fail, {code: signal for code in FAIL_ORDER},
                       atr=latest["atr"], entry_reason="recovery_break" if signal else "unknown")
    for key in ("use_recovery_entry", "recovery_cancel_beyond_slow", "recovery_use_wick",
                "recovery_use_zone_memory"):
        if not isinstance(p[key], bool):
            raise ValueError(f"{key} must be true or false")
    expiry = p["recovery_expiry_bars"]
    if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry < 1:
        raise ValueError("recovery_expiry_bars must be a positive integer")
    # Keep old flat configs working without letting legacy keys override new ones.
    for new, old in (("entry_atr_period", "atr_n"),
                     ("entry_ema_fast_period", "h1_ema_fast"),
                     ("entry_ema_slow_period", "h1_ema_slow")):
        if params is not None and new not in params and old in params:
            p[new] = params[old]
    warmup = int(p["warmup_bars"])
    lookback = int(p["lookback"])
    n = int(p["pivot_n"])
    side = str(direction).upper()
    if h1 is None or len(h1) < max(warmup, lookback + 1, 2 * n + 1):
        return _result(False, "warmup", {}, None, None)
    if side not in ("LONG", "SHORT"):
        return _result(False, "direction", {}, None, None)

    close, high, low = h1["close"], h1["high"], h1["low"]
    efast = _ema(close, int(p["entry_ema_fast_period"]))
    eslow = _ema(close, int(p["entry_ema_slow_period"]))
    atr = _atr_wilder(high, low, close, int(p["entry_atr_period"]))
    t = len(h1) - 1
    o, hi, lo, c = (float(h1[col].iloc[t]) for col in ("open", "high", "low", "close"))
    a = float(atr.iloc[t])
    if pd.isna(a) or a <= 0:
        return _result(False, "warmup", {}, None, None)
    if p["use_recovery_entry"]:
        if not p["recovery_use_zone_memory"] and expiry >= len(h1):
            raise ValueError("recovery_expiry_bars must be smaller than the available entry history")
        signal = _recovery_break(h1, efast, eslow, side, expiry,
                                 p["recovery_cancel_beyond_slow"], p["recovery_use_wick"],
                                 p["recovery_use_zone_memory"])
        # This mode replaces candle filters, not the caller's bias/risk/cost guards.
        checks = {code: True for code in FAIL_ORDER}
        checks["W1"] = signal
        return _result(signal, None if signal else "W1", checks, atr=a,
                       entry_reason="recovery_break" if signal else "unknown")
    body, rng = abs(c - o), hi - lo
    checks: dict[str, bool] = {}
    w1_depth = float(p.get("w1_pen_atr", 0.0)) * a  # W1 sweep yardstick
    # Modern patterns are opt-in so older W1 configurations keep their behavior.
    w1_patterns = bool(p["w1_cross_into_gap"]) or (params is not None and (
        "w1_touch_from_trend_side" in params or "w1_cross_from_other_side" in params))
    fast, slow = float(efast.iloc[t]), float(eslow.iloc[t])
    # Fade the pullback only while the entry EMAs still agree with the bias.
    pullback_cross = bool(p["w1_cross_into_gap"]) and (
        (fast > slow and o > fast and slow < c < fast) if side == "LONG" else
        (fast < slow and o < fast and fast < c < slow))

    if side == "LONG":
        checks["HR2"] = rng > 0 and body / rng >= float(p["min_body_ratio"]) and c > o
        checks["HR3"] = body <= float(p["max_body_atr"]) * a
        pivots = pivot_lows(low, n)
        hl = next(((idx, px) for idx, px in reversed(pivots) if idx <= t - n), (None, None))
        checks["HR4"] = (hl[0] is not None and c > hl[1]
                         and c - hl[1] <= float(p["edge_atr"]) * a)
        if hl[0] is not None and bool(p["hl_guard"]):
            since = low.iloc[hl[0] + 1:t + 1].to_numpy()
            checks["HR4-guard"] = not (len(since) and since.min() < hl[1])
        else:
            checks["HR4-guard"] = True
        checks["EXT"] = abs(c - float(efast.iloc[t])) <= float(p["ext_atr"]) * a
        win = range(max(0, t - lookback + 1), t + 1)  # includes the signal bar
        touch = any(float(low.iloc[i]) - float(eslow.iloc[i]) <= float(p["touch_atr"]) * float(atr.iloc[i])
                    for i in win)
        nobreak = all(float(close.iloc[i]) >= float(eslow.iloc[i]) - float(p["breakdown_atr"]) * float(atr.iloc[i])
                      for i in win)
        checks["E1-setup"] = touch and nobreak
        checks["E1-trigger"] = c > float(efast.iloc[t]) and c > float(high.iloc[t - 1])
        # W1 · wick swept the fast EMA against the trade; the chart's own
        # fast/slow EMA relation must agree with the bias direction
        fast = float(efast.iloc[t])
        open_ok = ((bool(p.get("w1_touch_from_trend_side")) and o > fast)
                   or (bool(p.get("w1_cross_from_other_side")) and o < fast))
        checks["W1"] = (fast > float(eslow.iloc[t])
                        and lo <= fast - w1_depth
                        and ((c > fast and open_ok) if w1_patterns else
                             (o > fast if bool(p.get("w1_open_side", False)) else True)))
        level = hl[1]
    else:
        checks["HR2"] = rng > 0 and body / rng >= float(p["min_body_ratio"]) and c < o
        checks["HR3"] = body <= float(p["max_body_atr"]) * a
        pivots = pivot_highs(high, n)
        lh = next(((idx, px) for idx, px in reversed(pivots) if idx <= t - n), (None, None))
        checks["HR4"] = (lh[0] is not None and c < lh[1]
                         and lh[1] - c <= float(p["edge_atr"]) * a)
        if lh[0] is not None and bool(p["hl_guard"]):
            since = high.iloc[lh[0] + 1:t + 1].to_numpy()
            checks["HR4-guard"] = not (len(since) and since.max() > lh[1])
        else:
            checks["HR4-guard"] = True
        checks["EXT"] = abs(c - float(efast.iloc[t])) <= float(p["ext_atr"]) * a
        win = range(max(0, t - lookback + 1), t + 1)
        touch = any(float(eslow.iloc[i]) - float(high.iloc[i]) <= float(p["touch_atr"]) * float(atr.iloc[i])
                    for i in win)
        nobreak = all(float(close.iloc[i]) <= float(eslow.iloc[i]) + float(p["breakdown_atr"]) * float(atr.iloc[i])
                      for i in win)
        checks["E1-setup"] = touch and nobreak
        checks["E1-trigger"] = c < float(efast.iloc[t]) and c < float(low.iloc[t - 1])
        fast = float(efast.iloc[t])
        open_ok = ((bool(p.get("w1_touch_from_trend_side")) and o < fast)
                   or (bool(p.get("w1_cross_from_other_side")) and o > fast))
        checks["W1"] = (fast < float(eslow.iloc[t])
                        and hi >= fast + w1_depth
                        and ((c < fast and open_ok) if w1_patterns else
                             (o < fast if bool(p.get("w1_open_side", False)) else True)))
        level = lh[1]

    checks["W1"] = checks["W1"] or pullback_cross

    # Ablation switches: a disabled gate auto-passes (still reported per gate).
    if not bool(p.get("use_hr2", True)):
        checks["HR2"] = True
    if not bool(p.get("use_hr3", True)):
        checks["HR3"] = True
    if not bool(p.get("use_hr4", True)):
        checks["HR4"] = True
        checks["HR4-guard"] = True
    if not bool(p.get("use_ext", True)):
        checks["EXT"] = True
    if not bool(p.get("use_e1_setup", True)):
        checks["E1-setup"] = True
    if not bool(p.get("use_e1_trigger", True)):
        checks["E1-trigger"] = True
    if not bool(p.get("use_w1", False)):
        checks["W1"] = True
    fail = next((code for code in FAIL_ORDER if not checks.get(code, False)), None)
    reason = "unknown"
    if fail is None:
        if not bool(p.get("use_w1", False)):
            reason = "other"  # A disabled W1 is not the reason this entry qualified.
        elif not w1_patterns:
            reason = "legacy_w1"  # Older W1 did not require the modern closing pattern.
        elif pullback_cross:
            reason = "pullback_cross"
        else:
            trend_side = o > fast if side == "LONG" else o < fast
            reason = "wick_touch" if trend_side else "cross_candle"
    return _result(fail is None, fail, checks, level, a, reason)
