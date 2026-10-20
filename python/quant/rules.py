"""Shared strategy math used by BOTH the backtest engine and the live trader.

One source for the entry-decision numbers (cost gate, sizing scope, target
distance, trail geometry). The engine calls these so live orders can never
drift from what the backtest assumed. No MT5, no files — pure functions.
"""
from __future__ import annotations

import math


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


def read_sizing(risk: dict) -> tuple[float, dict]:
    """Resolve one base lot; accept the old stop-only key for older configs."""
    stop_sizing = dict(risk.get("stop_sizing") or {})
    base = float(risk.get("default_lot", stop_sizing.get("fixed_lot", 0.01)))
    if (not math.isfinite(base) or base < 0.01
            or not math.isclose(base / 0.01, round(base / 0.01), abs_tol=1e-9)):
        raise ValueError("risk.default_lot must be at least 0.01 in 0.01-lot steps")
    # Keep the resolved legacy field in run records and older caller interfaces.
    stop_sizing["fixed_lot"] = base
    return base, stop_sizing


def scope_lots(step_risk_usd: float, scope_low: float, scope_high: float,
               fixed_lot: float = 0.0, risk_target_usd: float = 0.0,
               default_lot: float | None = None
               ) -> tuple[float, float, str | None]:
    """Sizing decision. Returns (lots, risk_usd, reason).

    reason None = sized fine; 'scope' = refused by the sizing band; 'lot' =
    sub-minimum legacy sizing. Mirrors the engine's funnel gates exactly.
    Scope path: start at default_lot, add 0.01 lots until 1R reaches scope_low,
    refused when that size busts scope_high. No scope plus an explicit base
    uses the base unchanged; older callers retain legacy target sizing.
    """
    if fixed_lot:
        risk = step_risk_usd * fixed_lot / 0.01
        if (scope_low > 0 or scope_high > 0) and not (
                (scope_low <= 0 or risk + 1e-9 >= scope_low)
                and (scope_high <= 0 or risk <= scope_high + 1e-9)):
            return 0.0, 0.0, "scope"
        return float(fixed_lot), risk, None
    if scope_low > 0 or scope_high > 0 or default_lot is not None:
        if step_risk_usd <= 0 or not math.isfinite(step_risk_usd):
            return 0.0, 0.0, "scope"
        # Start at the base and add individual 0.01 lots, not base-sized blocks.
        base_steps = round((default_lot if default_lot is not None else 0.01) / 0.01)
        n = max(1, base_steps, math.ceil(round(scope_low / step_risk_usd, 9)))
        lots = round(n * 0.01, 2)
        if scope_high > 0 and step_risk_usd * n > scope_high + 1e-9:
            return 0.0, 0.0, "scope"  # granularity hole: no size fits the band
        return lots, step_risk_usd * n, None
    # legacy target sizing (no scope configured)
    lots = risk_target_usd / (step_risk_usd / 0.01) if step_risk_usd > 0 else 0.0
    lots = int(lots // 0.01) * 0.01
    if lots < 0.01:
        return 0.0, 0.0, "lot"
    return lots, step_risk_usd * lots / 0.01, None


def scaled_lots(step_risk_usd: float, aim_usd: float, scope_low: float,
                 scope_high: float, default_lot: float = 0.01
                 ) -> tuple[float, float, str | None]:
    """Compounding sizing (lot_scale). aim_usd = pct x account balance.

    Same 0.01 snapping and the SAME scope fence as scope_lots, but the aim
    follows the balance instead of sitting on the fence floor: snap UP to the
    smallest 0.01 step reaching the aim, then refuse when the snapped 1R
    falls outside [scope_low, scope_high] (0 disables a fence side).
    reason: None sized; 'high'/'low' fence breach; 'empty' = nothing to aim
    with (aim <= 0, i.e. the account is gone). Compounding only grows/shrinks
    with the account — never doubles after a loss (not martingale).
    """
    if step_risk_usd <= 0 or aim_usd <= 0:
        return 0.0, 0.0, "empty"
    # ceil(aim/step), rounded first: 9.000000000000002 must stay 9 steps
    n = max(1, round(default_lot / 0.01), math.ceil(round(aim_usd / step_risk_usd, 9)))
    risk = step_risk_usd * n
    if scope_high > 0 and risk > scope_high + 1e-9:
        return 0.0, 0.0, "high"
    if scope_low > 0 and risk < scope_low - 1e-9:
        return 0.0, 0.0, "low"
    return float(n) * 0.01, risk, None


def fit_stop_to_scope(stop_dist: float, atr: float, tick_size: float,
                      tick_value: float, scope_low: float, scope_high: float,
                      fixed_lot: float, max_stop_atr: float
                      ) -> tuple[float, str | None]:
    """Stop distance for a FIXED lot, widened until that lot risks scope_low.

    The alternative to widening is trading MORE lots on a tight stop. This
    function implements the widening branch, shared by the backtest engine and
    the live planner so both size a trade the same way.

    - fixed_lot <= 0 -> the ATR stop is used unchanged (no widening configured).
    - The stop is only ever widened, never narrowed.
    - The widened stop must still fit inside max_stop_atr x ATR, else the
      trade is refused ("stop-cap"): a stop that far from price is not the
      trade the rules described.
    - The fixed lot must stay inside the scope band: refused ("scope") when it
      already risks more than scope_high at the ATR stop.
    - The caller places the take profit with target_dist(), so the reward
      distance moves with the stop and the R:R stays as configured.
    Returns (stop_dist, reason) with reason None when the trade may proceed.
    """
    if fixed_lot <= 0:
        return stop_dist, None
    risk_at = risk_usd(stop_dist, tick_size, tick_value, fixed_lot)
    if risk_at <= 0:
        return stop_dist, "scope"  # no tick math -> no way to size this trade
    if scope_high > 0 and risk_at > scope_high + 1e-9:
        return stop_dist, "scope"  # the fixed lot is already too big
    if scope_low <= 0 or risk_at >= scope_low:
        return stop_dist, None  # the ATR stop already reaches the floor
    # risk grows in a straight line with the stop distance
    needed = stop_dist * scope_low / risk_at
    cap = max_stop_atr * atr if max_stop_atr > 0 else float("inf")
    if needed > cap + 1e-12:
        return stop_dist, "stop-cap"
    new_risk = risk_usd(needed, tick_size, tick_value, fixed_lot)
    if scope_high > 0 and new_risk > scope_high + 1e-9:
        return stop_dist, "scope"
    return needed, None


def size_stop_to_scope(stop_dist: float, atr: float, tick_size: float,
                       tick_value: float, scope_low: float, scope_high: float,
                       fixed_lot: float, max_stop_atr: float,
                       increase_lots_if_widening_fails: bool = False
                       ) -> tuple[float, float, str | None, bool]:
    """Try widening first; optionally size more lots at the ORIGINAL stop.

    Only a widening-cap refusal permits fallback. Scope failures and bad tick
    data must never be rescued by increasing exposure. The last return value
    identifies a successful fallback for run records.
    """
    fitted, why = fit_stop_to_scope(
        stop_dist, atr, tick_size, tick_value, scope_low, scope_high,
        fixed_lot, max_stop_atr)
    if why == "stop-cap" and increase_lots_if_widening_fails:
        lots, _, why = scope_lots(
            step_risk(stop_dist, tick_size, tick_value), scope_low, scope_high,
            default_lot=fixed_lot)
        return stop_dist, lots, why, why is None
    return fitted, fixed_lot, why, False


def stop_sizing_conflict(stop_sizing: dict | None, scale_lots: bool) -> str | None:
    """Error text when the stop-sizing mode cannot run, else None.

    Shared by the backtest and the live loop so both refuse the same
    combinations: a fixed lot cannot compound, and the knobs must be sane.
    """
    ss = stop_sizing or {}
    if not ss.get("widen_stop_to_scope"):
        return None
    if scale_lots:
        return ("widen_stop_to_scope and scale_lot_with_balance cannot run "
                "together (fixed lot vs compounding lot)")
    if float(ss.get("fixed_lot") or 0.0) < 0.01:
        return "risk.stop_sizing.fixed_lot must be at least 0.01"
    if float(ss.get("max_stop_atr") or 0.0) <= 0:
        return "risk.stop_sizing.max_stop_atr must be > 0"
    return None


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
