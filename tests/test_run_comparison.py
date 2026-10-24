"""Saved-artifact comparisons only: synthetic data, no actual-history backtest or terminal."""
import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

from quant import ledger, report


def _run(root, number, *, net=10.0, dd=20.0, trades=2, pf=1.5, completed=True):
    run = root / f"20261023_{number:06d}_H4_H4"
    run.mkdir(parents=True)
    frame = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC"),
                          "open": [1.1, 1.2, 1.3], "high": [1.2, 1.3, 1.4],
                          "low": [1.0, 1.1, 1.2], "close": [1.15, 1.25, 1.35]})
    identity = ledger.data_identity(frame)
    params = {"jobs": [["EURUSD", "not-read.csv"]], "run_status": "completed" if completed else "running",
              "completed_at_utc": f"2026-10-23T00:{number:02d}:00+00:00",
              "comparison_mtm_symbols": ["EURUSD"] if trades else [],
              "comparison_mtm_drawdown_usd": dd,
              "strategy": {"tp_mult": 10}, "benchmarks": {"account_usd": 100},
              "backtest_comparison": {"enabled": True, "max_drawdown_pct": 50.0},
              "timeframes": {"execution": "H4", "regime": "H4"}, "position_checks": "H4",
              "raw_tape_tf": "H4", "coarse_exit_timing": "bar_close",
              "broker_data": {"source_type": "synthetic_broker"}, "default_lot": 0.01}
    results = {"EURUSD": {"comparison_inputs": {"raw": identity, "execution": identity,
        "regime": identity, "broker_bars": True, "minute_checks": None, "converters": {}},
        "comparison_costs": {"spread_points": 20, "slippage_pips": 0.0}}}
    params["comparison_context"] = ledger.comparison_context(params, results)
    (run / "params.json").write_text(json.dumps(params), encoding="utf-8")
    row = {"trades": trades, "net_usd": net, "max_dd_mtm": dd, "max_dd_mtm_pct": round(dd, 1),
           "max_dd": 0, "win_rate": 0.5, "profit_factor": pf}
    pd.DataFrame([{**row, "symbol": "EURUSD"}, {**row, "symbol": "TOTAL"}]).to_csv(
        run / "summary.csv", index=False)
    pd.DataFrame({"pnl_usd": [net / trades] * trades if trades else []}).to_csv(
        run / "trades_EURUSD.csv", index=False)
    return run


def _change_params(run, change):
    path = run / "params.json"
    params = json.loads(path.read_text(encoding="utf-8"))
    change(params)
    path.write_text(json.dumps(params), encoding="utf-8")


def test_first_comparable_run_gets_marker_without_folder_rename(tmp_path):
    run = _run(tmp_path, 1)
    result = ledger.compare_run(run)
    assert result["is_best"] and result["previous"] is None
    assert result["delta_vs_previous"] is None and result["comparable_runs"] == 1
    marker = json.loads((run / "BEST.txt").read_text())
    assert marker["run"] == run.name and marker["max_drawdown_pct"] == 50
    assert (run / "summary.csv").exists()
    assert json.loads((run / "comparison.json").read_text()) == result


def test_comparison_groups_distinguish_evaluation_window_even_on_same_prices(tmp_path):
    run = _run(tmp_path, 1)
    params = json.loads((run / "params.json").read_text())
    original = params["comparison_context"]
    params["evaluation_window"] = {"enabled": True, "start": "2020-01-01", "end": "2021-01-01"}
    results = {"EURUSD": {"comparison_inputs": original["inputs"]["EURUSD"],
                           "comparison_costs": original["costs"]["EURUSD"]}}
    changed = ledger.comparison_context(params, results)
    assert changed["evaluation_window"] == params["evaluation_window"]
    assert ledger._json_key(original) != ledger._json_key(changed)


def test_improvement_compares_previous_and_moves_only_managed_marker(tmp_path):
    first = _run(tmp_path, 1)
    ledger.compare_run(first)
    second = _run(tmp_path, 2, net=30, dd=15, pf=2)
    result = ledger.compare_run(second)
    assert result["is_best"] and result["previous"]["run"] == first.name
    assert result["previous_best"]["run"] == first.name
    assert result["delta_vs_previous"] == {
        "net_usd": 20, "max_dd_pct": -5, "win_rate_pct": 0, "profit_factor": 0.5, "trades": 0}
    assert not (first / "BEST.txt").exists() and (second / "BEST.txt").exists()


