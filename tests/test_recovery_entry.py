"""Remembered pullbacks: closed synthetic bars only; no broker or historical data."""
import pandas as pd
import pytest

from quant import signals


def _run(monkeypatch, tail, side="LONG", fast=None, **overrides):
    rows = [(11.5, 12, 11, 11.5)] * 30 + tail
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    ef = [10.0] * len(frame) if fast is None else [10.0] * 30 + fast
    es = [5.0] * len(frame)
    if side == "SHORT":
        frame = pd.DataFrame({"open": 30-frame.open, "high": 30-frame.low,
                              "low": 30-frame.high, "close": 30-frame.close})
        ef, es = [30-x for x in ef], [30-x for x in es]
    monkeypatch.setattr(signals, "_ema", lambda s, n: pd.Series(ef if n == 20 else es))
    params = {"warmup_bars": 3, "entry_ema_fast_period": 20,
              "entry_ema_slow_period": 100, "use_recovery_entry": True,
              "use_w1": True, "w1_touch_from_trend_side": True,
              "use_e1_trigger": True, **overrides}
    return signals.check_entry(frame, side, params)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("setup", [(11, 11.2, 9, 9.5), (11, 11.2, 10, 10.5)])
def test_next_candle_close_or_wick_setup(monkeypatch, side, setup):
    result = _run(monkeypatch, [setup, (11.3, 11.5, 11.1, 11.4)], side)
    assert result["signal"] and result["entry_reason"] == "recovery_break"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_wick_switch_does_not_disable_close_setups(monkeypatch, side):
    wick_tail = [(11, 11.2, 10, 10.5), (11.3, 11.5, 11.1, 11.4)]
    assert _run(monkeypatch, wick_tail, side, recovery_use_wick=True)["signal"]
    assert not _run(monkeypatch, wick_tail, side, recovery_use_wick=False)["signal"]
    close_tail = [(11, 11.2, 9, 9.5), (11.3, 11.5, 11.1, 11.4)]
    assert _run(monkeypatch, close_tail, side, recovery_use_wick=False)["signal"]
    assert _run(monkeypatch, close_tail, side) == _run(
        monkeypatch, close_tail, side, recovery_use_wick=True)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_disabled_wick_cannot_refresh_expired_setup(monkeypatch, side):
    tail = [(11, 12, 9, 9.5), (11, 13, 10.5, 11),
            (12, 14, 9, 12), (14, 15, 13, 14.5)]
    assert _run(monkeypatch, tail, side, recovery_expiry_bars=1)["signal"]
    assert not _run(monkeypatch, tail, side, recovery_expiry_bars=1,
                    recovery_use_wick=False)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_remembers_setup_and_breaks_latest_not_original_high(monkeypatch, side):
    tail = [(11, 12, 9, 9.5), (10.7, 11, 10.5, 10.8), (11, 11.2, 10.9, 11.1)]
    assert not _run(monkeypatch, tail[:2], side)["signal"]
    assert _run(monkeypatch, tail, side)["signal"]


def test_trigger_can_still_be_below_fast_ema(monkeypatch):
    result = _run(monkeypatch, [(9, 9.5, 8, 9), (9.5, 9.9, 9.4, 9.8)])
    assert result["signal"]  # The legacy E1-trigger would reject this close below EMA20.


def test_strict_close_not_wick_or_equal_high(monkeypatch):
    setup = (11, 12, 9, 9.5)
    assert not _run(monkeypatch, [setup, (11, 13, 10.5, 12)])["signal"]


