"""Shared strategy math (quant/rules.py) — pure-function parity vs the engine."""
import pytest

from quant import rules


def test_step_risk_and_zero_guards():
    assert rules.step_risk(0.0050, 0.00001, 1.0) == pytest.approx(5.0)  # 500 ticks
    assert rules.step_risk(0.0, 0.00001, 1.0) == 0.0
    assert rules.step_risk(0.0, 0.0, 1.0) == 0.0
    assert rules.risk_usd(0.0050, 0.00001, 1.0, 0.05) == pytest.approx(25.0)


def test_cost_gate_boundaries():
    assert rules.cost_ok(0.0050, 0.0002, 0.0003, 0.10)      # 0.0005/0.0050 = 0.10
    assert rules.cost_ok(0.0050, 0.0002, 0.0003, 0.0)       # 0 = off
    assert not rules.cost_ok(0.0050, 0.0002, 0.0004, 0.10)
    assert not rules.cost_ok(0.0, 0.0002, 0.0003, 0.10)     # no stop -> no entry


def test_scope_lots_engine_paths():
    # smallest 0.01 multiple that reaches the low bound
    lots, risk, why = rules.scope_lots(50.0, 100.0, 120.0)
    assert (lots, risk, why) == (0.02, pytest.approx(100.0), None)
    # even the minimum lot busts the ceiling
    assert rules.scope_lots(130.0, 0.0, 120.0) == (0.0, 0.0, "scope")
    # granularity hole: ceil to 0.02 = 120 > 110
    assert rules.scope_lots(60.0, 100.0, 110.0) == (0.0, 0.0, "scope")
    # low unset: one minimum lot is allowed
    lots, risk, why = rules.scope_lots(50.0, 0.0, 120.0)
    assert (lots, risk, why) == (0.01, pytest.approx(50.0), None)
    # fixed-lot diagnostic path, in/out of band
    lots, risk, why = rules.scope_lots(50.0, 100.0, 120.0, fixed_lot=0.02)
    assert why is None and lots == 0.02 and risk == pytest.approx(100.0)
    assert rules.scope_lots(50.0, 100.0, 120.0, fixed_lot=0.05) == (0.0, 0.0, "scope")
    # legacy target sizing (no scope configured)
    lots, risk, why = rules.scope_lots(50.0, 0.0, 0.0, risk_target_usd=100.0)
    assert lots == 0.02 and risk == pytest.approx(100.0) and why is None
    assert rules.scope_lots(50.0, 0.0, 0.0, risk_target_usd=1.0) == (0.0, 0.0, "lot")


@pytest.mark.parametrize("step,low,high,base,lots,reason", [
    (1.5, 4.0, 5.5, 0.02, 0.03, None),  # add 0.01, not another 0.02
    (1.0, 4.0, 5.5, 0.02, 0.04, None),  # more than one increment
    (2.0, 4.0, 5.5, 0.02, 0.02, None),  # base already fits
    (3.0, 4.0, 5.5, 0.02, 0.0, "scope"),  # base exceeds ceiling
    (1.9, 4.0, 5.5, 0.02, 0.0, "scope"),  # next step exceeds ceiling
    (1.0, 0.0, 5.5, 0.03, 0.03, None),  # no floor: do not shrink
    (1.0, 4.0, 0.0, 0.02, 0.04, None),  # ceiling disabled
    (1.0, 0.0, 0.0, 0.02, 0.02, None),  # scope off: use base
])
def test_scope_stacks_001_lots_above_base(step, low, high, base, lots, reason):
    result, risk, why = rules.scope_lots(step, low, high, default_lot=base)
    assert result == pytest.approx(lots) and why == reason
    if why is None:
        assert risk == pytest.approx(step * lots / 0.01)


@pytest.mark.parametrize("base", [0, -0.01, 0.005, 0.015, float("nan"), float("inf")])
def test_read_sizing_refuses_invalid_base(base):
    with pytest.raises(ValueError, match="risk.default_lot"):
        rules.read_sizing({"default_lot": base})


