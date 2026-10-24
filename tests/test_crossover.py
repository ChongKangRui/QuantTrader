"""Crossover memory and actual-fill admission. Synthetic bars and mocked MT5 only."""
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from quant import signals, trader
from quant.backtest import portfolio_filter, scan_pair, simulate
from quant.monitor import flatten_strategy, load_pairs, read_limits, read_timeframes, read_trade_cfg
from tests.test_backtest import _pt
from tests.test_trader import MAGIC, NOW, _FakeMT5, cfg


PARAMS = {
    "use_crossover_memory": True, "crossover_max_entries": 2,
    "crossover_history_bars": 200, "warmup_bars": 9,
    "entry_ema_fast_period": 3, "entry_ema_slow_period": 9,
    "bias_ema_fast_period": 3, "bias_ema_slow_period": 9,
    "entry_atr_period": 3, "bias_atr_period": 3, "use_atr_sep": False,
    "use_recovery_entry": True, "recovery_use_zone_memory": True,
    "recovery_use_wick": False, "recovery_cancel_beyond_slow": False,
    "stop_atr": 1.5, "tp_mult": 10, "use_trail": True, "trail_r": 1.5,
}


def _bars(side="LONG"):
    closes = list(pd.Series(range(30)).map(lambda i: 20 - i * 10 / 29))
    closes += [10 + i * 10 / 59 for i in range(60)]
    closes += [19.45, 20.4, 19.7, 20.6, 19.9, 20.8]
    if side == "SHORT":
        closes = [40 - c for c in closes]
    closes = pd.Series([1 + c * 0.001 for c in closes])
    return pd.DataFrame({"time": pd.date_range(end=NOW - timedelta(hours=4),
                                              periods=len(closes), freq="4h"),
                         "open": closes, "high": closes + 0.00005,
                         "low": closes - 0.00005, "close": closes})


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_historical_cross_and_fresh_recovery_for_each_entry(side):
    bars = _bars(side)
    records, state = signals.crossover_signals(bars, PARAMS)
    fired = [r for r in records if r["signal"]]
    assert len(fired) >= 3
    assert all(r["direction"] == side for r in fired[-3:])
    assert len({r["crossover_time"] for r in fired[-3:]}) == 1
    assert pd.Timestamp(state["crossover_time"]) < bars.time.iloc[-6]
    assert all(pd.Timestamp(r["crossover_time"]) < pd.Timestamp(r["time"]) for r in fired)
    _, cands = scan_pair(bars, bars, "EURUSD", PARAMS, reg_hours=4, exec_hours=4)
    assert [str(c["time"]) for c in cands] == [str(pd.Timestamp(r["time"])) for r in fired]


def test_memory_matches_full_replay_after_restart_and_window_rollover():
    bars = _bars()
    records, full = signals.crossover_signals(bars, PARAMS)
    _, saved = signals.crossover_signals(bars.iloc[:-5], PARAMS)
    for i in range(len(bars) - 5, len(bars)):
        fresh, saved = signals.crossover_signals(bars.iloc[i-1:i+1], PARAMS, saved)
        assert fresh == [records[i]]
    assert saved == full
    assert signals.crossover_signals(bars.iloc[-2:], PARAMS, saved) == ([], saved)


def test_prefixes_never_read_future_crosses_or_recoveries():
    bars = _bars()
    records, _ = signals.crossover_signals(bars, PARAMS)
    for n in (10, 30, 40, 70, 91, 92, 94, 96):
        prefix, _ = signals.crossover_signals(bars.iloc[:n], PARAMS)
        assert prefix[-1] == records[n-1]


def test_initial_alignment_and_equal_emas_do_not_invent_a_cross():
    bars = _bars().iloc[:25].copy()
    assert signals.crossover_signals(bars, PARAMS)[1].get("crossover_time") is None
    bars.loc[:, ["open", "high", "low", "close"]] = 1.1
    assert signals.crossover_signals(bars, PARAMS)[1].get("crossover_time") is None


def test_opposite_cross_starts_new_memory():
    bars = _bars()
    _, saved = signals.crossover_signals(bars, PARAMS)
    tail = bars.iloc[-1:].copy()
    tail["time"] += pd.Timedelta(hours=4)
    tail.loc[:, ["open", "high", "low", "close"]] = 0.9
    _, state = signals.crossover_signals(pd.concat([bars.iloc[-1:], tail]), PARAMS, saved)
    assert state["direction"] == "SHORT"
    assert state["crossover_time"] != saved["crossover_time"]
    assert not state["latest"]["signal"]


