"""Dice probe unit tests: eligibility, streams, waves, thinning, verdict."""

import numpy as np
import pandas as pd
import pytest

import quant.dice_probe as dp
from quant.dice_probe import (_Stream, apply_filters, dice_pair_trades,
                              eligible_bars, env_from_frames, pooled_stats,
                              verdict_line)


def _h1(n: int = 800, step: float = 0.0003, drift: float = 0.0,
        seed: int = 7) -> pd.DataFrame:
    """Synthetic H1 bars: seeded random walk with wicks (drift = trend)."""
    rng = np.random.default_rng(seed)
    times = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    moves = rng.uniform(-step, step, n) + drift
    close = 1.0 + np.cumsum(moves)
    open_ = np.concatenate([[1.0], close[:-1]])
    wick = np.abs(rng.uniform(0, step / 3, n))
    return pd.DataFrame({"time": times, "open": open_,
                         "high": np.maximum(open_, close) + wick,
                         "low": np.minimum(open_, close) - wick,
                         "close": close})


def _mapped(n: int, neutral_until: int = 450) -> pd.DataFrame:
    dirs = ["NEUTRAL" if i < neutral_until else
            ("LONG" if i % 2 == 0 else "SHORT") for i in range(n)]
    return pd.DataFrame({"direction": dirs})


def _zero_costs() -> dict:
    return {"spread_points": 0, "slippage_pips": 0.0, "commission_per_lot": 0.0,
            "swap_long_per_0_01": 0.0, "swap_short_per_0_01": 0.0}


def _setup(**over) -> dict:
    s = {"strategy": {"warmup_bars": 100, "atr_n": 7, "stop_atr": 1.5,
                      "tp_mult": 3.0, "use_trail": False, "use_be": False},
         "converters": {}, "risk_usd": 3.0, "max_cost_ratio": 0.10,
         "scope_low": 0.0, "scope_high": 0.0, "max_day": 0, "max_open": 0,
         "max_ccy_net": 0, "weekly_r": 0.0,
         "position_checks": "H1", "no_trade_ranges": ()}
    s.update(over)
    return s


