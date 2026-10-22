"""Signals tests. Synthetic closed-bar frames only, no terminal, no data/."""
import pandas as pd

from quant.signals import _ema, check_entry, pivot_lows


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


def test_entry_period_names_work_and_override_old_names():
    bars, _ = _go_bars()
    frame = _frame(bars)
    old = {"atr_n": 14, "h1_ema_fast": 60, "h1_ema_slow": 100}
    new = {"entry_atr_period": 14, "entry_ema_fast_period": 60,
           "entry_ema_slow_period": 100}
    expected = check_entry(frame, "LONG", old)
    assert check_entry(frame, "LONG", new) == expected
    conflicting = {**old, **new, "atr_n": 2, "h1_ema_fast": 2,
                   "h1_ema_slow": 2}
    assert check_entry(frame, "LONG", conflicting) == expected
    assert expected["atr"] != check_entry(frame, "LONG", {})["atr"]


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


def test_disabled_trigger_turns_setup_bar_into_signal():
    bars, E = _go_bars()
    o, h, lo, c = bars[-1]
    bars[-1] = [c - 0.7, c - 0.3, c - 0.8, c - 0.4]  # up candle under EMA20
    df = _frame(bars)
    assert check_entry(df, "LONG", {})["fail"] == "E1-trigger"
    r = check_entry(df, "LONG", {"use_e1_trigger": False})
    assert r["signal"] is True and r["fail"] is None


def test_disabled_hr3_passes_giant_body():
    bars, E = _go_bars()
    o, h, lo, c = bars[-1]
    bars[-1] = [c - 3.0, c + 0.1, c - 3.1, c]
    df = _frame(bars)
    assert check_entry(df, "LONG", {})["fail"] == "HR3"
    assert check_entry(df, "LONG", {"use_hr3": False})["fail"] != "HR3"


# ── W1 · "wick swept the fast EMA" ──────────────────────────────────────────
# 30-bar linear move: the EMA relation is aligned by construction (a falling
# series puts EMA20 below EMA100, rising puts it above); closes fix the EMAs,
# so open/high/low of the signal bar can be crafted around them exactly.

_W1_ISO = {"use_w1": True, "use_hr2": False, "use_hr3": False, "use_hr4": False,
           "use_ext": False, "use_e1_setup": False, "use_e1_trigger": False,
           "warmup_bars": 12, "lookback": 5}


def _w1_bars(side: str):
    drift = -0.5 if side == "SHORT" else 0.5
    closes = [120.0 + drift * i for i in range(30)]
    ef = float(_ema(pd.Series(closes), 20).iloc[-1])
    bars = [[closes[i - 1] if i else closes[0], closes[i] + 0.1,
             closes[i] - 0.1, closes[i]] for i in range(30)]
    if side == "SHORT":  # open below the fast EMA, wick pokes above it
        bars[-1] = [ef - 0.3, ef + 0.4, closes[-1] - 0.1, closes[-1]]
    else:                # mirror: open above, wick dips below
        bars[-1] = [ef + 0.3, closes[-1] + 0.1, ef - 0.4, closes[-1]]
    return bars, ef


def test_w1_short_sweep_enters_and_alignment_blocks():
    bars, _ef = _w1_bars("SHORT")
    r = check_entry(_frame(bars), "SHORT", dict(_W1_ISO))
    assert r["signal"] is True and r["checks"]["W1"] is True
    # EMAs point UP -> no agreement with the SHORT bias -> the sweep is void
    up_bars, _u = _w1_bars("LONG")
    r2 = check_entry(_frame(up_bars), "SHORT", dict(_W1_ISO))
    assert r2["signal"] is False and r2["fail"] == "W1"


def test_w1_long_mirror_sweep():
    bars, _ef = _w1_bars("LONG")
    r = check_entry(_frame(bars), "LONG", dict(_W1_ISO))
    assert r["signal"] is True and r["checks"]["W1"] is True
    down_bars, _d = _w1_bars("SHORT")
    r2 = check_entry(_frame(down_bars), "LONG", dict(_W1_ISO))
    assert r2["signal"] is False and r2["fail"] == "W1"