def test_temporary_neutral_bias_keeps_the_same_crossover():
    bars = _bars().iloc[:-6].copy()
    params = {**PARAMS, "use_atr_sep": True, "sep_atr": 0}
    _, saved = signals.crossover_signals(bars, params)
    tail = bars.iloc[-1:].copy()
    tail["time"] += pd.Timedelta(hours=4)
    tail["open"] = tail["close"] = 1.0191
    tail["high"], tail["low"] = 1.01915, 1.01905
    _, state = signals.crossover_signals(pd.concat([bars.iloc[-1:], tail]), params, saved)
    assert state["crossover_time"] == saved["crossover_time"]
    assert state["direction"] == "LONG"
    # Regime settings cannot alter execution crossover/recovery mechanics.
    other = {**params, "bias_ema_fast_period": 5, "bias_ema_slow_period": 20,
             "bias_atr_period": 25, "sep_atr": 100, "hr1": "c"}
    assert signals.crossover_signals(_bars(), other)[0] == signals.crossover_signals(_bars(), params)[0]


def test_missing_overlap_and_changed_settings_refused():
    bars = _bars()
    _, saved = signals.crossover_signals(bars.iloc[:-5], PARAMS)
    with pytest.raises(ValueError, match="overlap"):
        signals.crossover_signals(bars.iloc[-2:], PARAMS, saved)
    with pytest.raises(ValueError, match="settings changed"):
        signals.crossover_signals(bars, {**PARAMS, "recovery_use_wick": True}, saved)


@pytest.mark.parametrize("key,value", [
    ("use_crossover_memory", "false"), ("crossover_max_entries", 0),
    ("crossover_max_entries", True), ("crossover_max_entries", 2.5),
    ("crossover_history_bars", 5), ("use_recovery_entry", False),
    ("recovery_use_zone_memory", "false"),
])
def test_invalid_controls_fail_closed(key, value):
    with pytest.raises(ValueError):
        signals.validate_crossover({**PARAMS, key: value})


def _trades(rows, cycle="2026-10-01 00:00Z"):
    trades = pd.concat([_pt("EURUSD", *r) for r in rows], ignore_index=True)
    trades["crossover_time"] = cycle
    return trades


def test_only_accepted_fills_count_and_same_pair_never_overlaps():
    trades = _trades([
        ("2026-10-12 01:00", "2026-10-12 05:00"),
        ("2026-10-12 02:00", "2026-10-12 06:00"),
        ("2026-10-12 05:00", "2026-10-12 07:00"),
        ("2026-10-13 01:00", "2026-10-13 02:00"),
        ("2026-10-14 01:00", "2026-10-14 02:00"),
    ])
    trades.loc[4, "crossover_time"] = "2026-10-14 00:00Z"
    kept, drops = portfolio_filter({"EURUSD": trades}, 0, 0, 0, crossover_max_entries=2)
    assert len(kept["EURUSD"]) == 3
    assert [d["reason"] for d in drops] == ["pair_open", "crossover_cap"]
    assert len(portfolio_filter({"EURUSD": trades.iloc[:4]}, 0, 0, 0,
                                crossover_max_entries=3)[0]["EURUSD"]) == 3


def test_weekly_halt_does_not_use_a_try_or_mask_next_week_entry():
    trades = _trades([
        ("2026-10-12 02:00", "2026-10-20 01:00"),
        ("2026-10-19 02:00", "2026-10-19 03:00"),
        ("2026-10-20 02:00", "2026-10-20 03:00"),
        ("2026-10-21 02:00", "2026-10-21 03:00"),
    ])
    other = _pt("AUDUSD", "2026-10-12 00:00", "2026-10-12 01:00", "LONG", -3)
    other["crossover_time"] = "2026-10-01 00:00Z"
    kept, drops = portfolio_filter({"EURUSD": trades, "AUDUSD": other},
                                   0, 0, 3, crossover_max_entries=2)
    assert list(kept["EURUSD"].entry_time) == ["2026-10-19 02:00", "2026-10-20 02:00"]
    assert [d["reason"] for d in drops] == ["weekly_halt", "crossover_cap"]


def test_independent_lifecycles_keep_same_day_candidates_for_admission():
    bars = _bars().iloc[-6:].reset_index(drop=True)
    cands = [{"t": i, "direction": "LONG", "atr": 0.01,
              "crossover_time": "2026-01-01T00:00:00+00:00"} for i in (0, 1, 2)]
    costs = {"spread_points": 0, "slippage_pips": 0}
    trades, _ = simulate(bars, "EURUSD", cands, PARAMS, costs, 3, 0,
                          default_lot=0.01, independent_candidates=True, bar_hours=4,
                          coarse_exit_at_close=True)
    assert len(trades) == 3
    assert set(trades.exit_type) == {"end-of-data"}
    kept, drops = portfolio_filter({"EURUSD": trades}, 0, 0, 0, crossover_max_entries=2)
    assert len(kept["EURUSD"]) == 1
    assert [d["reason"] for d in drops] == ["pair_open", "pair_open"]


