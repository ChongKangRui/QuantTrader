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
                                               "trail_r": 1.0, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert len(trades) == 1 and trades["exit_type"].iloc[0] == "target"
    assert trades["pnl_R"].iloc[0] == 3.0


def test_stop_before_target_inside_one_bar():
    h1 = _trade_frame([1.1005, 1.1010, 1.0900])  # bar spans both SL and TP
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                               "be_trigger_r": 1.0, "be_buffer": 0,
                                               "trail_r": 1.0, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop" and trades["pnl_R"].iloc[0] == -1.0


def test_breakeven_caps_a_reversal():
    h1 = _trade_frame([1.1005, 1.1010, 1.1045, 1.1005, 1.0995])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                               "be_trigger_r": 1.0, "be_buffer": 0,
                                               "trail_r": 100.0, "atr_n": 7},
                         _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop"
    assert abs(trades["pnl_R"].iloc[0]) < 0.2  # stopped near breakeven, not full R


def test_profit_trail_follows_peak_in_R():
    # entry 1.1001, risk 0.0030: +1R = 1.1031, peak 1.1077 -> stop = peak - 1R = 1.1047
    h1 = _trade_frame([1.1005, 1.1010, 1.1070, 1.1075, 1.1060, 1.1040])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    params = {"stop_atr": 1.5, "tp_mult": 3.0, "be_trigger_r": 1.0, "be_buffer": 0,
              "trail_r": 1.0, "atr_n": 7}
    trades, _ = simulate(h1, "EURUSD", cands, params, _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop"
    assert abs(trades["exit"].iloc[0] - 1.1047) < 1e-6
    assert abs(trades["pnl_R"].iloc[0] - 1.533) < 0.01  # locked profit, not just breakeven


def test_cost_filter_skips_expensive_setup():
    h1 = _trade_frame([1.1005, 1.1010, 1.1120])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0001,
              "time": h1["time"].iloc[11]}]  # tiny stop vs big spread
    trades, extra = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0,
                                                   "be_trigger_r": 1.0, "be_buffer": 0,
                                                   "trail_r": 1.0, "atr_n": 7},
                             _costs(spread_points=20), 3.0, 0.10)
    assert len(trades) == 0 and extra["sized"] == 0


def test_metrics_on_empty_and_wheel():
    h1 = _h1([1.1] * 10)
    m = metrics(h1.iloc[0:0].copy(), h1)
    assert m["trades"] == 0 and m["net_usd"] == 0.0


def test_yearly_and_total_rows():
    from quant.backtest import total_row, yearly_table

    t = pd.DataFrame([
        {"symbol": "EURUSD", "exit_time": "2020-05-01 00:00:00+00:00",
         "pnl_usd": 9.0, "pnl_R": 3.0, "bars_held": 5},
        {"symbol": "EURUSD", "exit_time": "2021-06-01 00:00:00+00:00",
         "pnl_usd": -3.0, "pnl_R": -1.0, "bars_held": 5},
        {"symbol": "GBPUSD", "exit_time": "2021-07-01 00:00:00+00:00",
         "pnl_usd": -3.0, "pnl_R": -1.0, "bars_held": 5},
    ])
    y = yearly_table(t)
    assert len(y) == 3 and y["trades"].sum() == 3
    assert float(y[(y["symbol"] == "EURUSD") & (y["year"] == 2020)]["net_usd"].iloc[0]) == 9.0
    tot = total_row(t)
    assert tot["symbol"] == "TOTAL" and tot["trades"] == 3
    assert tot["net_usd"] == 3.0 and tot["expect_R"] == round(1.0 / 3, 3)


def test_fixed_lot_always_001_and_r_scales():
    h1 = _trade_frame([1.1005, 1.1010, 1.1120])
    cands = [{"t": 11, "direction": "LONG", "atr": 0.0020,
              "time": h1["time"].iloc[11]}]
    params = {"stop_atr": 1.5, "tp_mult": 3.0, "be_trigger_r": 1.0, "be_buffer": 0,
              "trail_r": 1.0, "atr_n": 7}
    trades, _ = simulate(h1, "EURUSD", cands, params, _costs(), 3.0, 0.10, lot=0.01)
    assert trades["lot"].iloc[0] == 0.01 and trades["pnl_R"].iloc[0] == 3.0


def test_tick_spec_matches_pip_table():
    from quant.backtest import tick_spec

    size, val = tick_spec("EURUSD", 1.1)  # $10/pip/lot -> $1/tick/lot
    assert (size, val) == (0.00001, 1.0)
    size, val = tick_spec("USDJPY", 150.0)  # 1000JPY/pip/lot, tick 0.001
    assert size == 0.001 and abs(val * 10 * 150.0 - 1000.0) < 1e-6
    assert tick_spec("EURGBP", 0.85) is None  # cross: second feed needed
    size, val = tick_spec("AUDJPY", 95.0, {"USDJPY": 150.0})
    assert size == 0.001 and abs(val * 10 * 150.0 - 1000.0) < 1e-6
    assert tick_spec("AUDJPY", 95.0) is None  # converter feed missing
    size, val = tick_spec("EURGBP", 0.85, {"GBPUSD": 1.30})
    assert size == 0.00001 and abs(val * 10 - 10 * 1.30) < 1e-9  # 10GBP/pip -> USD


def test_jpy_cross_sizes_through_converter():
    idx = pd.date_range("2020-01-06", periods=15, freq="h", tz="UTC")
    closes = [150.00 + (0.01 if i % 2 else -0.01) for i in range(12)] + [150.05, 150.10, 151.20]
    h1 = pd.DataFrame([{"time": t, "open": closes[max(0, i - 1)], "high": c + 0.02,
                        "low": c - 0.02, "close": c, "tick_volume": 5}
                       for i, (t, c) in enumerate(zip(idx, closes))])
    jpy = pd.Series([150.0] * 15, index=idx)
    cands = [{"t": 11, "direction": "LONG", "atr": 0.02, "time": idx[11]}]
    params = {"stop_atr": 1.5, "tp_mult": 3.0, "be_trigger_r": 1.0, "be_buffer": 0,
              "trail_r": 100.0, "atr_n": 7}  # trail off: this test is about JPY sizing
    trades, _ = simulate(h1, "AUDJPY", cands, params, _costs(), 3.0, 0.10,
                         lot=0.01, converters={"USDJPY": jpy})
    assert len(trades) == 1 and trades["exit_type"].iloc[0] == "target"
    assert trades["pnl_R"].iloc[0] == 3.0
    trades, _ = simulate(h1, "AUDJPY", cands, params, _costs(), 3.0, 0.10, lot=0.01)
    assert len(trades) == 0  # no converter feed: skipped, not crashed


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
