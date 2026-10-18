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