class _CrossMT5(_FakeMT5):
    def __init__(self):
        super().__init__()
        self.frame = _bars()
        self.history = []
        self.queries = []

    def copy_rates_from_pos(self, symbol, tf, start, n):
        assert start == 1 and tf == trader.TIMEFRAME_H4
        frame = self.frame.iloc[-n:].copy()
        frame["time"] = frame.time.map(lambda t: int(t.timestamp()))
        return frame.to_dict("records")

    def history_deals_get(self, date_from, date_to):
        self.queries.append((date_from, date_to))
        return self.history


def _live(mt5, mem, tmp_path, dry=True, direction="LONG", **over):
    config = cfg(max_trades_per_day=0, max_total_positions=0, max_ccy_net=0,
                 max_cost_ratio=0, scope_low=0, scope_high=0, default_lot=0.01,
                 exec_tf="H4", memory_path=tmp_path / "memory.json", **over)
    return trader.trade_on_bar(mt5, "EURUSD", "EURUSD", direction,
        int(mt5.frame.time.iloc[-1].timestamp()), NOW, magic=MAGIC, dry=dry,
        params=PARAMS, journal_path=tmp_path / "journal.csv", mem=mem,
        cfg=config, deals=(), ranges=())


def _history(mt5, count):
    mt5.history = [mt5.deal(position_id=i+1,
                           time_=(NOW-timedelta(hours=12+i*8)).timestamp()) for i in range(count)]


def test_live_restores_historical_cross_and_counts_distinct_actual_positions(tmp_path):
    mt5, mem = _CrossMT5(), {}
    _history(mt5, 1)
    mt5.history += mt5.history  # Partial fills/deal duplicates count as one position.
    assert _live(mt5, mem, tmp_path).startswith("PLAN")
    state = mem["crossovers"]["EURUSD"]
    assert state["used"] == 1
    assert mt5.queries[0][0] < NOW - timedelta(days=5)
    assert not mt5.sent
    _history(mt5, 2)
    assert "crossover-cap" in _live(mt5, {}, tmp_path)


def test_dry_run_and_explicit_failed_send_do_not_use_tries(tmp_path):
    mt5, mem = _CrossMT5(), {}
    assert _live(mt5, mem, tmp_path).startswith("PLAN")
    assert mem["crossovers"]["EURUSD"]["used"] == 0
    mem["bars"].clear()
    mt5.fail_open = True
    assert _live(mt5, mem, tmp_path, dry=False).startswith("ORDER FAILED")
    assert mem["crossovers"]["EURUSD"]["used"] == 0
    assert not mem["crossovers"]["EURUSD"].get("pending_bar")
    assert not mem["bars"]


def test_confirmed_fill_persisted_before_position_discovery(tmp_path):
    mt5, mem = _CrossMT5(), {}
    assert _live(mt5, mem, tmp_path, dry=False).startswith("ORDER")
    saved = trader.load_mem(tmp_path / "memory.json")
    assert saved["crossovers"]["EURUSD"]["used"] == 1
    assert saved["bars"] == mem["bars"]
    assert _live(mt5, saved, tmp_path, dry=False) == "seen"
    assert len(mt5.sent) == 1


def test_crash_recovery_blocks_duplicate_even_if_filled_position_already_closed(tmp_path):
    mt5 = _CrossMT5()
    mt5.history = [mt5.deal(time_=NOW.timestamp())]
    assert _live(mt5, {}, tmp_path, dry=False) == "seen"
    assert not mt5.sent


def test_ambiguous_send_and_missing_history_fail_closed(tmp_path):
    mt5, mem = _CrossMT5(), {}
    mt5.order_send = lambda req: None
    assert _live(mt5, mem, tmp_path, dry=False).startswith("ORDER UNCONFIRMED")
    saved = trader.load_mem(tmp_path / "memory.json")
    assert "unresolved crossover order" in _live(mt5, saved, tmp_path, dry=False)
    mt5.history = None
    assert "deal history unavailable" in _live(mt5, saved, tmp_path)