def test_read_sizing_prefers_new_base_and_accepts_legacy():
    base, ss = rules.read_sizing({"default_lot": 0.02, "stop_sizing": {"fixed_lot": 0.03}})
    assert base == ss["fixed_lot"] == 0.02
    assert rules.read_sizing({"stop_sizing": {"fixed_lot": 0.03}})[0] == 0.03
    assert rules.read_sizing({})[0] == 0.01


def test_balance_scaling_and_widening_use_the_base():
    assert rules.scaled_lots(1.0, 1.0, 0.0, 5.5, default_lot=0.02) == (0.02, 2.0, None)
    assert rules.scaled_lots(3.0, 1.0, 0.0, 5.5, default_lot=0.02)[2] == "high"
    stop, lots, why, used = rules.size_stop_to_scope(
        0.001, 0.001, 0.00001, 1.0, 4.0, 5.5, 0.02, 3.0, True)
    assert why is None and not used and lots == 0.02
    assert stop == pytest.approx(0.002)


def test_target_and_activation():
    assert rules.target_dist(0.0050, 3.0) == pytest.approx(0.0150)
    # LONG: best must clear entry + act_r x stop; SHORT mirrored
    assert rules.activated(1.1000, 0.0100, 1.1111, True, 1.0)
    assert not rules.activated(1.1000, 0.0100, 1.1050, True, 1.0)
    assert rules.activated(1.1000, 0.0100, 1.0900, False, 1.0)
    assert not rules.activated(1.1000, 0.0100, 1.0950, False, 1.0)


def test_combine_stop_engine_mirror():
    entry, stop = 1.1000, 0.0100
    sl, be_buf, trail_r = 1.0900, 0.0001, 1.0
    best = 1.1150  # 1.5R: trigger armed
    # trail wins: best - trail_r x stop = 1.1050 -> eff = max(sl, level)
    assert rules.combine_stop(sl, entry, stop, best, True, False, 0.0, True, trail_r) \
        == pytest.approx(1.1050)
    # BE only: entry(+buffer)
    assert rules.combine_stop(sl, entry, stop, best, True, True, be_buf, False, trail_r) \
        == pytest.approx(1.1001)
    # BE + trail: both overlays, higher one wins
    assert rules.combine_stop(sl, entry, stop, best, True, True, be_buf, True, trail_r) \
        == pytest.approx(1.1050)
    # trail level still on the losing side is ignored (no trigger yet)
    assert rules.combine_stop(sl, entry, stop, 1.1050, True, False, 0.0, True, trail_r) == sl
    # SHORT mirrors with min(): 1.0850 -> level 1.0950 below entry, valid
    assert rules.combine_stop(1.1100, entry, stop, 1.0850, False, False, 0.0, True, trail_r) \
        == pytest.approx(1.0950)
    # SHORT losing-side level ignored (level above entry = still a loss)
    assert rules.combine_stop(1.1100, entry, stop, 1.0950, False, False, 0.0, True, trail_r) \
        == 1.1100


# ------------------------------------------------------- widened stop (stop sizing)
# 0.01 lot of EURUSD: one pip (0.0001) is worth 0.10 USD at 0.01 lot.
# tick_size 0.00001, tick_value 1.0 per 1.0 lot -> 0.0001 pip = 10 ticks = 1.0 USD
# per 1.0 lot, so 0.01 lot risks 0.10 USD per pip.

def test_fit_stop_widens_until_the_fixed_lot_reaches_the_floor():
    stop, atr = 0.0010, 0.0010           # 10 pips
    dist, why = rules.fit_stop_to_scope(stop, atr, 0.00001, 1.0, 4.0, 5.5, 0.01, 5.0)
    assert why is None
    # 0.01 lot at 10 pips risks 1.00 USD -> needs 4.00 USD -> 40 pips
    assert dist == pytest.approx(0.0040)
    assert rules.risk_usd(dist, 0.00001, 1.0, 0.01) == pytest.approx(4.0)


