"""Vendor-derived research is opt-in, source-checked and shared with dice."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant import dice_probe as dp
from quant.backtest import _broker_bar_path, load_chart_frames, map_bias, bias_frames, run_pair
from quant.mkdata import (RESEARCH_SOURCE, build_research_data, research_chart_path,
                          research_info)
from tests.test_dice_probe import _h1, _setup, _zero_costs


def _sources(tmp_path, symbols=("EURUSD",), frame=None):
    src = tmp_path / "sources"
    src.mkdir()
    if frame is None:
        frame = pd.DataFrame({"time": pd.to_datetime([
            "2020-01-01 23:58Z", "2020-01-01 23:59Z", "2020-01-02 00:00Z",
            "2020-01-02 00:01Z", "2020-01-02 12:00Z", "2020-01-03 00:00Z"]),
            "open": [1.1] * 6, "high": [1.3] * 6, "low": [1.0] * 6,
            "close": [1.2] * 6, "tick_volume": [2] * 6})
    for sym in symbols:
        frame.to_csv(src / f"{sym}_M1.csv", index=False)
        frame.to_csv(src / f"{sym}_H1.csv", index=False)
    return src


def test_research_build_chunk_boundary_ohlc_no_fill_and_all_existing(tmp_path):
    src = _sources(tmp_path, ("EURUSD", "AUDJPY"))
    out = tmp_path / "research"
    manifest = build_research_data(src, out, all_existing=True, chunk_rows=2)
    assert set(manifest["symbols"]) == {"EURUSD", "AUDJPY"}
    h4 = pd.read_csv(out / "EURUSD_H4.csv")
    daily = pd.read_csv(out / "EURUSD_D1.csv")
    assert list(h4["n_minutes"]) == [2, 2, 1, 1]
    assert list(daily["n_minutes"]) == [2, 3, 1]
    assert list(daily["tick_volume"]) == [4, 6, 2]
    assert daily["open"].tolist() == [1.1] * 3
    assert daily["high"].tolist() == [1.3] * 3
    assert daily["low"].tolist() == [1.0] * 3
    assert daily["close"].tolist() == [1.2] * 3
    assert pd.to_datetime(h4["time"], utc=True).iloc[0].hour == 20
    meta = json.loads((out / "EURUSD_H4.meta.json").read_text())
    assert meta["source_type"] == RESEARCH_SOURCE
    assert meta["empty_periods"] == 4
    assert meta["partial_bars"] == 4
    assert meta["source_minutes"] == 6
    assert "unverified" in meta["warning"]
    assert (src / "EURUSD_M1.csv").exists()
    assert not (out / "EURUSD_M1.csv").exists()


def test_chunk_size_cannot_change_derived_candles(tmp_path):
    src = _sources(tmp_path)
    for chunk in (1, 4, 100):
        build_research_data(src, tmp_path / str(chunk), all_existing=True, chunk_rows=chunk)
    for tf in ("H4", "D1"):
        assert (tmp_path / "1" / f"EURUSD_{tf}.csv").read_bytes() == (
            tmp_path / "100" / f"EURUSD_{tf}.csv").read_bytes()
        assert (tmp_path / "4" / f"EURUSD_{tf}.csv").read_bytes() == (
            tmp_path / "100" / f"EURUSD_{tf}.csv").read_bytes()


@pytest.mark.parametrize("problem", ["duplicate", "descending", "price", "missing", "minute"])
def test_bad_sources_abort_without_publishing(tmp_path, problem):
    src = _sources(tmp_path)
    file = src / "EURUSD_M1.csv"
    frame = pd.read_csv(file)
    if problem == "duplicate":
        frame.loc[2, "time"] = frame.loc[1, "time"]
    elif problem == "descending":
        frame = frame.iloc[::-1]
    elif problem == "price":
        frame.loc[3, "high"] = 0.5
    elif problem == "missing":
        frame = frame.drop(columns="close")
    else:
        frame.loc[0, "time"] = "2020-01-01 23:58:05+00:00"
    frame.to_csv(file, index=False)
    out = tmp_path / "research"
    with pytest.raises(ValueError):
        build_research_data(src, out, all_existing=True, chunk_rows=2)
    assert not list(out.glob("*.csv"))
    assert not (out / "manifest.json").exists()


def test_source_and_derived_integrity_guard_and_opt_in(tmp_path):
    src = _sources(tmp_path)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True)
    path = research_chart_path(out, "EURUSD", "H4", src / "EURUSD_H1.csv")
    assert path == out / "EURUSD_H4.csv"
    assert research_info(out)["source_type"] == RESEARCH_SOURCE
    (src / "EURUSD_H4.csv").write_bytes(path.read_bytes())
    (src / "EURUSD_H4.meta.json").write_bytes((out / "EURUSD_H4.meta.json").read_bytes())
    with pytest.raises(ValueError, match="explicit"):
        _broker_bar_path(src / "EURUSD_H1.csv", "EURUSD", "H4")
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        research_chart_path(out, "EURUSD", "H4", src / "EURUSD_H1.csv")


def test_modified_source_rejected(tmp_path):
    src = _sources(tmp_path)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True)
    with (src / "EURUSD_M1.csv").open("a") as fh:
        fh.write("\n")
    with pytest.raises(ValueError, match="source changed"):
        research_chart_path(out, "EURUSD", "D1", src / "EURUSD_H1.csv")


def test_research_output_must_be_separate_and_never_overwrites_by_default(tmp_path):
    src = _sources(tmp_path)
    with pytest.raises(ValueError, match="separate"):
        build_research_data(src, src, all_existing=True)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True)
    with pytest.raises(FileExistsError):
        build_research_data(src, out, all_existing=True)


def test_shared_h4_daily_research_frames_and_real_dice_path_parity(tmp_path, monkeypatch):
    # Sparse synthetic M1: one observed minute/hour, so gaps stay explicit.
    frame = _h1(n=3200, drift=0.0003)
    frame["tick_volume"] = 1
    src = _sources(tmp_path, frame=frame)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True, chunk_rows=777)
    setup = _setup(exec_hours=4, reg_hours=24, execution="H4", regime="D1",
                   research_data_dir=str(out), default_lot=0.01)
    setup["position_checks"] = "H4"
    setup["strategy"].update(bias_ema_fast_period=2, bias_ema_slow_period=5,
        use_atr_sep=False, use_e1_setup=False, use_e1_trigger=False,
        use_hr2=False, use_hr3=False, use_hr4=False, use_ext=False, use_w1=False)
    path = src / "EURUSD_H1.csv"
    raw, execution, regime, closed = load_chart_frames("EURUSD", path, 4, 24, out)
    assert len(raw) == 3200 and len(execution) == 800 and len(regime) == 134
    assert closed is True
    args = SimpleNamespace(exec_hours=4, reg_hours=24, research_data_dir=str(out),
        position_checks="H4", no_trade_ranges=(), risk_usd=3.0, max_cost_ratio=0.1,
        lot=None, scope_low=0, scope_high=0, stop_sizing={}, default_lot=0.01)
    expected = run_pair("EURUSD", path, setup["strategy"], _zero_costs(), args)["trades"]
    monkeypatch.setattr(dp, "_STATE", {})
    _, actual, _ = dp._real_one("EURUSD", str(path), _zero_costs(), setup)
    assert len(expected) > 0
    pd.testing.assert_frame_equal(actual, expected)
    env = dp.build_env("EURUSD", path, _zero_costs(), setup)
    assert len(env["atr"]) == len(execution)
    candidates = dp._Stream(env, "B", np.random.default_rng(42)).draw(10)
    assert candidates
    assert all(c["time"] in set(execution["time"]) for c in candidates)
    assert all(c["direction"] == env["mapped"].iloc[c["t"]]["direction"] for c in candidates)
    mapped = map_bias(execution, regime, bias_frames(regime, setup["strategy"]),
                      reg_hours=24, exec_hours=4, broker_bars=True)
    pd.testing.assert_frame_equal(mapped, env["mapped"])


def test_unknown_dice_mode_or_missing_direction_map_is_rejected():
    with pytest.raises(ValueError, match="mode"):
        dp.eligible_bars({}, "unknown")
    with pytest.raises(ValueError, match="direction map"):
        dp.eligible_bars({}, "B")


def test_reference_timeframes_and_research_identity_checked_before_simulation(tmp_path):
    setup = {"execution": "H4", "regime": "D1", "research_data": {"manifest_sha256": "new"}}
    (tmp_path / "params.json").write_text(json.dumps({"timeframes": {
        "execution": "H1", "regime": "H4"}}))
    with pytest.raises(ValueError, match="timeframes"):
        dp.validate_reference_setup(setup, tmp_path)
    (tmp_path / "params.json").write_text(json.dumps({"timeframes": {
        "execution": "H4", "regime": "D1"}, "research_data": {"manifest_sha256": "old"}}))
    with pytest.raises(ValueError, match="manifest"):
        dp.validate_reference_setup(setup, tmp_path)


def test_research_chart_missing_cannot_fall_back_to_h1(tmp_path):
    src = _sources(tmp_path)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True, timeframes=("H4",))
    with pytest.raises(KeyError):
        load_chart_frames("EURUSD", src / "EURUSD_H1.csv", 4, 24, out)


def test_report_uses_research_charts_and_warns_without_resample(tmp_path, monkeypatch):
    from quant import report
    from tests.test_report import _run_dir, _blob

    run, src, _ = _run_dir(tmp_path)
    minutes = pd.read_csv(src / "S1_H1.csv")
    minutes["tick_volume"] = 1
    minutes.to_csv(src / "S1_M1.csv", index=False)
    out = tmp_path / "research"
    build_research_data(src, out, all_existing=True)
    params = {"research_data": research_info(out), "data_dir": str(src),
              "timeframes": {"execution": "H4", "regime": "D1"}}
    (run / "params.json").write_text(json.dumps(params))
    def forbidden(*args, **kwargs):
        pytest.fail("research reports must not fall back to broker files or H1 resampling")
    monkeypatch.setattr(report, "_tf_bars", forbidden)
    assert report.write_report(run, Path("data"))
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "RESEARCH ONLY" in html
    payload = _blob(html, "trades-json")
    assert not any(r["missing"] for r in payload["meta"])
    assert payload["tf"] == {"exec": "H4", "reg": "Daily"}
    # Changing the manifest after a run must not substitute a new research dataset.
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["built_at_utc"] = "changed"
    (out / "manifest.json").write_text(json.dumps(manifest))
    assert report.write_report(run, Path("data"))
    payload = _blob((run / "report.html").read_text(encoding="utf-8"), "trades-json")
    assert all(r["missing"] for r in payload["meta"])


def test_reference_settings_match_and_changed_costs_are_rejected(tmp_path):
    setup = _setup(default_lot=0.01, stop_sizing={}, execution="H4", regime="D1",
                   research_data=None, jobs=[("EURUSD", "unused.csv", _zero_costs())])
    params = {"timeframes": {"execution": "H4", "regime": "D1"},
        "strategy": setup["strategy"], "jobs": [["EURUSD", "unused.csv"]],
        "costs": _zero_costs(), "position_checks": setup["position_checks"],
        "max_cost_ratio": setup["max_cost_ratio"], "default_lot": 0.01}
    (tmp_path / "params.json").write_text(json.dumps(params))
    dp.validate_reference_setup(setup, tmp_path)
    params["costs"]["spread_points"] = 100
    (tmp_path / "params.json").write_text(json.dumps(params))
    with pytest.raises(ValueError, match="costs"):
        dp.validate_reference_setup(setup, tmp_path)


@pytest.mark.parametrize("old_timing", [None, "closed_rows_v1"])
def test_reference_must_use_corrected_simulation_timing(tmp_path, old_timing):
    from quant.backtest import SIMULATION_TIMING

    setup = _setup(default_lot=0.01, stop_sizing={}, execution="H4", regime="D1",
                   research_data=None, jobs=[("EURUSD", "unused.csv", _zero_costs())],
                   coarse_exit_timing="bar_close", simulation_timing=SIMULATION_TIMING)
    params = {"timeframes": {"execution": "H4", "regime": "D1"},
              "strategy": setup["strategy"], "jobs": [["EURUSD", "unused.csv"]],
              "costs": _zero_costs(), "position_checks": setup["position_checks"],
              "max_cost_ratio": setup["max_cost_ratio"], "default_lot": 0.01,
              "coarse_exit_timing": "bar_close", "simulation_timing": old_timing}
    (tmp_path / "params.json").write_text(json.dumps(params))
    with pytest.raises(ValueError, match="simulation timing"):
        dp.validate_reference_setup(setup, tmp_path)
    params["simulation_timing"] = SIMULATION_TIMING
    (tmp_path / "params.json").write_text(json.dumps(params))
    dp.validate_reference_setup(setup, tmp_path)


def test_full_trade_parity_rejects_equal_totals_with_different_entries(tmp_path):
    trades = pd.DataFrame([{"entry_time": "2020-01-01 00:00+00:00",
        "exit_time": "2020-01-01 04:00+00:00", "pnl_usd": 1.0, "pnl_R": 1.0}])
    trades.to_csv(tmp_path / "trades_EURUSD.csv", index=False)
    total = {"trades": 1, "net_usd": 1.0, "expect_R": 1.0, "swap_usd": 0.0}
    pd.DataFrame([{"symbol": "TOTAL", **total}]).to_csv(tmp_path / "summary.csv", index=False)
    changed = trades.copy()
    changed.loc[0, "entry_time"] = "2020-01-01 01:00+00:00"
    ok, detail = dp.check_parity({"EURUSD": 1}, total, tmp_path, {"EURUSD": changed})
    assert not ok and "trade-level parity failed" in detail["diffs"][0]