def test_w1_open_side_flag():
    bars, ef = _w1_bars("SHORT")
    iso = dict(_W1_ISO, w1_open_side=True)
    assert check_entry(_frame(bars), "SHORT", iso)["signal"] is True  # opens below
    bars2 = list(bars)
    bars2[-1] = [ef + 0.3, ef + 0.4, bars2[-1][2], bars2[-1][3]]  # opens above
    r = check_entry(_frame(bars2), "SHORT", iso)
    assert r["signal"] is False and r["fail"] == "W1"
    long_bars, ef_l = _w1_bars("LONG")
    iso_l = dict(_W1_ISO, w1_open_side=True)
    assert check_entry(_frame(long_bars), "LONG", iso_l)["signal"] is True
    lb2 = list(long_bars)
    lb2[-1] = [ef_l - 0.3, lb2[-1][1], ef_l - 0.4, lb2[-1][3]]  # opens below
    r2 = check_entry(_frame(lb2), "LONG", iso_l)
    assert r2["signal"] is False and r2["fail"] == "W1"


def test_w1_pen_depth_knob():
    bars, _ef = _w1_bars("SHORT")  # wick reaches ef + 0.4
    shallow = check_entry(_frame(bars), "SHORT", dict(_W1_ISO, w1_pen_atr=0.1))
    assert shallow["signal"] is True      # 0.4 >= 0.1 x ATR (~0.7)
    deep = check_entry(_frame(bars), "SHORT", dict(_W1_ISO, w1_pen_atr=3.0))
    assert deep["signal"] is False and deep["fail"] == "W1"  # far past the wick
    zero = check_entry(_frame(bars), "SHORT", dict(_W1_ISO, w1_pen_atr=0.0))
    assert zero["signal"] is True         # any touch counts


def test_w1_off_autopasses():
    # sweep geometry exists, but the gate is off: auto-pass, never a hidden False
    bars, _ef = _w1_bars("SHORT")
    r = check_entry(_frame(bars), "SHORT", {"warmup_bars": 12})
    assert r["checks"]["W1"] is True
    # the result object keeps the raw computed outcome visible for debugging
    on = check_entry(_frame(_w1_bars("SHORT")[0]), "SHORT", dict(_W1_ISO))
    assert on["checks"]["W1"] is True  # same bar, gate on: real pass (not auto)


def test_w1_h4_two_patterns_work_for_buys_and_sells():
    for side in ("LONG", "SHORT"):
        bars, fast = _w1_bars(side)
        params = dict(_W1_ISO, w1_touch_from_trend_side=True,
                      w1_cross_from_other_side=True)
        assert check_entry(_frame(bars), side, params)["signal"] is True
        assert check_entry(_frame(bars), side, params)["entry_reason"] == "wick_touch"

        crossed = list(bars)
        o, hi, lo, c = crossed[-1]
        crossed[-1] = ([fast - 0.3, hi, fast - 0.4, c] if side == "LONG" else
                       [fast + 0.3, fast + 0.4, lo, c])
        assert check_entry(_frame(crossed), side, params)["signal"] is True
        assert check_entry(_frame(crossed), side, params)["entry_reason"] == "cross_candle"
        assert check_entry(_frame(crossed), side, dict(
            params, w1_cross_from_other_side=False))["fail"] == "W1"
        assert check_entry(_frame(crossed), side, dict(
            params, w1_cross_from_other_side=False))["entry_reason"] == "unknown"
        assert check_entry(_frame(bars), side, dict(
            params, w1_touch_from_trend_side=False))["fail"] == "W1"
        assert check_entry(_frame(bars), side, dict(
            params, w1_touch_from_trend_side=False,
            w1_cross_from_other_side=False))["fail"] == "W1"


def test_w1_h4_rejects_wrong_close_and_open_on_ema():
    params = dict(_W1_ISO, w1_touch_from_trend_side=True,
                  w1_cross_from_other_side=True)
    for side in ("LONG", "SHORT"):
        bars, fast = _w1_bars(side)
        wrong = list(bars)
        o, hi, lo, _ = wrong[-1]
        wrong[-1] = [o, hi, lo, fast - 0.2 if side == "LONG" else fast + 0.2]
        assert check_entry(_frame(wrong), side, params)["fail"] == "W1"
        equal_close = list(bars)
        equal_close[-1] = [o, hi, lo, fast]
        assert check_entry(_frame(equal_close), side, params)["fail"] == "W1"
        at_ema = list(bars)
        at_ema[-1] = [fast, hi, lo, bars[-1][3]]
        assert check_entry(_frame(at_ema), side, params)["fail"] == "W1"