def test_higher_profit_cannot_win_above_ceiling_and_previous_is_not_previous_best(tmp_path):
    first = _run(tmp_path, 1, net=20)
    ledger.compare_run(first)
    second = _run(tmp_path, 2, net=100, dd=51)
    rejected = ledger.compare_run(second)
    assert not rejected["is_best"] and not rejected["current"]["eligible"]
    third = _run(tmp_path, 3, net=25)
    result = ledger.compare_run(third)
    assert result["previous"]["run"] == second.name
    assert result["previous_best"]["run"] == first.name
    assert result["delta_vs_previous"]["net_usd"] == -75
    assert result["delta_vs_previous_best"]["net_usd"] == 5
    assert result["is_best"]


@pytest.mark.parametrize("dd,eligible", [(50, True), (50.004, False), (0, True)])
def test_ceiling_uses_mtm_usd_not_rounded_percent_or_closed_drawdown(tmp_path, dd, eligible):
    run = _run(tmp_path, 1, dd=dd)
    summary = pd.read_csv(run / "summary.csv")
    summary["max_dd_mtm"] = round(dd, 2)
    summary.to_csv(run / "summary.csv", index=False)
    assert ledger.compare_run(run)["current"]["eligible"] is eligible


def test_profit_ties_prefer_lower_drawdown_then_older_completion(tmp_path):
    first = _run(tmp_path, 1, dd=20)
    second = _run(tmp_path, 2, dd=10)
    third = _run(tmp_path, 3, dd=10)
    result = ledger.compare_run(third)
    assert result["best"]["run"] == second.name
    assert not (first / "BEST.txt").exists() and (second / "BEST.txt").exists()


@pytest.mark.parametrize("part,replacement", [
    ("simulation_timing", "closed_rows_v1"),
    ("timeframes", {"execution": "H4", "regime": "D1"}),
    ("account_usd", 200), ("position_checks", "M1"), ("max_drawdown_pct", 30),
    ("costs", {"EURUSD": {"spread_points": 40, "slippage_pips": 0.0}}),
    ("sizing", {"default_lot": 0.02}), ("source", {"broker_mode": False}),
    ("inputs", {"EURUSD": {"prices": "another-history"}}),
])
def test_incompatible_runs_are_not_ranked_together(tmp_path, part, replacement):
    first = _run(tmp_path, 1)
    ledger.compare_run(first)
    second = _run(tmp_path, 2, net=100)
    _change_params(second, lambda p: p["comparison_context"].update({part: replacement}))
    result = ledger.compare_run(second)
    assert result["previous"] is None and result["comparable_runs"] == 1
    assert result["excluded_runs"] == 1
    assert (first / "BEST.txt").exists() and (second / "BEST.txt").exists()


def test_strategy_changes_are_allowed_but_input_content_changes_are_not(tmp_path):
    first = _run(tmp_path, 1)
    second = _run(tmp_path, 2, net=30)
    _change_params(second, lambda p: p["strategy"].update(tp_mult=4, use_trail=False))
    assert ledger.compare_run(second)["previous"]["run"] == first.name
    frame = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=2, tz="UTC"), "close": [1, 2]})
    identity = ledger.data_identity(frame)
    assert identity == ledger.data_identity(frame.copy())
    frame.loc[1, "close"] = 3
    assert identity["sha256"] != ledger.data_identity(frame)["sha256"]
    assert identity["first"] == ledger.data_identity(frame)["first"]


@pytest.mark.parametrize("damage", ["running", "failed", "legacy", "missing_trade", "partial_trade", "partial_summary",
                                        "partial_mtm", "missing_raw_mtm",
                                        "missing_mtm", "nan_profit", "bad_count", "bad_total_net", "malformed_json"])
def test_failed_partial_legacy_and_corrupt_runs_are_excluded(tmp_path, damage):
    first = _run(tmp_path, 1)
    bad = _run(tmp_path, 2, net=100)
    if damage in ("running", "failed"):
        _change_params(bad, lambda p: p.update(run_status=damage))
    elif damage == "legacy":
        _change_params(bad, lambda p: p.pop("comparison_context"))
    elif damage == "partial_mtm":
        _change_params(bad, lambda p: p.update(comparison_mtm_symbols=[]))
    elif damage == "missing_raw_mtm":
        _change_params(bad, lambda p: p.pop("comparison_mtm_drawdown_usd"))
    elif damage == "missing_trade":
        (bad / "trades_EURUSD.csv").unlink()
    elif damage == "partial_trade":
        pd.DataFrame({"pnl_usd": [50]}).to_csv(bad / "trades_EURUSD.csv", index=False)
    elif damage == "malformed_json":
        (bad / "params.json").write_text("not json")
    else:
        path = bad / "summary.csv"
        summary = pd.read_csv(path)
        if damage == "partial_summary":
            summary = summary[summary.symbol == "TOTAL"]
        elif damage == "missing_mtm":
            summary = summary.drop(columns="max_dd_mtm")
        elif damage == "nan_profit":
            summary.loc[summary.symbol == "TOTAL", "net_usd"] = float("nan")
        elif damage == "bad_total_net":
            summary.loc[summary.symbol == "TOTAL", "net_usd"] = 1000
        else:
            summary.loc[summary.symbol == "TOTAL", "trades"] = 3
        summary.to_csv(path, index=False)
    result = ledger.compare_run(first)
    assert result["best"]["run"] == first.name and result["comparable_runs"] == 1
    assert not (bad / "BEST.txt").exists()