@pytest.mark.parametrize("retcode", [10008, 10010, 10012, 10031, 123456])
def test_partial_placed_timeout_and_unknown_results_keep_pending_guard(tmp_path, retcode):
    from types import SimpleNamespace

    mt5, mem = _CrossMT5(), {}
    mt5.order_send = lambda req: SimpleNamespace(retcode=retcode)
    assert "ORDER UNCONFIRMED" in _live(mt5, mem, tmp_path, dry=False)
    saved = trader.load_mem(tmp_path / "memory.json")
    assert saved["crossovers"]["EURUSD"]["pending_bar"]
    assert "unresolved crossover order" in _live(mt5, saved, tmp_path, dry=False)


def test_open_other_magic_and_unavailable_positions_block_new_entry(tmp_path):
    mt5 = _CrossMT5()
    mt5._positions = [type("Position", (), {"magic": MAGIC+1, "symbol": "EURUSD"})()]
    assert "pair-open" in _live(mt5, {}, tmp_path)
    mt5.positions_get = lambda **kw: None
    assert "DATA ERROR - crossover positions" in _live(mt5, {}, tmp_path)
    assert not mt5.sent


def test_wider_history_can_find_cross_older_than_original_startup_window(tmp_path):
    mt5, mem = _CrossMT5(), {}
    bars = mt5.frame
    # First startup has only the late, already-aligned part of the trend.
    mt5.frame = bars.iloc[60:-6]
    old_bar = int(mt5.frame.time.iloc[-1].timestamp())
    first = trader._crossover_check(mt5, "EURUSD", "EURUSD", PARAMS,
                                    {"exec_tf": "H4"}, mem, MAGIC, NOW, old_bar)
    assert first["blocked"] == "crossover-memory"
    mt5.frame = bars
    latest = trader._crossover_check(mt5, "EURUSD", "EURUSD", PARAMS,
        {"exec_tf": "H4"}, mem, MAGIC, NOW, int(bars.time.iloc[-1].timestamp()))
    assert latest["crossover_time"] and latest["blocked"] is None


def test_missing_startup_cross_never_grants_entries(tmp_path):
    mt5 = _CrossMT5()
    mt5.frame = mt5.frame.iloc[60:-6]
    assert "crossover-memory" in _live(mt5, {}, tmp_path)
    assert not mt5.sent


def test_live_hours_blackout_weekly_halt_keep_tries_unused(tmp_path):
    mt5 = _CrossMT5()
    for extra, expected in [({"halted": True}, "weekly-halt"),
        ({"entry_hours": {"enabled": True, "start": "01:00", "end": "02:00"}}, "entry-hours")]:
        mem = {}
        assert expected in _live(mt5, mem, tmp_path, **extra)
        assert mem["crossovers"]["EURUSD"]["used"] == 0
    mem = {}
    result = trader.trade_on_bar(mt5, "EURUSD", "EURUSD", "LONG",
        int(mt5.frame.time.iloc[-1].timestamp()), NOW, magic=MAGIC, dry=True,
        params=PARAMS, journal_path=tmp_path / "j.csv", mem=mem,
        cfg=cfg(exec_tf="H4", max_trades_per_day=0), deals=(), ranges=[("10-01", "10-31")])
    assert "window" in result and mem["crossovers"]["EURUSD"]["used"] == 0


@pytest.mark.parametrize("execution,regime", [
    ("H1", "H4"), ("H4", "D1"), ("H1", "D1"),
    ("H1", "H1"), ("H4", "H4"), ("D1", "D1")])
def test_crossover_accepts_supported_timeframe_pairs(tmp_path, execution, regime):
    preset = tmp_path / "_base_cross.yaml"
    preset.write_text(yaml.safe_dump({"strategy": {**PARAMS, "bias_ema_slow_period": 20},
        "timeframes": {"execution": execution, "regime": regime}}))
    assert read_timeframes(tmp_path, preset) == (execution, regime)


@pytest.mark.parametrize("direction", ["NEUTRAL", "SHORT"])
def test_live_regime_bias_blocks_disagreeing_execution_signal(tmp_path, direction):
    mt5, mem = _CrossMT5(), {}
    result = _live(mt5, mem, tmp_path, direction=direction)
    assert not result.startswith("PLAN")
    assert mem["crossovers"]["EURUSD"]["used"] == 0
    assert not mt5.sent


def test_memory_refreshes_while_pair_open_and_on_neutral_bias(tmp_path):
    mt5, mem = _CrossMT5(), {}
    assert _live(mt5, mem, tmp_path).startswith("PLAN")
    mt5._positions = [type("Position", (), {"magic": MAGIC, "symbol": "EURUSD"})()]
    tail = mt5.frame.iloc[-1:].copy()
    tail["time"] += pd.Timedelta(hours=4)
    tail.loc[:, ["open", "high", "low", "close"]] = 0.9
    mt5.frame = pd.concat([mt5.frame, tail], ignore_index=True)
    assert "pair-open" in _live(mt5, mem, tmp_path)
    state = mem["crossovers"]["EURUSD"]
    assert state["indicators"]["direction"] == "SHORT"
    assert state["used"] == 0


