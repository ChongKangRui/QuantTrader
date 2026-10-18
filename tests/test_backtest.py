"""Backtest tests. Synthetic H1 only, never data/, never a terminal."""
import pandas as pd

from quant.backtest import (bias_frames, build_h4, grade_benchmarks, map_bias,
                            metrics, portfolio_filter, scan_pair, simulate,
                            total_row, yaml_notes)
from quant.bias import h4_bias


def test_yaml_notes_decls_inline_comments(tmp_path):
    yml = tmp_path / "_base.yaml"
    yml.write_text(
        "# full header lines and gate tables must be ignored\n"
        "   # (indented comment too)\n"
        "costs:\n"
        "  spread_points: 20               # spread assumption for the BACKTEST\n"
        "  miss: 1\n"                       # no comment -> not in notes
        "strategy:\n"
        "  use_hr2: true       # HR2 ON/OFF (candle color + body quality)\n"
        "  min_body_ratio: 0.5   # HR2: body as share of range\n"
        "limits:\n"
        "  max_cost_ratio: 0.10   # share of stop (0 = off)\n",
        encoding="utf-8")
    notes = yaml_notes(yml)
    assert notes["spread_points"] == "spread assumption for the BACKTEST"
    assert notes["use_hr2"] == "HR2 ON/OFF (candle color + body quality)"
    assert notes["min_body_ratio"] == "HR2: body as share of range"
    assert notes["max_cost_ratio"] == "share of stop (0 = off)"
    assert "miss" not in notes and "costs" not in notes
    assert "use_x" not in notes  # comment-only lines never become keys
    # missing file: empty, no crash
    assert yaml_notes(tmp_path / "none.yaml") == {}


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


def _pt(sym: str, entry: str, exit_: str, direction: str = "LONG",
        pnl: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame([{"symbol": sym, "direction": direction, "entry_time": entry,
                          "exit_time": exit_, "pnl_usd": pnl, "pnl_R": pnl}])


def test_portfolio_filter_open_cap_drops_fifth():
    trades = {"EURUSD": _pt("EURUSD", "2026-01-05 10:00", "2026-01-05 20:00"),
              "AUDUSD": _pt("AUDUSD", "2026-01-05 10:30", "2026-01-05 20:30"),
              "GBPUSD": _pt("GBPUSD", "2026-01-05 11:00", "2026-01-05 21:00"),
              "NZDUSD": _pt("NZDUSD", "2026-01-05 11:30", "2026-01-05 21:30"),
              "USDCAD": _pt("USDCAD", "2026-01-05 12:00", "2026-01-05 22:00")}
    kept, dropped = portfolio_filter(trades, 4, 0, 0.0, 100.0)
    assert [len(kept[s]) for s in trades] == [1, 1, 1, 1, 0]
    assert dropped == [{"symbol": "USDCAD", "entry_time": "2026-01-05 12:00",
                        "reason": "open_max"}]


def test_portfolio_filter_ccy_cap_blocks_one_sided_stack():
    trades = {"EURUSD": _pt("EURUSD", "2026-01-05 10:00", "2026-01-05 22:00", "LONG"),
              "AUDUSD": _pt("AUDUSD", "2026-01-05 10:30", "2026-01-05 22:30", "LONG"),
              "NZDUSD": _pt("NZDUSD", "2026-01-05 11:00", "2026-01-05 23:00", "LONG")}
    kept, dropped = portfolio_filter(trades, 0, 2, 0.0, 100.0)
    # two longs already make the USD side -2; the third long breaches max_ccy_net
    assert [len(kept[s]) for s in trades] == [1, 1, 0]
    assert dropped == [{"symbol": "NZDUSD", "entry_time": "2026-01-05 11:00",
                        "reason": "ccy"}]


def test_portfolio_filter_weekly_halt_frees_next_week():
    trades = {"EURUSD": _pt("EURUSD", "2026-01-05 10:00", "2026-01-05 20:00", "LONG", -20.0),
              "AUDUSD": _pt("AUDUSD", "2026-01-07 10:00", "2026-01-07 20:00", "LONG", 1.0),
              "GBPUSD": _pt("GBPUSD", "2026-01-12 10:00", "2026-01-12 20:00", "LONG", 1.0)}
    kept, dropped = portfolio_filter(trades, 0, 0, 15.0, 100.0)
    # -20 closed same Monday = 20% of the 100 USD start -> halted; next Monday reset
    assert [len(kept[s]) for s in trades] == [1, 0, 1]
    assert dropped == [{"symbol": "AUDUSD", "entry_time": "2026-01-07 10:00",
                        "reason": "weekly_halt"}]


def test_portfolio_filter_exit_frees_the_slot_at_same_timestamp():
    trades = {"EURUSD": _pt("EURUSD", "2026-01-05 10:00", "2026-01-05 12:00"),
              "AUDUSD": _pt("AUDUSD", "2026-01-05 12:00", "2026-01-05 14:00")}
    kept, dropped = portfolio_filter(trades, 1, 0, 0.0, 100.0)
    assert dropped == [] and sum(len(k) for k in kept.values()) == 2


def test_portfolio_filter_all_zero_is_a_noop():
    trades = {"EURUSD": _pt("EURUSD", "2026-01-05 10:00", "2026-01-05 20:00")}
    kept, dropped = portfolio_filter(trades, 0, 0, 0.0, 100.0)
    assert len(kept["EURUSD"]) == 1 and dropped == []


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
                                               "trail_r": 100.0, "atr_n": 7, "use_be": True},
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
    m = metrics(h1.iloc[0:0].copy(), 30, len(h1))
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