def test_expiry_and_refresh(monkeypatch):
    tail = [(11, 12, 9, 9.5), (11, 13, 10.5, 11),
            (12, 14, 11, 12), (14, 15, 13, 14.5)]
    assert not _run(monkeypatch, tail, recovery_expiry_bars=2)["signal"]
    assert _run(monkeypatch, tail, recovery_expiry_bars=3)["signal"]
    tail[2] = (12, 14, 9, 12)  # A fresh wick refreshes the setup.
    assert _run(monkeypatch, tail, recovery_expiry_bars=1)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_slow_ema_cancellation_switch(monkeypatch, side):
    tail = [(11, 12, 9, 9.5), (4.5, 4.8, 4, 4.5), (5, 6, 4.9, 5.5)]
    assert not _run(monkeypatch, tail, side)["signal"]
    assert _run(monkeypatch, tail, side, recovery_cancel_beyond_slow=False)["signal"]


def test_cross_cancels_and_realignment_needs_fresh_setup(monkeypatch):
    tail = [(11, 12, 9, 9.5), (11, 12, 10.5, 11), (12, 13, 11.5, 12.5)]
    assert not _run(monkeypatch, tail, fast=[10, 4, 10])["signal"]
    assert not _run(monkeypatch, tail, fast=[10, 5, 10])["signal"]
    tail += [(11, 12, 9, 9.5), (12.5, 13, 12.4, 12.8)]
    assert _run(monkeypatch, tail, fast=[10, 4, 10, 10, 10])["signal"]


def test_consumed_setup_does_not_trigger_twice(monkeypatch):
    tail = [(11, 11.2, 9, 9.5), (11.3, 11.5, 11.1, 11.4)]
    assert _run(monkeypatch, tail)["signal"]
    assert not _run(monkeypatch, tail + [(11.5, 12, 11.4, 11.9)])["signal"]


@pytest.mark.parametrize("key,value", [("recovery_expiry_bars", 0),
    ("recovery_expiry_bars", 1.5), ("recovery_expiry_bars", True),
    ("use_recovery_entry", "false"), ("recovery_cancel_beyond_slow", "false"),
    ("recovery_use_wick", "false"), ("recovery_use_zone_memory", "false")])
def test_invalid_settings_refused(monkeypatch, key, value):
    with pytest.raises(ValueError, match=key):
        _run(monkeypatch, [], **{key: value})


def test_disabled_mode_is_legacy_equivalent():
    from tests.test_signals import _frame, _go_bars
    frame = _frame(_go_bars()[0])
    assert signals.check_entry(frame, "LONG", {}) == signals.check_entry(
        frame, "LONG", {"use_recovery_entry": False, "recovery_expiry_bars": 8,
                          "recovery_cancel_beyond_slow": False})


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_waits_inside_beyond_expiry_and_recovers_outside(monkeypatch, side):
    tail = [(9, 9.5, 8, 9)] * 6 + [(9, 10.5, 8.5, 10.2)]
    assert not _run(monkeypatch, tail[:-1], side, recovery_use_zone_memory=True)["signal"]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                recovery_expiry_bars=1, recovery_use_wick=False)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_first_recovery_inside_is_consumed_even_if_not_traded(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (9.5, 9.9, 9.4, 9.8)]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]
    # Replaying history models a skipped fill/restart: do not revive that signal.
    tail += [(10, 10.5, 9.9, 10.2), (10.5, 11, 10.4, 10.8)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_first_recovery_outside_cannot_trigger_again(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (10, 11, 9.9, 10.5)]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]
    tail += [(11, 12, 10.9, 11.5)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_outside_without_recovery_misses_opportunity(monkeypatch, side):
    tail = [(9, 12, 8, 9), (10.5, 11, 10, 10.5)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]
    tail += [(11.5, 12, 10.5, 11.5)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]
    # Closing inside again starts a genuinely fresh setup.
    tail += [(9.5, 10, 9, 9.5), (10.5, 11, 10, 10.5)]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_wrong_side_cancellation_switch(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (4, 4.5, 3.5, 4), (4.5, 5, 4, 4.8)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                    recovery_cancel_beyond_slow=True)["signal"]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                recovery_cancel_beyond_slow=False)["signal"]
    tail += [(5, 5.5, 4.9, 5.2)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                    recovery_cancel_beyond_slow=False)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_optional_cancellation_consumes_returning_recovery_not_next_one(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (4, 4.5, 3.5, 4), (4, 4.2, 3, 3.5),
            (4, 9, 3.5, 8.5)]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                recovery_cancel_beyond_slow=False)["signal"]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                    recovery_cancel_beyond_slow=True)["signal"]
    tail += [(9, 11, 8.5, 10.5)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                    recovery_cancel_beyond_slow=False)["signal"]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                recovery_cancel_beyond_slow=True)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_optional_cancellation_does_not_disable_alignment_guard(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (4, 4.5, 3.5, 4), (4.5, 5, 4, 4.8)]
    assert not _run(monkeypatch, tail, side, fast=[10, 4, 10],
                    recovery_use_zone_memory=True, recovery_cancel_beyond_slow=False)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("setup", [(11, 11.5, 10, 11), (4, 4.5, 3.5, 4)])
