"""Shared H4 trend-bias core (B1). Pure pandas, no MT5 import.

Baseline B1 (STRATEGY.md section 4): on the last CLOSED H4 bar, LONG when
EMA20 > EMA50, close > EMA50 (HR1a), and (EMA20 - EMA50) >= sep_min * ATR14
(Wilder). Mirror for SHORT. Strict inequalities: equality/doji -> NEUTRAL.
Callers must pass closed bars only, never the forming bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

EMA_FAST = 20
EMA_SLOW = 50
ATR_PERIOD = 14
SEP_MIN_DEFAULT = 0.3
MIN_BARS = 70  # slow EMA + ATR warmup plus margin


@dataclass(frozen=True)
class Bias:
    direction: str  # LONG | SHORT | NEUTRAL
    ema20: float | None
    ema50: float | None
    atr14: float | None
    sep_atr: float | None
    hr1_long: bool
    hr1_short: bool
    reason: str


def _ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def _atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ATR_PERIOD) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def h4_bias(h4: pd.DataFrame, sep_min: float = SEP_MIN_DEFAULT, hr1: str = "a",
            use_atr_sep: bool = True, min_bars: int = 300) -> Bias:
    """Bias from the last row of a closed-bar H4 frame (needs open/high/low/close).

    hr1 selects the STRATEGY.md section 4 variant: a = close past EMA50
    (baseline), b = full body past, c = whole candle past.
    use_atr_sep=False is the MA-only comparison leg: pure EMA20/50 direction,
    no separation gate, no HR1, no FLAT (ties go UP).
    min_bars is the spec warmup (warmup_bars, default 300): fewer bars -> FLAT.
    """
    variant = str(hr1).lower() if str(hr1).lower() in ("a", "b", "c") else "a"
    if h4 is None or len(h4) < max(int(min_bars), 1):
        n = 0 if h4 is None else len(h4)
        return Bias("NEUTRAL", None, None, None, None, False, False, f"warmup:bars={n}")
    close, high, low = h4["close"], h4["high"], h4["low"]
    e20 = float(_ema(close, EMA_FAST).iloc[-1])
    e50 = float(_ema(close, EMA_SLOW).iloc[-1])
    atr = float(_atr_wilder(high, low, close).iloc[-1])
    o, c = float(h4["open"].iloc[-1]), float(close.iloc[-1])
    hi, lo = float(high.iloc[-1]), float(low.iloc[-1])
    if pd.isna(e20) or pd.isna(e50) or pd.isna(atr) or atr <= 0:
        return Bias("NEUTRAL", None, None, None, None, False, False, "warmup:nan-atr")
    if variant == "b":
        hr1_long, hr1_short = min(o, c) > e50, max(o, c) < e50
    elif variant == "c":
        hr1_long, hr1_short = lo > e50, hi < e50
    else:
        hr1_long, hr1_short = c > e50, c < e50
    sep = (e20 - e50) / atr
    if not use_atr_sep:
        if e20 >= e50:
            return Bias("LONG", e20, e50, atr, sep, hr1_long, hr1_short, "ma-only:up")
        return Bias("SHORT", e20, e50, atr, sep, hr1_long, hr1_short, "ma-only:down")
    if e20 > e50 and hr1_long and sep >= sep_min:
        return Bias("LONG", e20, e50, atr, sep, True, False, f"stack+HR1{variant}+sep{sep:+.2f}")
    if e20 < e50 and hr1_short and -sep >= sep_min:
        return Bias("SHORT", e20, e50, atr, sep, False, True, f"stack+HR1{variant}+sep{sep:+.2f}")
    if e20 > e50 and not hr1_long:
        veto = f"veto:HR1{variant}"  # pullback under EMA50 while stack still up
    elif e20 < e50 and not hr1_short:
        veto = f"veto:HR1{variant}"
    elif (e20 > e50 and sep < sep_min) or (e20 < e50 and -sep < sep_min):
        veto = "veto:sep"
    else:
        veto = "veto:stack"
    return Bias("NEUTRAL", e20, e50, atr, sep, hr1_long, hr1_short, veto)