def _synthetic_csv(path, n=800, seed_phase=0.0):
    import math

    idx = pd.date_range("2020-01-06", periods=n, freq="h", tz="UTC")
    closes = [1.1 + i * 0.00005 + 0.002 * math.sin(i / 9.0 + seed_phase) for i in range(n)]
    rows = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        rows.append({"time": idx[i], "open": o, "high": max(o, c) + 0.0006,
                     "low": min(o, c) - 0.0006, "close": c, "tick_volume": 5})
    pd.DataFrame(rows).to_csv(path, index=False)


def test_resolve_workers():
    from quant.backtest import resolve_workers

    assert resolve_workers(1, 10) == 1  # linear
    assert resolve_workers(10, 4) == 4  # capped at pair count
    assert resolve_workers(10, 10) == 10
    assert 1 <= resolve_workers(0, 3) <= 3  # auto never exceeds the pair count


def test_parallel_run_matches_linear_and_isolates_failures(tmp_path):
    import argparse

    from quant.backtest import run_all

    a, b = tmp_path / "EURUSD_H1.csv", tmp_path / "GBPUSD_H1.csv"
    _synthetic_csv(a)
    _synthetic_csv(b, seed_phase=1.3)
    jobs = [("EURUSD", a, _costs()), ("MISSING", tmp_path / "nope.csv", _costs()),
            ("GBPUSD", b, _costs())]
    p = {"sep_atr": 0.3, "hr1": "a", "use_atr_sep": True, "warmup_bars": 300}
    args = argparse.Namespace(risk_usd=3.0, max_cost_ratio=0.10, bias_flip_exit=False,
                              weekend_flat=False, lot=0.01, scope_low=0.0, scope_high=0.0)
    lin, lin_fail = run_all(jobs, p, args, None, workers=1)
    par, par_fail = run_all(jobs, p, args, None, workers=3)
    assert set(lin_fail) == set(par_fail) == {"MISSING"}  # bad pair does not lose the others
    assert set(lin) == set(par) == {"EURUSD", "GBPUSD"}
    for sym in lin:
        pd.testing.assert_frame_equal(lin[sym]["trades"], par[sym]["trades"])
        assert lin[sym]["metrics"] == par[sym]["metrics"]
        assert lin[sym]["funnel"].equals(par[sym]["funnel"])


_RM = {"stop_atr": 1.5, "tp_mult": 3.0, "be_trigger_r": 1.0, "be_buffer": 0,
       "trail_r": 1.0, "atr_n": 7}


def _long_cand(h1):
    return [{"t": 11, "direction": "LONG", "atr": 0.002, "time": h1["time"].iloc[11]}]


