"""Signals tests. Synthetic closed-bar frames only, no terminal, no data/."""
import pandas as pd

from quant.signals import check_entry, pivot_lows


def _frame(bars):
    return pd.DataFrame([{"time": 1_700_000_000 + i * 3600, "open": o, "high": h,
                          "low": lo, "close": c} for i, (o, h, lo, c) in enumerate(bars)])


def _go_bars():
    """Calibrated E1 LONG: drift, pullback touching EMA50, young resume.

    Margins are tight by the nature of the rules (HR4 travel must fit inside
    1.5 x ATR while the trigger must cross EMA20). Deterministic: no randomness
    anywhere, so the construction is stable run to run.
    """
    s = 0.06
    closes = [100.0 + i * s for i in range(296)]
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - s
        bars.append([o, max(o, c) + 0.32, min(o, c) - 0.32, c])
    E = closes[-1]
    c = E
    for _ in range(3):
        o = c
        c -= 0.4
        bars.append([o, o + 0.1, c - 0.1, c])
    o = c
    lo = E - 1.7
    bars.append([o, o + 0.15, lo, lo + 0.15])
    c = lo + 0.15
    for _ in range(3):
        o = c
        c += 0.08
        bars.append([o, c + 0.12, o - 0.14, c])
    o = c
    c += 0.45
    bars.append([o, c + 0.15, o - 0.15, c])
    return bars, E


def _mirror(bars, k=240.0):
    return [[k - o, k - lo, k - h, k - c] for o, h, lo, c in bars]


def test_go_long_all_gates_green():
    bars, _ = _go_bars()
    r = check_entry(_frame(bars), "LONG", {})
    assert r["signal"] is True and r["fail"] is None
    assert all(r["checks"].values())


def test_go_short_mirror():
    bars, _ = _go_bars()
    r = check_entry(_frame(_mirror(bars)), "SHORT", {})
    assert r["signal"] is True and r["fail"] is None


def test_warmup_and_bad_direction():
    bars, _ = _go_bars()
    assert check_entry(_frame(bars[:100]), "LONG", {})["fail"] == "warmup"
    assert check_entry(_frame(bars), "SIDEWAYS", {})["fail"] == "direction"


def test_hr2_fails_on_doji():
    bars, _ = _go_bars()
    o, h, lo, c = bars[-1]
    bars[-1] = [c, h, lo, c]  # zero body
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "HR2"


def test_hr3_fails_on_huge_body():
    bars, E = _go_bars()
    o, h, lo, c = bars[-1]
    bars[-1] = [c - 3.0, c + 0.1, c - 3.1, c]  # body dwarfs ATR
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "HR3"


def test_hr4_fails_with_no_pivot_nearby():
    bars = []
    c = 100.0
    for i in range(310):  # monotonic grind: no pivot low ever forms
        o = c
        c += 0.3
        bars.append([o, c + 0.1, o - 0.1, c])
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "HR4"


def test_hr4_guard_trips_on_unconfirmed_lower_low():
    bars, E = _go_bars()
    bars[-1] = [E - 1.5, E - 0.95, E - 1.8, E - 1.0]  # pierces HL, closes back
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "HR4-guard"
    assert r["checks"]["HR4"] is True  # close itself is still near HL


def test_e1_setup_fails_without_touch():
    s = 0.06
    closes = [100.0 + i * s for i in range(296)]
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - s
        bars.append([o, max(o, c) + 0.32, min(o, c) - 0.32, c])
    E2 = closes[-1]
    c = E2
    for _ in range(3):  # shallow dip: extreme, but never reaches EMA50
        o = c
        c -= 0.17
        bars.append([o, o + 0.08, c - 0.08, c])
    o = c
    bars.append([o, o + 0.1, E2 - 0.7, E2 - 0.55])
    c = E2 - 0.55
    for _ in range(3):
        o = c
        c += 0.05
        bars.append([o, c + 0.08, o - 0.1, c])
    o = c
    c += 0.3
    bars.append([o, c + 0.12, o - 0.12, c])
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "E1-setup"


def test_e1_trigger_fails_on_gap_down_close():
    bars, E = _go_bars()
    o, h, lo, c = bars[-1]
    bars[-1] = [c - 0.7, c - 0.3, c - 0.8, c - 0.4]  # up candle under EMA20
    r = check_entry(_frame(bars), "LONG", {})
    assert r["fail"] == "E1-trigger"


def test_pivot_needs_strict_inequality():
    flat = pd.Series([1.0] * 20)
    assert pivot_lows(flat, 3) == []  # ties are not pivots
