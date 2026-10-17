"""H1 entry core (STRATEGY.md sections 5-7). Pure pandas, no MT5 import.

E1 pullback-resume plus the hard rules only (HR2/HR3/HR4/extension cap).
E2/E3 and every optional filter stay out until ablation. Evaluates at the
signal-bar close; the caller re-checks against the actual fill (spec: fill-time
re-check lives in the backtest/execution layers, which know the fill price).
"""
from __future__ import annotations

import pandas as pd

# Section-5 parameter table. Callers override per key from config.
# use_* flags switch gates off for ablation (off = gate auto-passes).
DEFAULTS = {
    "atr_n": 7,
    "ema_fast": 20,
    "ema_slow": 50,
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
FAIL_ORDER = ["HR2", "HR3", "HR4", "HR4-guard", "EXT", "E1-setup", "E1-trigger"]


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


def _result(signal: bool, fail: str | None, checks: dict, level=None, atr=None) -> dict:
    return {"signal": signal, "fail": fail, "checks": checks, "level": level, "atr": atr}


def check_entry(h1: pd.DataFrame, direction: str, params: dict | None = None) -> dict:
    """Full E1 gate for one direction on closed bars. t = last row (signal bar)."""
    p = {**DEFAULTS, **(params or {})}
    warmup = int(p["warmup_bars"])
    lookback = int(p["lookback"])
    n = int(p["pivot_n"])
    side = str(direction).upper()
    if h1 is None or len(h1) < max(warmup, lookback + 1, 2 * n + 1):
        return _result(False, "warmup", {}, None, None)
    if side not in ("LONG", "SHORT"):
        return _result(False, "direction", {}, None, None)

    close, high, low = h1["close"], h1["high"], h1["low"]
    efast = _ema(close, int(p["ema_fast"]))
    eslow = _ema(close, int(p["ema_slow"]))
    atr = _atr_wilder(high, low, close, int(p["atr_n"]))
    t = len(h1) - 1
    o, hi, lo, c = (float(h1[col].iloc[t]) for col in ("open", "high", "low", "close"))
    a = float(atr.iloc[t])
    if pd.isna(a) or a <= 0:
        return _result(False, "warmup", {}, None, None)
    body, rng = abs(c - o), hi - lo
    checks: dict[str, bool] = {}

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
        level = lh[1]

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
    fail = next((code for code in FAIL_ORDER if not checks.get(code, False)), None)
    return _result(fail is None, fail, checks, level, a)