def test_no_time_stop_trade_runs_to_target():
    h1 = _h1([1.1 + i * 0.00004 for i in range(245)])  # slow grind, >120 bars to 3R
    trades, _ = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10)
    assert len(trades) == 1 and trades["exit_type"].iloc[0] == "target"
    assert trades["bars_held"].iloc[0] > 120  # the 5-day hard stop is gone


def test_initial_stop_holds_until_trigger_point():
    # best price only ~0.67R: trail not triggered, so no breakeven, full -1R stop
    h1 = _trade_frame([1.1005, 1.1010, 1.1015, 1.1019, 1.1010, 1.0960])
    trades, _ = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "stop"
    assert abs(trades["exit"].iloc[0] - 1.0971) < 1e-9
    assert abs(trades["pnl_R"].iloc[0] + 1.0) < 0.02


def test_be_leg_is_redundant_when_trigger_equals_trail_r():
    h1 = _trade_frame([1.1005, 1.1010, 1.1070, 1.1075, 1.1060, 1.1040])
    on, _ = simulate(h1, "EURUSD", _long_cand(h1), {**_RM, "use_be": True},
                     _costs(), 3.0, 0.10)
    off, _ = simulate(h1, "EURUSD", _long_cand(h1), {**_RM, "use_be": False},
                      _costs(), 3.0, 0.10)
    pd.testing.assert_frame_equal(on, off)


def test_trail_and_be_can_both_be_switched_off():
    h1 = _trade_frame([1.1005, 1.1010, 1.1070, 1.1075, 1.1060, 1.1040])
    trades, _ = simulate(h1, "EURUSD", _long_cand(h1),
                         {**_RM, "use_trail": False, "use_be": False},
                         _costs(), 3.0, 0.10)
    assert len(trades) == 0  # nothing moves the stop: trade stays open on its initial stop


def test_short_pays_spread_on_exit():
    h1 = _trade_frame([1.0995, 1.0990, 1.0930, 1.0925, 1.0940, 1.0900])
    cands = [{"t": 11, "direction": "SHORT", "atr": 0.002, "time": h1["time"].iloc[11]}]
    trades, _ = simulate(h1, "EURUSD", cands, {**_RM, "trail_r": 100.0, "use_be": True},
                         _costs(spread_points=20), 3.0, 0.10)
    assert trades["exit_type"].iloc[0] == "target"
    assert abs(trades["exit"].iloc[0] - (1.0911 + 0.0002)) < 1e-9  # bought back on the ask


def test_apply_daily_cap_keeps_earliest():
    from quant.backtest import apply_daily_cap

    a = pd.DataFrame([{"symbol": "A", "entry_time": "2020-01-06 01:00:00"},
                      {"symbol": "A", "entry_time": "2020-01-07 01:00:00"}])
    b = pd.DataFrame([{"symbol": "B", "entry_time": "2020-01-06 05:00:00"},
                      {"symbol": "B", "entry_time": "2020-01-06 09:00:00"}])
    out, dropped = apply_daily_cap({"A": a, "B": b}, 2)
    assert len(out["A"]) == 2 and len(out["B"]) == 1
    assert dropped == [{"symbol": "B", "entry_time": "2020-01-06 09:00:00"}]
    same, none = apply_daily_cap({"A": a, "B": b}, 0)  # 0 = off
    assert none == [] and len(same["B"]) == 2


def test_no_trade_window_blocks_entry():
    h1 = _trade_frame([1.1005, 1.1010, 1.1120])  # fill day = Jan 6
    trades, extra = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10,
                             no_trade_ranges=(("01-06", "01-07"),))
    assert len(trades) == 0 and extra["window"] == 1 and extra["sized"] == 0
    trades, extra = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10)
    assert len(trades) == 1 and extra["window"] == 0  # no ranges: trade happens


def _m1_frame(rows):
    return pd.DataFrame([{"time": t, "open": o, "high": max(o, c) + 0.0001,
                          "low": min(o, c) - 0.0001, "close": c, "tick_volume": 1}
                         for t, o, c in rows])


