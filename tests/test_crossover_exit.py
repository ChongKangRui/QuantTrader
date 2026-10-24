"""Opposite-cross exits: synthetic candles and fake MT5 only."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant import backtest, signals, trader
from tests.test_crossover import PARAMS, _CrossMT5
from tests.test_trader import MAGIC, _pos


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("enabled", [True, False])
def test_exit_on_next_open_with_costs_and_no_future_candle_range(monkeypatch, side, enabled):
    bars = pd.DataFrame({"time": pd.date_range("2026-02-02", periods=5, freq="4h", tz="UTC"),
        "open": [1.1, 1.1, 1.1, 1.12, 1.1], "high": [1.13] * 5,
        "low": [1.08] * 5, "close": [1.1] * 5})
    records = [{"crossover_time": None, "direction": None} for _ in range(5)]
    records[2] = {"crossover_time": bars.time.iloc[2].isoformat(),
                  "direction": "SHORT" if side == "LONG" else "LONG"}
    monkeypatch.setattr(backtest, "crossover_signals", lambda *a: (records, {}))
    bars.loc[3, ["high", "low"]] = [2.0, 0.1]  # Unknown at the exit open; must not affect this exit.
    params = {**PARAMS, "use_crossover_exit": enabled, "use_trail": False}
    trades, _ = backtest.simulate(bars, "EURUSD", [{"t": 0, "direction": side, "atr": 0.1}],
        params, {"spread_points": 20, "slippage_pips": 1}, 3, 0,
        lot=0.01, bar_hours=4, coarse_exit_at_close=True)
    row = trades.iloc[0]
    if enabled:
        assert row.exit_type == "crossover"
        assert pd.Timestamp(row.exit_time) == bars.time.iloc[3]
        assert row.exit == pytest.approx(1.1199 if side == "LONG" else 1.1203)
    else:
        assert row.exit_type == "stop"


def test_cross_before_entry_and_neutral_bias_are_distinct():
    record = {"crossover_time": "2026-02-02T00:00:00Z", "direction": "SHORT", "bias": "NEUTRAL"}
    assert signals.opposite_crossover(record, "LONG", pd.Timestamp("2026-02-02T01:00Z"), 4)
    assert not signals.opposite_crossover(record, "LONG", pd.Timestamp("2026-02-02T04:00Z"), 4)
    assert not signals.opposite_crossover(record, "SHORT", pd.Timestamp("2026-02-02T01:00Z"), 4)


def test_invalid_exit_switch_refused():
    with pytest.raises(ValueError, match="use_crossover_exit"):
        signals.validate_crossover({**PARAMS, "use_crossover_exit": "false"})
    with pytest.raises(ValueError, match="requires"):
        signals.validate_crossover({"use_crossover_exit": True})


def _manage(tmp_path, mt5, mem, *, dry=True, enabled=True):
    return trader.manage_book(mt5, "EURUSD", "EURUSD",
        {**PARAMS, "use_crossover_exit": enabled, "use_trail": False}, MAGIC, dry,
        tmp_path / "journal.csv", mem, {}, memory_path=tmp_path / "memory.json")


def _terminal():
    mt5 = _CrossMT5()
    mt5.symbol_select = lambda *a: True
    pos = _pos(ptype=1)
    pos.time = int(mt5.frame.time.iloc[20].timestamp())
    mt5._positions = [pos]
    return mt5


def test_dry_run_exit_does_not_send_and_disabled_mode_does_not_close(tmp_path):
    mt5 = _terminal()
    assert any("EXIT(plan)" in s for s in _manage(tmp_path, mt5, {}))
    assert mt5.sent == []
    assert not any("EXIT" in s for s in _manage(tmp_path, mt5, {}, enabled=False))


def test_close_targets_ticket_and_rechecks_after_restart(tmp_path):
    mt5, mem = _terminal(), {}
    def close(req):
        mt5.sent.append(req)
        assert req["position"] == 100 and "position_id" not in req
        assert req["type"] == mt5.ORDER_TYPE_BUY
        assert req["volume"] == 0.02 and req["magic"] == MAGIC
        mt5._positions.clear()
        return SimpleNamespace(retcode=10009)
    mt5.order_send = close
    assert any("EXIT crossover" in s for s in _manage(tmp_path, mt5, mem, dry=False))
    restored = trader.load_mem(tmp_path / "memory.json")
    _manage(tmp_path, mt5, restored, dry=False)
    assert len(mt5.sent) == 1


def test_partial_close_retries_only_remaining_ticket_volume(tmp_path):
    mt5, mem = _terminal(), {}
    def partial(req):
        mt5.sent.append(req)
        if len(mt5.sent) == 1:
            mt5._positions[0].volume = 0.01
            return SimpleNamespace(retcode=10010)
        mt5._positions.clear()
        return SimpleNamespace(retcode=10009)
    mt5.order_send = partial
    _manage(tmp_path, mt5, mem, dry=False)
    _manage(tmp_path, mt5, trader.load_mem(tmp_path / "memory.json"), dry=False)
    assert [r["volume"] for r in mt5.sent] == [0.02, 0.01]
    assert all(r["position"] == 100 for r in mt5.sent)


def test_flat_bias_and_weekly_halt_do_not_block_management_or_reverse_trade(tmp_path, monkeypatch):
    from quant.monitor import PairRow, _trade_pass
    mt5 = _terminal()
    config = {"expected_account": None, "journal": tmp_path / "journal.csv",
              "mem_path": tmp_path / "memory.json", "magic": MAGIC, "dry": True,
              "base": {"exec_tf": "H4"}, "base_costs": {}, "ranges": [("01-01", "12-31")]}
    monkeypatch.setattr(trader, "trade_on_bar", lambda *a, **kw: pytest.fail("must not reverse on close pass"))
    _trade_pass(mt5, [{"symbol": "EURUSD", "params": {**PARAMS, "use_crossover_exit": True}, "costs": {}}],
                [PairRow("EURUSD", True, bias="FLAT", has_position=True)], {}, config,
                "DEMO", {"halted": True}, None, mt5.frame.time.iloc[-1].to_pydatetime())
    saved = trader.load_mem(config["mem_path"])
    assert saved["open"]["100"]["crossover_exit_at"]
    assert mt5.sent == []


def test_uncertain_close_survives_restart_without_duplicate_send(tmp_path):
    mt5, mem = _terminal(), {}
    def uncertain(req):
        mt5.sent.append(req)
        return None
    mt5.order_send = uncertain
    assert any("UNCONFIRMED" in s for s in _manage(tmp_path, mt5, mem, dry=False))
    restored = trader.load_mem(tmp_path / "memory.json")
    assert any("UNCONFIRMED" in s for s in _manage(tmp_path, mt5, restored, dry=False))
    assert len(mt5.sent) == 1