def test_zero_trade_run_is_compared_but_cannot_win(tmp_path):
    first = _run(tmp_path, 1, net=-5)
    ledger.compare_run(first)
    empty = _run(tmp_path, 2, net=0, dd=0, trades=0, pf=0)
    summary = pd.read_csv(empty / "summary.csv")
    summary[summary.symbol != "TOTAL"].to_csv(empty / "summary.csv", index=False)
    result = ledger.compare_run(empty)
    assert result["best"]["run"] == first.name
    assert result["delta_vs_previous"]["net_usd"] == 5
    assert not (empty / "BEST.txt").exists()


def test_all_win_profit_factor_keeps_valid_json_and_reports_no_infinite_delta(tmp_path):
    first = _run(tmp_path, 1, pf=float("inf"))
    ledger.compare_run(first)
    second = _run(tmp_path, 2, net=20, pf=float("inf"))
    result = ledger.compare_run(second)
    assert result["current"]["metrics"]["profit_factor"] == "Infinity"
    assert result["delta_vs_previous"]["profit_factor"] is None
    json.loads((second / "comparison.json").read_text(),
               parse_constant=lambda s: pytest.fail(f"invalid JSON constant {s}"))


def test_disabled_comparison_and_unmanaged_marker_are_not_overwritten(tmp_path):
    run = _run(tmp_path, 1)
    _change_params(run, lambda p: p["backtest_comparison"].update(enabled=False))
    assert ledger.compare_run(run) is None
    assert not (run / "comparison.json").exists()
    _change_params(run, lambda p: p["backtest_comparison"].update(enabled=True))
    (run / "BEST.txt").write_text("User's own notes", encoding="utf-8")
    with pytest.raises((ValueError, FileExistsError)):
        ledger.compare_run(run)
    assert (run / "BEST.txt").read_text() == "User's own notes"


def test_simultaneous_comparisons_leave_only_one_group_winner(tmp_path):
    first, second = _run(tmp_path, 1), _run(tmp_path, 2, net=30)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ledger.compare_run, [first, second]))
    assert all(result["best"]["run"] == second.name for result in results)
    assert not (first / "BEST.txt").exists() and (second / "BEST.txt").exists()


def test_settings_inherit_existing_ceiling_and_can_be_disabled_or_overridden():
    base = {"benchmarks": {"max_dd_pct": {"good": 30, "ok": 50}}}
    assert ledger.comparison_settings(base) == {"enabled": True, "max_drawdown_pct": 50}
    assert ledger.comparison_settings(base, max_drawdown_pct=25)["max_drawdown_pct"] == 25
    assert ledger.comparison_settings({"backtest_comparison": {"max_drawdown_pct": 20}})["max_drawdown_pct"] == 20
    assert ledger.comparison_settings(base, enabled=False)["enabled"] is False
    assert ledger.comparison_settings({})["max_drawdown_pct"] is None


@pytest.mark.parametrize("raw", [{"enabled": "false"}, {"max_drawdown_pct": True},
    {"max_drawdown_pct": 0}, {"max_drawdown_pct": -1}, {"max_drawdown_pct": float("nan")},
    {"max_drawdown_pct": float("inf")}, {"max_drawdown_pct": "50"}, []])
def test_invalid_comparison_controls_rejected(raw):
    with pytest.raises(ValueError):
        ledger.comparison_settings({"backtest_comparison": raw})


def test_no_configured_ceiling_or_no_mtm_cannot_win(tmp_path):
    run = _run(tmp_path, 1)
    _change_params(run, lambda p: p["comparison_context"].update(max_drawdown_pct=None))
    result = ledger.compare_run(run)
    assert result["best"] is None and not (run / "BEST.txt").exists()