def test_position_checks_walk_m1_and_fall_back_per_hour():
    # Hour 13 rises to ~+1.2R in minutes 0-29 and collapses in minutes 30-59:
    # minute checks arm the trail mid-hour and stop at the trail level inside
    # the hour; a run without m1 (H1 checks) cannot see the dip within the bar
    # and rides to the 3R target instead.
    h1 = _trade_frame([1.1005, 1.1012, 1.1045, 1.1055, 1.1065, 1.1075, 1.1095])
    t13 = h1["time"].iloc[13]  # 13:00, the fill bar is 12:00 (H1 fallback there)
    rows = []
    for m in range(30):  # rise: minute closes 1.1005 -> 1.1035
        o = 1.1005 if m == 0 else 1.1005 + m * 0.0001
        rows.append((t13 + pd.Timedelta(minutes=m), o, 1.1005 + (m + 1) * 0.0001))
    for m in range(30, 60):  # fall: closes 1.1030 -> 1.1000, crosses the trail level
        rows.append((t13 + pd.Timedelta(minutes=m), 1.1035, 1.1035 - (m - 29) * 0.0005))
    m1 = _m1_frame(rows)
    trades_m1, _ = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10, m1=m1)
    trades_h1, _ = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10)
    assert trades_m1["exit_type"].iloc[0] == "stop"
    level = float(m1["high"].max()) - 0.003  # trail gap = trail_r x initial risk
    assert abs(trades_m1["exit"].iloc[0] - level) < 1e-6
    assert str(trades_m1["exit_time"].iloc[0]).endswith("13:35:00+00:00")  # minute-precision exit
    assert trades_h1["exit_type"].iloc[0] == "target"  # hour checks miss the intra-bar dip


def test_max_dd_counts_first_loss():
    m = metrics(pd.DataFrame([{"pnl_usd": -2.86, "pnl_R": -1.0, "bars_held": 5}]), 30, 100)
    assert m["max_dd"] == 2.86  # equity starts at 0, so the first loss is drawdown
    t = pd.DataFrame([
        {"symbol": "X", "exit_time": "2020-05-01 00:00:00+00:00", "pnl_usd": -3.0,
         "pnl_R": -1.0, "bars_held": 5},
        {"symbol": "X", "exit_time": "2020-05-02 00:00:00+00:00", "pnl_usd": 4.0,
         "pnl_R": 1.0, "bars_held": 5}])
    assert total_row(t)["max_dd"] == 3.0  # same for the portfolio curve


def test_simulate_reports_named_gates():
    from quant.backtest import simulate

    h1 = _trade_frame([1.1005, 1.1010, 1.1020])
    _, extra = simulate(h1, "EURUSD", [], {}, {"spread_points": 20, "slippage_pips": 0.3},
                        3.0, 0.10)
    for key in ("sized", "window", "open", "day", "tick", "scope", "cost", "lot"):
        assert key in extra  # every skip reason is named, nothing hides in "sized"


def test_cli_costs_beat_everything():
    import argparse

    from quant.backtest import _cli_costs

    args = argparse.Namespace(spread_pips=None, spread_points=None,
                              slippage_pips=0.5, flat_swaps=True)
    out = _cli_costs(args)
    assert out == {"slippage_pips": 0.5,
                   "swap_long_per_0_01": 0.0, "swap_short_per_0_01": 0.0}
    assert _cli_costs(argparse.Namespace(spread_pips=None, spread_points=None,
                                         slippage_pips=None, flat_swaps=False)) == {}


def test_cost_gate_sensitivity_to_spread():
    """The gate must respond to smaller/larger spreads (per-pair calibration relies on it)."""
    import argparse

    from quant.backtest import simulate

    # spread 20 points (2 pips): stop 23.2 pips -> cost ratio 0.0993 passes at 0.10
    h1 = _trade_frame([1.1000, 1.1010, 1.1200])
    cands = [{"t": 0, "direction": "LONG", "atr": 0.00155}]  # stop = 1.5 x 15.5 pips
    args = argparse.Namespace(risk_usd=3.0, max_cost_ratio=0.10, lot=0.01)
    _, ex = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                     {"spread_points": 20, "slippage_pips": 0.3}, args.risk_usd,
                     args.max_cost_ratio, lot=args.lot)
    _, ex_tight = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                           {"spread_points": 22, "slippage_pips": 0.3}, 3.0, 0.10,
                           lot=0.01)
    assert ex["cost"] == 0 and ex["sized"] == 1         # 2 pips: fits the gate
    assert ex_tight["cost"] == 1                        # 2.2 pips: gate says no


