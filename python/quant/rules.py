"""Shared strategy math used by BOTH the backtest engine and the live trader.

One source for the entry-decision numbers (cost gate, sizing scope, target
distance, trail geometry). The engine calls these so live orders can never
drift from what the backtest assumed. No MT5, no files — pure functions.
"""
from __future__ import annotations


def step_risk(stop_dist: float, tick_size: float, tick_value: float) -> float:
    """Money at risk for one trade at 0.01 lot (account currency)."""
    if tick_size <= 0 or tick_value <= 0:
        return 0.0
    return (stop_dist / tick_size) * tick_value * 0.01


def risk_usd(stop_dist: float, tick_size: float, tick_value: float, lots: float) -> float:
    """Actual 1R money for `lots` at the given stop distance."""
    if tick_size <= 0 or tick_value <= 0:
        return 0.0
    return (stop_dist / tick_size) * tick_value * lots


def cost_ok(stop_dist: float, spread_px: float, slip_px: float, max_cost_ratio: float) -> bool:
    """Round-trip cost must stay below max_cost_ratio of the stop distance."""
    if max_cost_ratio <= 0:
        return True
    if stop_dist <= 0:
        return False
    return (spread_px + slip_px) / stop_dist <= max_cost_ratio


def scope_lots(step_risk_usd: float, scope_low: float, scope_high: float,
               fixed_lot: float = 0.0, risk_target_usd: float = 0.0
               ) -> tuple[float, float, str | None]:
    """Sizing decision. Returns (lots, risk_usd, reason).

    reason None = sized fine; 'scope' = refused by the sizing band; 'lot' =
    sub-minimum legacy sizing. Mirrors the engine's funnel gates exactly.
    Scope path: smallest 0.01 multiple whose 1R reaches scope_low, refused when
    that multiple busts scope_high (includes "even 0.01 lot is too big").
    """
    if fixed_lot:
        risk = step_risk_usd * fixed_lot / 0.01
        if (scope_low > 0 or scope_high > 0) and not (
                (scope_low <= 0 or risk + 1e-9 >= scope_low)
                and (scope_high <= 0 or risk <= scope_high + 1e-9)):
            return 0.0, 0.0, "scope"
        return float(fixed_lot), risk, None
    if scope_high > 0:
        if step_risk_usd > scope_high:
            return 0.0, 0.0, "scope"  # even the minimum lot busts the ceiling
        n = max(1, int(-(-scope_low // step_risk_usd)))  # ceil(scope_low / step_risk)
        lots = n * 0.01
        if step_risk_usd * n > scope_high:
            return 0.0, 0.0, "scope"  # granularity hole: no size fits the band
        return lots, step_risk_usd * n, None
    # legacy target sizing (no scope configured)
    lots = risk_target_usd / (step_risk_usd / 0.01) if step_risk_usd > 0 else 0.0
    lots = int(lots // 0.01) * 0.01
    if lots < 0.01:
        return 0.0, 0.0, "lot"
    return lots, step_risk_usd * lots / 0.01, None


def target_dist(stop_dist: float, tp_mult: float) -> float:
    """Take-profit distance = tp_mult x the initial stop distance."""
    return tp_mult * stop_dist


def activated(entry: float, stop_dist: float, best: float, long: bool, act_r: float) -> bool:
    """Is the trigger point hit: price moved act_r x risk in our favour?"""
    return (best - entry >= act_r * stop_dist) if long else (entry - best >= act_r * stop_dist)


def combine_stop(sl: float, entry: float, stop_dist: float, best: float, long: bool,
                 use_be: bool, be_buf: float, use_trail: bool, trail_r: float) -> float:
    """Effective stop for one check row, given the best price so far.

    Mirrors the engine's per-row stop build: BE lifts the stop to entry(+/-)
    buffer once the trigger fired; the trail keeps trail_r x risk behind the
    best price but never suggests a level still on the losing side.
    Engine (backtest.py) calls this too when a trail/BE leg is on.
    """
    eff = sl
    if use_be:
        eff = max(eff, entry + be_buf) if long else min(eff, entry - be_buf)
    if use_trail:
        level = best - trail_r * stop_dist if long else best + trail_r * stop_dist
        if (long and level >= entry) or (not long and level <= entry):
            eff = max(eff, level) if long else min(eff, level)
    return eff
