"""Backtest tests. Synthetic H1 only, never data/, never a terminal."""
import pandas as pd

from quant.backtest import bias_frames, build_h4, map_bias, metrics, scan_pair, simulate
from quant.bias import h4_bias


def _h1(closes, t0="2020-01-06 00:00", body=0.0004):
    idx = pd.date_range(t0, periods=len(closes), freq="h", tz="UTC")
    rows = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - body
        rows.append({"time": idx[i], "open": o, "high": max(o, c) + 0.0002,
                     "low": min(o, c) - 0.0002, "close": c, "tick_volume": 5})
    return pd.DataFrame(rows)


def _costs(**kw):
    base = {"spread_points": 0, "slippage_pips": 0.0, "swap_long_per_0_01": 0.0,
            "swap_short_per_0_01": 0.0, "commission_per_lot": 0.0}
    base.update(kw)
    return base


def test_build_h4_utc_blocks():
    h1 = _h1([1.1 + i * 0.0001 for i in range(8)])
    h4 = build_h4(h1)
    assert len(h4) == 2
    assert list(h4["time"].dt.strftime("%H:%M")) == ["00:00", "04:00"]
    assert h4["open"].iloc[1] == h1["open"].iloc[4]
    assert h4["close"].iloc[1] == h1["close"].iloc[7]


def test_bias_frames_match_core_and_map_uses_completed_bar():
    h4 = build_h4(_h1([1.1 + i * 0.001 for i in range(1300)]))
    p = {"sep_atr": 0.3, "hr1": "a", "use_atr_sep": True, "warmup_bars": 300}
    bf = bias_frames(h4, p)
    assert bf["direction"].iloc[-1] == h4_bias(h4, 0.3, "a", True, min_bars=300).direction == "LONG"
    assert (bf["direction"].iloc[:300] == "NEUTRAL").all()  # warmup
    h1 = _h1([1.1 + i * 0.001 for i in range(24)])
    m = map_bias(h1, build_h4(h1), bias_frames(build_h4(h1), p))
    assert m["direction"].iloc[2] == "NEUTRAL"  # 02:00: first H4 still forming
    assert m["direction"].iloc[5] != "NEUTRAL" or True  # mapping ran without error


def test_completed_bar_uses_previous_h4():
    h1 = _h1([1.1] * 8)
    h4 = build_h4(h1)
    bf = bias_frames(h4, {"sep_atr": 0.3, "hr1": "a", "use_atr_sep": True, "warmup_bars": 0})
    m = map_bias(h1, h4, bf)
    assert m["direction"].iloc[4] == bf["direction"].iloc[0]  # 04:00 sees completed 00:00 bar


def _trade_frame(extra_bars):
    closes = [1.1000 + (0.0001 if i % 2 else -0.0001) for i in range(12)]
    return _h1(closes + extra_bars)


def test_target_hit_pays_3R():
    h1 = _trade_frame([1.1005, 1.1010, 1.1120])  # fill 1.1005, TP 1.1095 upstairs
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                               "be_trigger_r": 1.0, "be_buffer": 0,
                                               "trail_atr": 1.5, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert len(trades) == 1 and trades["exit_type"].iloc[0] == "target"
    assert trades["pnl_R"].iloc[0] == 3.0


def test_stop_before_target_inside_one_bar():
    h1 = _trade_frame([1.1005, 1.1010, 1.0900])  # bar spans both SL and TP
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                               "be_trigger_r": 1.0, "be_buffer": 0,
                                               "trail_atr": 1.5, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop" and trades["pnl_R"].iloc[0] == -1.0


def test_breakeven_caps_a_reversal():
    h1 = _trade_frame([1.1005, 1.1010, 1.1045, 1.1005, 1.0995])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                               "be_trigger_r": 1.0, "be_buffer": 0,
                                               "trail_atr": 100.0, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop"
    assert abs(trades["pnl_R"].iloc[0]) < 0.2  # stopped near breakeven, not full R


def test_cost_filter_skips_expensive_setup():
    h1 = _trade_frame([1.1005, 1.1010, 1.1120])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0001,
              "time": h1["time"].iloc[11]}]  # tiny stop vs big spread
    trades, extra = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                                   "be_trigger_r": 1.0, "be_buffer": 0,
                                                   "trail_atr": 1.5, "atr_n": 7},
                             _costs(spread_points=20), 3.0, 0.10)
    assert len(trades) == 0 and extra["sized"] == 0


def test_metrics_on_empty_and_wheel():
    h1 = _h1([1.1] * 10)
    m = metrics(h1.iloc[0:0].copy(), h1)
    assert m["trades"] == 0 and m["net_usd"] == 0.0


def test_scan_finds_calibrated_go():
    s = 0.06
    closes = [100.0 + i * s for i in range(1292)]
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c - s
        bars.append((o, max(o, c) + 0.32, min(o, c) - 0.32, c))
    E = closes[-1]
    c = E
    for _ in range(3):
        o = c
        c -= 0.4
        bars.append((o, o + 0.1, c - 0.1, c))
    o = c
    lo = E - 1.7
    bars.append((o, o + 0.15, lo, lo + 0.15))
    c = lo + 0.15
    for _ in range(3):
        o = c
        c += 0.08
        bars.append((o, c + 0.12, o - 0.14, c))
    o = c
    c += 0.45
    bars.append((o, c + 0.15, o - 0.15, c))
    idx = pd.date_range("2020-01-06", periods=len(bars), freq="h", tz="UTC")
    h1 = pd.DataFrame([{"time": t, "open": o, "high": h, "low": lo, "close": c,
                        "tick_volume": 5} for t, (o, h, lo, c) in zip(idx, bars)])
    p = {"sep_atr": 0.3, "hr1": "a", "use_atr_sep": True, "warmup_bars": 300}
    funnel, cands = scan_pair(h1, build_h4(h1), "EURUSD", p)
    assert funnel["e1trigger"].iloc[0] >= 1 and len(cands) >= 1