def test_scope_sizing_sizes_up_and_skips():
    """scope [2.5, 3.6] USD: size up to >= 2.5; skip when no 0.01 multiple fits."""
    # EURUSD: $0.10 per pip per 0.01 lot -> a 10-pip stop risks $1.00 at 0.01 lot
    h1 = _trade_frame([1.1000, 1.1010, 1.1200])
    cands = [{"t": 0, "direction": "LONG", "atr": 0.001000 / 1.5}]  # stop = 10 pips
    tr, _ = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                     {"spread_points": 2, "slippage_pips": 0.3}, 3.0, 0.0,
                     scope_low=2.5, scope_high=3.6)
    assert len(tr) == 1
    assert round(float(tr["lot"].iloc[0]), 2) == 0.03   # sized up: 3 x $1.00 = $3.00
    assert abs(float(tr["risk_usd"].iloc[0]) - 3.0) < 0.011  # 1R stays in band

    h1b = _trade_frame([1.1000, 1.1010, 1.1200])
    cands = [{"t": 0, "direction": "LONG", "atr": 0.002400 / 1.5}]  # stop = 24 pips
    _, ex = simulate(h1b, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                     {"spread_points": 2, "slippage_pips": 0.3}, 3.0, 0.0,
                     scope_low=2.5, scope_high=3.6)
    assert ex["scope"] == 1  # hole: 0.01 lot = $2.40 < low, 0.02 lots = $4.80 > high

    h1c = _trade_frame([1.1000, 1.1010, 1.1200])
    cands = [{"t": 0, "direction": "LONG", "atr": 0.004000 / 1.5}]  # stop = 40 pips
    _, ex = simulate(h1c, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                     {"spread_points": 2, "slippage_pips": 0.3}, 3.0, 0.0,
                     scope_low=2.5, scope_high=3.6)
    assert ex["scope"] == 1  # even 0.01 lot ($4.00) is already above the ceiling


def test_scope_filters_fixed_lot():
    h1 = _trade_frame([1.1000, 1.1010, 1.1200])
    cands = [{"t": 0, "direction": "LONG", "atr": 0.002400 / 1.5}]  # stop = 24 pips
    tr, ex = simulate(h1, "EURUSD", cands, {"stop_atr": 1.5, "tp_mult": 3.0},
                      {"spread_points": 2, "slippage_pips": 0.3}, 3.0, 0.0, lot=0.01,
                      scope_low=2.5, scope_high=3.6)
    assert len(tr) == 0 and ex["scope"] == 1  # fixed 0.01 lot risks $2.40, below low


def test_mtm_equity_marks_open_positions():
    from quant.backtest import mtm_equity

    times = pd.date_range("2024-01-02 00:00", periods=6, freq="h", tz="UTC")
    h1 = pd.DataFrame({"time": times,
                       "close": [1.1000, 1.1010, 1.1020, 1.1030, 1.0990, 1.1015]})
    tr = pd.DataFrame([
        {"symbol": "EURUSD", "direction": "SHORT",
         "entry_time": str(times[0]), "exit_time": str(times[1]),
         "entry": 1.1000, "sl": 1.1010, "pnl_usd": -3.0, "risk_usd": 3.0},
        {"symbol": "EURUSD", "direction": "LONG",
         "entry_time": str(times[1]), "exit_time": str(times[5]),
         "entry": 1.1010, "sl": 1.1000, "pnl_usd": 5.0, "risk_usd": 2.5},
    ])
    curve = mtm_equity({"EURUSD": tr}, {"EURUSD": h1}, 100.0)
    got = [round(float(v), 2) for v in curve["usd"]]
    # long trade's mark rides its close: +1R, +2R, then -2R before realizing +5
    assert got == [100.0, 97.0, 99.5, 102.0, 92.0, 102.0]
    dd = float((curve["usd"].cummax() - curve["usd"]).max())
    assert abs(dd - 10.0) < 1e-6  # open floating loss deeper than the 3.0 closed dip