def test_report_includes_comparison_and_escapes_saved_folder_names(tmp_path):
    run = _run(tmp_path / "results", 1)
    saved = ledger.compare_run(run)
    saved["current"]["run"] = '<img src=x onerror="alert(1)">'
    (run / "comparison.json").write_text(json.dumps(saved), encoding="utf-8")
    html = report._comparison_html(run)
    assert 'id="run-comparison"' in html and "BEST SO FAR" in html
    assert "&lt;img" in html and '<img src=x' not in html
    assert "best historical results" in html.lower()
    from tests.test_report import _run_dir
    report_run, data, _ = _run_dir(tmp_path)
    (report_run / "comparison.json").write_text(json.dumps(saved), encoding="utf-8")
    assert report.write_report(report_run, data)
    assert 'id="run-comparison"' in (report_run / "report.html").read_text(encoding="utf-8")
    assert not (report_run / "BEST.txt").exists()  # Rendering does not rerank or move markers.
    (report_run / "comparison.json").write_text("broken json")
    assert report._comparison_html(report_run) == ""


@pytest.mark.parametrize("profit_factor,label", [
    (1.25, "1.25"), (1.234, "1.23"), (0, "0.00"), (float("inf"), "inf"),
    (None, "NA"), (float("nan"), "NA"), (-1, "NA"),
])
def test_profit_factor_folder_suffix_preserves_saved_artifacts(tmp_path, profit_factor, label):
    from quant import backtest

    run = tmp_path / "20261023_213000_D_H4"
    run.mkdir()
    snapshot = b"# exact source\r\nstrategy: {}\r\n"
    (run / "config.yaml").write_bytes(snapshot)
    old = tmp_path / "20261022_213000_D_H4"
    old.mkdir()
    renamed = backtest.add_profit_factor_suffix(run, profit_factor)
    assert renamed.name == f"20261023_213000_D_H4_PF{label}"
    assert (renamed / "config.yaml").read_bytes() == snapshot
    assert not run.exists() and old.exists()
    assert ledger._stamp(renamed.name) == "2026-10-23 21:30:00"