def test_monitor_tracks_crossover_even_if_initial_panel_bias_is_flat(tmp_path):
    from quant.monitor import PairRow, _trade_pass

    mt5 = _CrossMT5()
    rows = [PairRow("EURUSD", True, bias="FLAT")]
    pairs = [{"symbol": "EURUSD", "params": PARAMS, "costs": {}}]
    config = {"expected_account": None, "journal": tmp_path / "j.csv",
              "mem_path": tmp_path / "mem.json", "magic": MAGIC, "dry": True,
              "base_costs": {}, "ranges": [],
              "base": cfg(exec_tf="H4", max_trades_per_day=0, max_total_positions=0,
                          max_ccy_net=0, max_cost_ratio=0, scope_low=0, scope_high=0,
                          default_lot=0.01)}
    _trade_pass(mt5, pairs, rows, {"EURUSD": int(mt5.frame.time.iloc[-1].timestamp())},
                config, "DEMO", {}, (), NOW)
    assert rows[0].bias == "FLAT"
    assert "cross " in rows[0].entry and "0/2 used" in rows[0].entry
    assert trader.load_mem(config["mem_path"])["crossovers"]["EURUSD"]["crossover_time"]
    assert not mt5.sent


def test_separate_preset_uses_existing_pairs_without_changing_active_base(tmp_path):
    active = Path("configs/_base.yaml").read_bytes()
    preset = "configs/_base_crossover.yaml"
    assert read_timeframes("configs", preset) == ("H4", "H4")
    pairs = load_pairs("configs", preset)
    assert pairs and all(p["params"]["use_crossover_memory"] for p in pairs)
    config = read_trade_cfg("configs", preset)
    assert config["max_total_positions"] == config["max_ccy_net"] == 0
    assert config["max_trades_per_day"] == config["max_trades_per_pair_per_week"] == 0
    assert config["entry_hours"]["enabled"] and config["ranges"]
    (tmp_path / "_base.yaml").write_text("live: {magic: 100001}\n", encoding="utf-8")
    assert config["magic"] != read_trade_cfg(tmp_path)["magic"]
    assert read_limits("configs", preset) == read_limits("configs")
    strat = flatten_strategy(yaml.safe_load(Path(preset).read_text()))
    assert strat["stop_atr"] == strat["trail_r"] == 1.5 and strat["tp_mult"] == 10
    assert Path("configs/_base.yaml").read_bytes() == active
    missing = tmp_path / "missing.yaml"
    for reader in (read_timeframes, load_pairs, read_trade_cfg, read_limits):
        with pytest.raises(OSError):
            reader("configs", missing)


def test_active_base_loads_and_propagates_user_settings():
    active = yaml.safe_load(Path("configs/_base.yaml").read_text(encoding="utf-8"))
    assert read_timeframes("configs") == (active["timeframes"]["execution"],
                                           active["timeframes"]["regime"])
    params = flatten_strategy(active)
    signals.validate_crossover(params)
    assert all(pair["params"] == params for pair in load_pairs("configs"))
    assert read_trade_cfg("configs")["dry_run_default"] == active["live"]["dry_run_default"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_daily_bias_filters_h4_crossovers_without_execution_bias(side):
    bars = _bars()
    # Independent Daily trend with different EMA periods and an already closed history.
    daily = _bars(side).copy()
    daily["time"] = pd.date_range(end=bars.time.iloc[0] - pd.Timedelta(days=1),
                                  periods=len(daily), freq="1D")
    params = {**PARAMS, "bias_ema_fast_period": 5, "bias_ema_slow_period": 20,
              "bias_atr_period": 5}
    _, candidates = scan_pair(bars, daily, "EURUSD", params, reg_hours=24,
                               exec_hours=4, broker_bars=True)
    if side == "LONG":
        assert candidates
        assert all(c["direction"] == "LONG" for c in candidates)
    else:
        assert not candidates


def test_live_execution_timeframe_change_refuses_saved_memory(tmp_path):
    mt5, mem = _CrossMT5(), {}
    _live(mt5, mem, tmp_path)
    mem["crossovers"]["EURUSD"]["exec_tf"] = "H1"
    mem["bars"].clear()
    assert "execution timeframe changed" in _live(mt5, mem, tmp_path)
    assert not mt5.sent