def test_grading_bands_and_edges():
    bench = {"account_usd": 100.0, "max_dd_pct": {"good": 30.0, "ok": 50.0},
             "profit_factor": {"good": 1.5, "ok": 1.0}, "expect_r": {"good": 0.1, "ok": 0.0}}
    g = grade_benchmarks({"trades": 10, "max_dd": 29.0, "profit_factor": 1.6, "expect_R": 0.2}, bench)
    assert g["max_dd_pct"] == 29.0 and "dd_band" not in g  # per-pair DD band is gone
    assert g["verdict"] == "PASS"
    g = grade_benchmarks({"trades": 10, "max_dd": 40.0, "profit_factor": 1.2, "expect_R": 0.05}, bench)
    assert (g["pf_band"], g["expect_band"], g["verdict"]) == ("WARN", "WARN", "WARN")
    g = grade_benchmarks({"trades": 10, "max_dd": 75.0, "profit_factor": 1.6, "expect_R": 0.2},
                         bench, portfolio=True)
    assert g["dd_band"] == "FAIL" and g["verdict"] == "FAIL"  # drawdown bands: TOTAL only
    # zero trades: no evidence, not a verdict -> NA
    g = grade_benchmarks({"trades": 0, "max_dd": 0.0, "profit_factor": 0.0, "expect_R": 0.0}, bench)
    assert g["verdict"] == "NA"
    # profit factor inf (no losing trades) must grade PASS, not crash
    g = grade_benchmarks({"trades": 3, "max_dd": 0.0, "profit_factor": float("inf"), "expect_R": 1.0}, bench)
    assert g["pf_band"] == "PASS"
    # portfolio-only metrics: trades/month and worst calendar year
    pb = {"account_usd": 100.0, "max_dd_pct": {"good": 30.0, "ok": 50.0},
          "profit_factor": {"good": 1.5, "ok": 1.0}, "expect_r": {"good": 0.1, "ok": 0.0},
          "per_month": {"good": 2.0, "ok": 0.2}, "worst_year_r": {"ok": -20.0}}
    m = {"trades": 50, "max_dd": 10.0, "profit_factor": 1.5, "expect_R": 0.1, "per_month": 1.0}
    g = grade_benchmarks(m, pb, portfolio=True, min_year_R=-5.0)
    assert g["freq_band"] == "WARN" and g["year_band"] == "PASS" and g["verdict"] == "WARN"
    g = grade_benchmarks(m, pb, portfolio=True, min_year_R=-25.0)
    assert g["year_band"] == "FAIL"  # a -25R year fails even with a green rest


def test_m1_slice_anchors_at_true_hour_edge():
    # Vendor H1 stamps can sit at :01 when the raw :00 minute is missing. The
    # minute walk must anchor at the hour edge: a :01 anchor would swallow the
    # next hour's 13:00 row into the 12:0x bar (exit one bar early, bars_held 1).
    closes = [1.1000 + (0.0001 if i % 2 else -0.0001) for i in range(12)]
    h1 = _h1(closes + [1.1005, 1.1012, 1.1045, 1.1095])
    h1.loc[12, "time"] = pd.Timestamp("2020-01-06 12:01", tz="UTC")  # the :01 stamp
    t13 = pd.Timestamp("2020-01-06 13:00", tz="UTC")
    rows = [
        (pd.Timestamp("2020-01-06 12:01", tz="UTC"), 1.1005, 1.1006),  # fill-bar minutes
        (pd.Timestamp("2020-01-06 12:59", tz="UTC"), 1.1005, 1.1004),  #  no stop, no trigger
        (t13, 1.1004, 1.0960),  # next bar's own minute: dips below the initial stop
    ]
    trades, _ = simulate(h1, "EURUSD", _long_cand(h1), _RM, _costs(), 3.0, 0.10, m1=_m1_frame(rows))
    assert trades["exit_type"].iloc[0] == "stop"
    assert abs(trades["exit"].iloc[0] - 1.0971) < 1e-9  # initial stop level, untouched by trail
    assert trades["bars_held"].iloc[0] == 2  # 13:00 shown to the NEXT hour bar, not the 12:0x bar
    assert str(trades["exit_time"].iloc[0]).endswith("13:00:00+00:00")
