"""Probe unit tests: events, alignment, cost, pooling, verdict gating."""

import numpy as np
import pandas as pd
import pytest

from quant.edge_probe import (_cost_atr, _events, _moves, pool, probe_pair,
                              verdict)


def _p(k: int, mean: float, se: float) -> dict:
    return {"symbol": "POOLED", "kind": "onset", "horizon": k, "n": 100,
            "mean_edge": mean, "se": se}


def test_events_counts():
    d = pd.Series(["NEUTRAL", "NEUTRAL", "LONG", "LONG", "SHORT", "SHORT", "NEUTRAL"])
    onset, state = _events(d)
    assert list(onset) == [2, 4]  # NEUTRAL->LONG and LONG->SHORT (direct flip)
    assert list(state) == [2, 3, 4, 5]


def test_move_alignment_and_truncation():
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    atr = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    m, trunc = _moves(close, atr, np.array([0, 1]), np.array([1, -1]), 3)
    assert trunc == 0
    assert np.allclose(m, [3.0, -3.0])  # long up, short aligned to the SHORT sign
    m, trunc = _moves(close, atr, np.array([0, 1]), np.array([1, 1]), 10)
    assert trunc == 2 and m.size == 0  # k overruns the data: skipped, not read


def test_cost_atr_math():
    c = _cost_atr({"spread_points": 20, "slippage_pips": 0.3}, 0.0001, 0.0012)
    assert c == pytest.approx(2.6 * 0.0001 / 0.0012)  # (2.0 pips spread + 2*0.3 slip)


def _fake_rows() -> list[dict]:
    return [
        {"symbol": "A", "kind": "onset", "horizon": 48, "n": 2, "truncated": 0,
         "cost_atr": 0.2, "moves": np.array([0.5, 0.7])},
        {"symbol": "B", "kind": "onset", "horizon": 48, "n": 1, "truncated": 1,
         "cost_atr": 0.4, "moves": np.array([0.9])},
        {"symbol": "A", "kind": "state", "horizon": 48, "n": 2, "truncated": 0,
         "cost_atr": 0.2, "moves": np.array([0.1, -0.1])},
    ]


def test_pool_subtracts_own_pair_cost():
    p = pool(_fake_rows(), "onset", 48)
    edges = np.array([0.5 - 0.2, 0.7 - 0.2, 0.9 - 0.4])
    assert p["n"] == 3 and p["truncated"] == 1
    assert p["mean_edge"] == pytest.approx(edges.mean())
    assert p["se"] == pytest.approx(edges.std(ddof=1) / np.sqrt(3))


def test_verdict_gating():
    strong = [_p(48, 0.5, 0.05), _p(72, 0.5, 0.05)]
    assert verdict(strong) == "CONFIRMED"
    assert verdict([_p(48, -0.4, 0.05), _p(72, 0.5, 0.05)]).startswith(
        "NOT CONFIRMED (edge below cost")
    noise = [_p(48, 0.1, 0.05), _p(72, 0.1, 0.05)]  # mean within 2 SE of zero
    assert verdict(noise).startswith("NOT CONFIRMED (positive but within noise")
    # both horizons must pass; a horizon missing from the pools is a fail
    assert verdict([_p(72, 0.5, 0.05)]).startswith("NOT CONFIRMED")
    # 24-bar horizon never decides anything
    assert verdict([_p(24, 0.9, 0.01), _p(48, 0.5, 0.05), _p(72, 0.5, 0.05)]) == "CONFIRMED"


def _h1_trend(n: int, step: float, start: float = 1.0) -> pd.DataFrame:
    times = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    close = start + step * np.arange(n)
    # a thin wick band keeps ATR(7) small next to the trend move
    return pd.DataFrame({"time": times, "open": close - step / 2,
                         "high": close + 0.01 * abs(step),
                         "low": close - 0.01 * abs(step), "close": close})


def test_probe_pair_counts_on_synthetic_trend():
    hills = pd.concat([_h1_trend(800, 0.0010), _h1_trend(800, -0.0010,
                        start=1.0 + 0.0010 * 800)], ignore_index=True)
    p = {"warmup_bars": 40, "sep_atr": 0.3, "hr1": "a", "use_atr_sep": True, "atr_n": 7}
    costs = {"spread_points": 20, "slippage_pips": 0.3}
    rng = np.random.default_rng(0)
    rows = probe_pair("TEST", hills, p, costs, rng, (24, 48, 72), 0.0001)
    by = {(r["kind"], r["horizon"]): r for r in rows}
    onset, state = _events_dummy(hills, p)
    assert by[("onset", 24)]["n"] >= 2  # entering LONG and entering SHORT both measured
    assert by[("null", 24)]["n"] == by[("onset", 24)]["n"]  # null matches onset count
    assert by[("state", 24)]["n"] == state
    for r in rows:
        assert np.isfinite(r["moves"]).all()


def _events_dummy(h1: pd.DataFrame, p: dict) -> tuple[int, int]:
    from quant.backtest import bias_frames, build_h4, map_bias

    mapped = map_bias(h1, build_h4(h1), bias_frames(build_h4(h1), p))
    onset, state = _events(mapped["direction"])
    return len(onset), len(state)