def test_dice_passes_the_same_base_to_shared_simulation(monkeypatch):
    setup = _setup(default_lot=0.02)
    monkeypatch.setattr(dp, "_STATE", {"setup": setup})
    captured = {}
    def fake_simulate(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame(), {}
    monkeypatch.setattr(dp, "simulate", fake_simulate)
    dp._simulate({"h1": _h1(), "symbol": "EURUSD", "costs": _zero_costs(),
                  "mapped": None, "m1": None}, [])
    assert captured["default_lot"] == 0.02


def test_eligible_bars_variants():
    n = 800
    env = {"symbol": "EURUSD", "h1": _h1(n), "mapped": _mapped(n), "t0": 400,
           "atr": np.full(n, 0.0002)}
    a = eligible_bars(env, "A")
    assert a[0] == 400 and a[-1] == n - 2 and len(a) == n - 401  # t+1 must exist
    env["atr"][500:505] = 0.0  # check_entry rejects a nonpositive ATR
    a = eligible_bars(env, "A")
    assert 499 in a and 505 in a and 500 not in a and 504 not in a
    b = eligible_bars(env, "B")
    assert b[0] == 450  # first bias-ON bar in range (NEUTRAL before it)
    assert (env["mapped"]["direction"].to_numpy()[b] != "NEUTRAL").all()


def test_stream_draw_sorted_reproducible_exhausts():
    n = 800
    env = {"symbol": "EURUSD", "h1": _h1(n), "mapped": _mapped(n), "t0": 400,
           "atr": np.full(n, 0.0002)}
    s1 = _Stream(env, "A", np.random.default_rng([42, 0, 0]))
    d1 = s1.draw(30)
    ts = [c["t"] for c in d1]
    assert ts == sorted(ts) and len(set(ts)) == 30  # time order, no replacement
    s2 = _Stream(env, "A", np.random.default_rng([42, 0, 0]))
    d2 = s2.draw(30)
    assert [(c["t"], c["direction"]) for c in d2] == \
        [(c["t"], c["direction"]) for c in d1]
    assert s1.left == len(s1.pool) - 30
    left_before = s1.left
    rest = s1.draw(10 ** 9)  # clamps to what is left
    assert len(rest) == left_before and s1.left == 0
    assert s1.draw(5) == []


def test_stream_b_directions_follow_bias():
    n = 800
    env = {"symbol": "EURUSD", "h1": _h1(n), "mapped": _mapped(n), "t0": 450,
           "atr": np.full(n, 0.0002)}
    s = _Stream(env, "B", np.random.default_rng([1, 2, 3]))
    d = s.draw(20)
    dirs = env["mapped"]["direction"].to_numpy()
    assert all(c["direction"] == dirs[c["t"]] for c in d)


def test_dice_pair_trades_reaches_target_and_reproduces():
    setup = _setup()
    dp._STATE["setup"] = setup
    env = env_from_frames("EURUSD", _h1(), _zero_costs(), setup, None)
    t1, d1 = dice_pair_trades(env, "A", 5, np.random.default_rng([42, 0, 0]))
    assert len(t1) == 5 and d1["kept"] == 5 and d1["shortfall"] == 0
    assert d1["waves"] >= 1 and d1["drawn"] >= d1["kept"]
    t2, _ = dice_pair_trades(env, "A", 5, np.random.default_rng([42, 0, 0]))
    pd.testing.assert_frame_equal(t1, t2)
    # variant B on a trending synthetic (bias-ON pool must exist there)
    env_tr = env_from_frames("EURUSD", _h1(drift=0.0003), _zero_costs(),
                             setup, None)
    t3, d3 = dice_pair_trades(env_tr, "B", 5, np.random.default_rng([42, 0, 1]))
    assert len(t3) == 5 and d3["shortfall"] == 0


def test_thinning_random_not_first_in_time(monkeypatch):
    setup = _setup()
    dp._STATE["setup"] = setup
    env = {"symbol": "EURUSD", "h1": _h1(), "mapped": _mapped(800),
           "t0": 400, "atr": np.full(800, 0.0002), "m1": None}
    frames = pd.DataFrame({
        "entry_time": pd.date_range("2020-01-01", periods=100, freq="12h",
                                    tz="UTC").astype(str),
        "i": np.arange(100)})

    calls = {"n": 0}

    def fake_sim(env_, cands):
        calls["n"] += 1
        return frames.copy(), {}

    monkeypatch.setattr(dp, "_simulate", fake_sim)
    t, d = dice_pair_trades(env, "A", 30, np.random.default_rng([9, 9]))
    assert len(t) == 30 and calls["n"] == 1  # first wave 4x30 reaches target
    assert list(t["entry_time"]) == sorted(t["entry_time"])  # time order kept
    assert t["i"].max() > 30  # uniform thinning, not the first 30 rows
    assert d["drawn"] == 120


def test_verdict_line():
    dice = np.arange(100, dtype=float)  # P95 = 94.05 (n-1 interpolation)
    v = verdict_line(96.0, dice)
    assert v["confirmed"] and v["percentile_of_real"] == 96.0
    assert not verdict_line(94.0, dice)["confirmed"]  # inside the dice range
    assert verdict_line(1.0, np.array([]))["confirmed"] is False


def test_apply_filters_and_pooled_stats():
    setup = _setup(max_day=20, max_open=1, max_ccy_net=2, weekly_r=15.0)

    def tr(sym, entry, pnl):
        return pd.DataFrame([{"symbol": sym, "entry_time": entry,
                              "exit_time": entry.replace("00:00", "01:00"),
                              "pnl_usd": pnl, "pnl_R": pnl / 3.0, "swap": 0.0}])

    by = {"EURUSD": tr("EURUSD", "2020-01-01 00:00", 3.0),
          "GBPUSD": tr("GBPUSD", "2020-01-02 00:00", -1.0)}
    kept, cap_d, pf_d = apply_filters(by, setup)
    assert not cap_d and not pf_d  # disjoint times: both fit max_open=1
    total = pooled_stats(kept)
    assert total["trades"] == 2
    assert total["expect_R"] == pytest.approx((1.0 - 1.0 / 3.0) / 2.0,
                                              abs=1e-3)
    empty = pooled_stats({"EURUSD": pd.DataFrame()})
    assert empty["trades"] == 0 and empty["expect_R"] == 0.0