def test_fit_stop_leaves_a_reaching_stop_alone():
    stop, atr = 0.0050, 0.0050           # 50 pips -> 5.00 USD at 0.01 lot
    dist, why = rules.fit_stop_to_scope(stop, atr, 0.00001, 1.0, 4.0, 5.5, 0.01, 3.0)
    assert (dist, why) == (stop, None)


def test_fit_stop_refuses_beyond_the_atr_cap():
    stop, atr = 0.0010, 0.0010           # 10 pips, needs 40 pips = 4x ATR
    dist, why = rules.fit_stop_to_scope(stop, atr, 0.00001, 1.0, 4.0, 5.5, 0.01, 3.0)
    assert why == "stop-cap" and dist == stop
    # the same trade passes with a 5x cap
    ok, why2 = rules.fit_stop_to_scope(stop, atr, 0.00001, 1.0, 4.0, 5.5, 0.01, 5.0)
    assert why2 is None and ok == pytest.approx(0.0040)


def test_fit_stop_refuses_a_fixed_lot_that_overshoots_the_ceiling():
    stop, atr = 0.0050, 0.0050           # 5.00 USD > high 5.5? no: equals; use 60 pips
    stop = 0.0060                        # 6.00 USD at 0.01 lot
    dist, why = rules.fit_stop_to_scope(stop, atr, 0.00001, 1.0, 4.0, 5.5, 0.01, 3.0)
    assert why == "scope" and dist == stop


def test_fit_stop_without_a_fixed_lot_never_changes_the_stop():
    stop = 0.0010
    assert rules.fit_stop_to_scope(stop, 0.0010, 0.00001, 1.0, 4.0, 5.5, 0.0, 3.0) \
        == (stop, None)


@pytest.mark.parametrize("enabled,cap,expected_lot,expected_stop,reason,fallback", [
    (False, 3.0, 0.01, 0.0010, "stop-cap", False),
    (True, 3.0, 0.04, 0.0010, None, True),
    (True, 5.0, 0.01, 0.0040, None, False),
])
def test_stop_sizing_optional_lot_fallback(enabled, cap, expected_lot,
                                           expected_stop, reason, fallback):
    dist, lots, why, used = rules.size_stop_to_scope(
        0.0010, 0.0010, 0.00001, 1.0, 4.0, 5.5, 0.01, cap, enabled)
    assert dist == pytest.approx(expected_stop)
    assert lots == pytest.approx(expected_lot)
    assert (why, used) == (reason, fallback)


@pytest.mark.parametrize("stop,value,low,high", [
    (0.006, 1.0, 4.0, 5.5),  # minimum lot already exceeds the ceiling
    (0.003, 1.0, 4.0, 5.5),  # 0.01 risks 3; 0.02 risks 6: neither fits
    (0.001, 0.0, 4.0, 5.5),  # missing tick value cannot trigger fallback
])
def test_lot_fallback_keeps_scope_and_tick_refusals(stop, value, low, high):
    _, _, why, used = rules.size_stop_to_scope(
        stop, 0.001, 0.00001, value, low, high, 0.01, 3.0, True)
    assert why == "scope" and not used


def test_stop_sizing_conflicts():
    ok = {"widen_stop_to_scope": True, "fixed_lot": 0.01, "max_stop_atr": 3.0}
    assert rules.stop_sizing_conflict(None, False) is None
    assert rules.stop_sizing_conflict({"widen_stop_to_scope": False}, True) is None
    assert rules.stop_sizing_conflict(ok, False) is None
    assert "cannot run together" in rules.stop_sizing_conflict(ok, True)
    assert "fixed_lot" in rules.stop_sizing_conflict(
        dict(ok, fixed_lot=0.005), False)
    assert "max_stop_atr" in rules.stop_sizing_conflict(
        dict(ok, max_stop_atr=0), False)