def test_zone_outside_closes_and_wick_touches_cannot_arm(monkeypatch, side, setup):
    tail = [setup, (12, 13, 11.5, 12.5)]
    assert not _run(monkeypatch, tail, side, recovery_use_zone_memory=True,
                    recovery_use_wick=True, recovery_cancel_beyond_slow=False)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("boundary", [5, 10])
def test_zone_ema_boundaries_count_as_inside(monkeypatch, side, boundary):
    tail = [(boundary, boundary, boundary-0.5, boundary), (11, 12, 10.5, 11.5)]
    assert _run(monkeypatch, tail, side, recovery_use_zone_memory=True)["signal"]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_zone_alignment_loss_cancels_until_fresh_inside_close(monkeypatch, side):
    tail = [(9, 9.5, 8, 9), (11, 12, 10.5, 11), (12, 13, 11.5, 12.5)]
    assert not _run(monkeypatch, tail, side, fast=[10, 4, 10],
                    recovery_use_zone_memory=True)["signal"]


def test_zone_expiry_history_limit_is_unused(monkeypatch):
    tail = [(9, 9.5, 8, 9), (10, 11, 9.5, 10.5)]
    assert _run(monkeypatch, tail, recovery_use_zone_memory=True,
                recovery_expiry_bars=1000)["signal"]


def test_zone_switch_off_preserves_timed_behavior(monkeypatch):
    tail = [(11, 12, 9, 9.5), (11, 13, 10.5, 11), (14, 15, 13, 14.5)]
    assert _run(monkeypatch, tail) == _run(monkeypatch, tail,
                                          recovery_use_zone_memory=False)


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_live_gate_uses_same_recovery_core_without_orders(side):
    from quant import trader
    from tests.test_signals import _frame, _go_bars, _mirror
    from tests.test_trader import _FakeMT5, _scale

    bars = _go_bars()[0]
    if side == "SHORT":
        bars = _mirror(bars)
    mt5 = _FakeMT5()
    mt5._bars = _scale(bars)
    params = {"use_recovery_entry": True, "entry_ema_fast_period": 20,
              "entry_ema_slow_period": 100}
    expected = signals.check_entry(_frame(mt5._bars), side, params)
    assert expected["signal"]
    assert trader._gate_check(mt5, "EURUSD", side, params)[0]
    assert mt5.sent == []


def test_report_recognizes_recovery_reason(tmp_path):
    from quant import report
    from tests.test_report import _blob, _run_dir

    run, data, _ = _run_dir(tmp_path)
    path = run / "trades_S1.csv"
    trades = pd.read_csv(path)
    trades["entry_reason"] = "recovery_break"
    trades.to_csv(path, index=False)
    assert report.write_report(run, data)
    payload = _blob((run / "report.html").read_text(encoding="utf-8"), "trades-json")
    assert all(row["entryReasonLabel"] == signals.ENTRY_REASON_LABELS["recovery_break"]
               for row in payload["meta"])
