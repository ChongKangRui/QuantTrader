"""Bias core tests. Synthetic frames only, no terminal, no data/."""
import pandas as pd

from quant.bias import bias_periods, h4_bias


def _frame(closes, start_ts=1_700_000_000, step=14_400):
    rows = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - 0.3
        rows.append({"time": start_ts + i * step, "open": o, "high": max(o, c) + 0.3,
                     "low": min(o, c) - 0.3, "close": c})
    return pd.DataFrame(rows)


def test_long_bias_on_steady_uptrend():
    df = _frame([100.0 + i * 1.0 for i in range(320)])
    b = h4_bias(df)
    assert b.direction == "LONG"
    assert b.sep_atr is not None and b.sep_atr > 0.3


def test_short_bias_on_steady_downtrend():
    df = _frame([200.0 - i * 1.0 for i in range(320)])
    b = h4_bias(df)
    assert b.direction == "SHORT"


def test_flat_market_is_neutral():
    df = _frame([100.0 + (0.05 if i % 2 else -0.05) for i in range(320)])
    assert h4_bias(df).direction == "NEUTRAL"


def test_warmup_is_neutral():
    df = _frame([100.0 + i for i in range(290)])
    b = h4_bias(df)
    assert b.direction == "NEUTRAL" and b.reason.startswith("warmup")


def test_pullback_close_kills_bias_without_lookahead():
    base = [100.0 + i * 1.0 for i in range(319)]
    df = _frame(base + [60.0])  # last closed bar collapses; earlier bars untouched
    b = h4_bias(df)
    assert b.direction == "NEUTRAL" and b.reason.startswith("veto")


def test_hr1b_vetoes_body_straddling_ema50():
    base = _frame([100.0 + i * 1.0 for i in range(320)])
    e50 = h4_bias(base).ema_slow  # the actual configured slow line (default 50)
    last = {"time": 1_700_000_000 + 320 * 14_400, "open": e50 - 10.0,
            "high": e50 + 10.2, "low": e50 - 10.2, "close": e50 + 10.0}
    df = pd.concat([base, pd.DataFrame([last])], ignore_index=True)
    assert h4_bias(df, hr1="a").direction == "LONG"  # close past ema_slow is enough
    b = h4_bias(df, hr1="b")
    assert b.direction == "NEUTRAL" and b.reason == "veto:HR1b"


def test_hr1c_vetoes_wick_piercing_ema50():
    base = _frame([100.0 + i * 1.0 for i in range(320)])
    e50 = h4_bias(base).ema_slow
    last = {"time": 1_700_000_000 + 320 * 14_400, "open": e50 + 23.7,
            "high": e50 + 24.3, "low": e50 - 10.0, "close": e50 + 24.0}
    df = pd.concat([base, pd.DataFrame([last])], ignore_index=True)
    assert h4_bias(df, hr1="a").direction == "LONG"
    b = h4_bias(df, hr1="c")
    assert b.direction == "NEUTRAL" and b.reason == "veto:HR1c"


def test_unknown_hr1_variant_falls_back_to_a():
    df = _frame([100.0 + i * 1.0 for i in range(320)])
    assert h4_bias(df, hr1="zzz").direction == "LONG"


def test_periods_come_from_params_not_constants():
    df = _frame([100.0 + i * 1.0 for i in range(320)])
    # the same frame under two configured period sets -> different slow lines
    a = h4_bias(df, ema_fast=20, ema_slow=50)
    b = h4_bias(df, ema_fast=20, ema_slow=100)
    assert a.ema_slow != b.ema_slow and a.ema_fast == b.ema_fast


def test_bias_period_names_are_chart_roles_and_new_names_win():
    new = {"bias_ema_fast_period": 20, "bias_ema_slow_period": 100,
           "bias_atr_period": 14}
    old = {"h4_ema_fast": 20, "h4_ema_slow": 100, "h4_atr_n": 14}
    assert bias_periods(new) == bias_periods(old) == (20, 100, 14)
    assert bias_periods({**old, **new, "h4_ema_fast": 8,
                         "h4_ema_slow": 12, "h4_atr_n": 7}) == (20, 100, 14)


def test_ma_only_ignores_sep_and_hr1_and_never_flat():
    base = _frame([100.0 + i * 1.0 for i in range(319)])
    e50 = h4_bias(base).ema_slow  # pullback stays above the stack break
    last = {"time": 1_700_000_000 + 319 * 14_400, "open": e50 - 29.0,
            "high": e50 - 28.5, "low": e50 - 30.5, "close": e50 - 30.0}
    df = pd.concat([base, pd.DataFrame([last])], ignore_index=True)
    assert h4_bias(df).direction == "NEUTRAL"  # HR1a vetoes the dip
    b = h4_bias(df, use_atr_sep=False)
    assert b.direction == "LONG" and b.reason == "ma-only:up"


def test_ma_only_down_and_tie_goes_up():
    df = _frame([200.0 - i * 1.0 for i in range(320)])
    assert h4_bias(df, use_atr_sep=False).direction == "SHORT"
    flat = _frame([100.0] * 320)
    assert h4_bias(flat, use_atr_sep=False).direction == "LONG"  # EMA20 == EMA50 tie


def test_ma_only_warmup_stays_neutral():
    df = _frame([100.0 + i for i in range(10)])
    assert h4_bias(df, use_atr_sep=False).direction == "NEUTRAL"