@pytest.mark.parametrize("collision", [False, True])
def test_profit_factor_folder_rename_failure_keeps_original(tmp_path, monkeypatch, capsys, collision):
    from pathlib import Path
    from quant import backtest

    run = tmp_path / "new_run"
    run.mkdir()
    (run / "config.yaml").write_text("# original\n")
    destination = tmp_path / "new_run_PF1.25"
    if collision:
        destination.mkdir()
        (destination / "notes.txt").write_text("user work")
    else:
        def blocked_rename(*args):
            raise PermissionError("folder locked")
        monkeypatch.setattr(Path, "rename", blocked_rename)
    assert backtest.add_profit_factor_suffix(run, 1.25) == run
    assert (run / "config.yaml").read_text() == "# original\n"
    assert "profit-factor folder suffix skipped:" in capsys.readouterr().out
    if collision:
        assert (destination / "notes.txt").read_text() == "user work"


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("pnls,label", [
    ([10, -5], "2.00"), ([10], "inf"), ([-5], "0.00"), ([], "NA"),
])
def test_backtest_finalization_compares_before_rendering_with_no_real_simulation(
        tmp_path, monkeypatch, enabled, failed, pnls, label):
    from quant import backtest

    config = tmp_path / "configs"
    config.mkdir()
    (config / "_base.yaml").write_text(
        "timeframes: {execution: H1, regime: H1, position_checks: H1}\n"
        "benchmarks: {account_usd: 100, max_dd_pct: {ok: 50}}\n", encoding="utf-8")
    pair = config / "EURUSD.yaml"
    pair.write_text("symbol: EURUSD\n", encoding="utf-8")
    tape = tmp_path / "EURUSD_H1.csv"
    bars = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
                         "open": [1.1] * 3, "high": [1.12] * 3,
                         "low": [1.09] * 3, "close": [1.11] * 3})
    bars.to_csv(tape, index=False)
    trades = pd.DataFrame([{"symbol": "EURUSD", "entry_time": str(bars.time.iloc[1]),
        "exit_time": str(bars.time.iloc[2]), "entry": 1.1, "sl": 1.09,
        "direction": "LONG", "lot": 0.01, "pnl_usd": 10, "pnl_R": 2,
        "swap": 0, "risk_usd": 5, "bars_held": 1}])
    template = trades.iloc[0].to_dict()
    trades = pd.DataFrame([{**template, "pnl_usd": pnl, "pnl_R": pnl / 5,
                            "entry_time": str(pd.Timestamp(template["entry_time"]) + pd.Timedelta(days=i)),
                            "exit_time": str(pd.Timestamp(template["exit_time"]) + pd.Timedelta(days=i))}
                           for i, pnl in enumerate(pnls)],
                          columns=trades.columns)
    result = {"trades": trades, "funnel": pd.DataFrame([{"scanned": 1}]),
              "metrics": {**backtest.metrics(trades, 1, 3), "symbol": "EURUSD", "signals": 1},
              "n_bars": 3, "span_days": 1,
              "comparison_inputs": {"raw": ledger.data_identity(bars), "execution": ledger.data_identity(bars)},
              "comparison_costs": {}}

    def fake_run_all(jobs, strategy, args, converters, workers):
        assert args.compare_results is enabled
        return {"EURUSD": result}, {"GBPUSD": "synthetic failure"} if failed else {}

    rendered = []

    def fake_report(run):
        rendered.append(run)
        assert run.name.endswith(f"_PF{label}") is (not failed)
        assert (run / "config.yaml").read_bytes() == (config / "_base.yaml").read_bytes()
        params = json.loads((run / "params.json").read_text())
        assert params["run_status"] == ("failed" if failed else "completed")
        assert params["simulation_timing"] == backtest.SIMULATION_TIMING
        if enabled and not failed:
            assert params["comparison_context"]["simulation_timing"] == backtest.SIMULATION_TIMING
        assert params["backtest_comparison"]["max_drawdown_pct"] == (15 if enabled else None)
        assert (run / "comparison.json").exists() is enabled
        assert (run / "BEST.txt").exists() is (enabled and not failed and bool(pnls))
        if enabled and not failed:
            comparison = json.loads((run / "comparison.json").read_text())
            assert comparison["current"]["run"] == run.name
            if pnls:
                assert comparison["best"]["run"] == run.name
            else:
                assert comparison["best"] is None
        return True

    monkeypatch.setattr(backtest, "run_all", fake_run_all)
    original_mtm = backtest.mtm_equity

    def checked_mtm(trades, tapes, *args, **kwargs):
        pd.testing.assert_series_equal(tapes["EURUSD"]["time"], bars["time"] + pd.Timedelta(hours=1))
        return original_mtm(trades, tapes, *args, **kwargs)

    monkeypatch.setattr(backtest, "mtm_equity", checked_mtm)
    monkeypatch.setattr(backtest, "simulate", lambda *a, **kw: pytest.fail("must not simulate"))
    monkeypatch.setattr(report, "try_write_report", fake_report)
    output = tmp_path / "results"
    assert backtest.main(["--config-dir", str(config), "--config", str(pair), "--data", str(tape),
        "--results-dir", str(output), "--jobs", "1"] +
        (["--comparison-max-dd-pct", "15"] if enabled else ["--no-compare-results"])) == 0
    assert len(rendered) == 1
    rows = pd.read_csv(output / "_ledger.csv")
    assert rows["run_folder"].tolist() == [rendered[0].name]


@pytest.mark.parametrize("fingerprint_fails", [False, True])
def test_worker_records_actual_frames_feeds_and_effective_costs_without_simulation(monkeypatch, fingerprint_fails):
    from types import SimpleNamespace
    from quant import backtest

    frame = pd.DataFrame({"time": pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC"),
                          "open": [1.1] * 3, "high": [1.2] * 3, "low": [1.0] * 3, "close": [1.15] * 3})
    feed = frame.set_index("time")["close"]
    costs = {"spread_points": 35, "slippage_pips": 0.5}
    monkeypatch.setattr(backtest, "load_chart_frames", lambda *a: (frame, frame, frame, True))
    monkeypatch.setattr(backtest, "scan_pair", lambda *a, **kw: (pd.DataFrame([{"scanned": 3}]), []))
    monkeypatch.setattr(backtest, "simulate", lambda *a, **kw: (pd.DataFrame(), {"sized": 0}))
    args = SimpleNamespace(exec_hours=4, reg_hours=4, position_checks="H4", risk_usd=3,
                           max_cost_ratio=0.1, lot=None, compare_results=True)
    if fingerprint_fails:
        def broken_identity(frame):
            raise RuntimeError("fingerprint unavailable")
        monkeypatch.setattr(ledger, "data_identity", broken_identity)
    saved = backtest.run_pair("EURUSD", "not-read.csv", {}, costs, args, {"USDJPY": feed})
    assert saved["metrics"]["trades"] == 0
    if fingerprint_fails:
        assert saved["comparison_error"] == "fingerprint unavailable"
        return
    assert saved["comparison_inputs"]["raw"] == ledger.data_identity(frame)
    assert saved["comparison_inputs"]["minute_checks"] is None
    assert saved["comparison_inputs"]["converters"]["USDJPY"] == ledger.data_identity(feed)
    assert saved["comparison_costs"] == costs
