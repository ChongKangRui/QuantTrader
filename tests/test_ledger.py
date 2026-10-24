"""Ledger tests: one clean row per run folder; blanks for off gates; backfill."""

import csv
import json

import pandas as pd

from quant.ledger import COLUMNS, append, rebuild


def _run_dir(tmp_path, name: str = "20260102_030405") -> "tuple":
    """A finished-looking run: params.json + summary.csv TOTAL + trades file."""
    root = tmp_path / "backtest_results"
    run = root / name
    root.mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True, exist_ok=True)
    (run / "params.json").write_text(json.dumps({
        "strategy": {"use_e1_setup": True, "use_e1_trigger": True, "use_hr2": True,
                     "use_trail": False, "h1_ema_fast": 20, "h1_ema_slow": 50,
                     "h4_ema_fast": 20, "h4_ema_slow": 50, "h4_atr_n": 14,
                     "atr_n": 7, "warmup_bars": 100, "lookback": 5, "sep_atr": 0.3,
                     "stop_atr": 1.5, "tp_mult": 3.0},
        "costs": {"spread_points": 20, "slippage_pips": 0.3,
                  "swap_long_per_0_01": 0.0, "swap_short_per_0_01": 0.0,
                  "commission_per_lot": 0.0},
        "sizing_scope_usd": {"low": 2.5, "high": 3.6}, "lot": None,
        "max_trades_per_day": 20, "workers": 4, "position_checks": "M1",
        "no_trade_ranges": [{"start": "12-15", "end": "01-01"}],
        "max_cost_ratio": 0.10, "benchmarks": {"account_usd": 100},
        "pair_costs": {"AUDUSD": {"swap_long_per_0_01": -0.08}},
    }), encoding="utf-8")
    pd.DataFrame([{"symbol": "AUDUSD", "trades": 2, "win_rate": 0.5,
                   "profit_factor": 1.2, "expect_R": 0.05, "verdict": "WARN",
                   "net_usd": 1.0, "net_R": 1.0, "max_dd": 0.5},
                  {"symbol": "TOTAL", "trades": 2, "win_rate": 0.5,
                   "profit_factor": 1.2, "expect_R": 0.05, "verdict": "WARN",
                   "net_usd": 1.0, "net_R": 1.0, "max_dd": 0.5}]).to_csv(
        run / "summary.csv", index=False)
    pd.DataFrame([{"swap": -0.08}, {"swap": -1.5}]).to_csv(
        run / "trades_AUDUSD.csv", index=False)
    return root, run


def _rows(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_append_writes_header_once_and_row_is_right(tmp_path):
    root, run = _run_dir(tmp_path)
    append(run)
    append(run)  # second call: row appended, no second header
    rows = _rows(root / "_ledger.csv")
    assert len(rows) == 2
    r = rows[-1]
    assert r["use_e1_setup"] == "Y" and r["use_e1_trigger"] == "Y" \
        and r["use_hr2"] == "Y"                      # enabled gates say Y
    assert r["use_trail"] == "" and r["use_hr3"] == "" and r["use_be"] == ""
    assert r["h1_ema_fast"] == "20" and r["sizing_scope"] == "2.5-3.6"
    assert r["run_folder"] == "20260102_030405"
    assert r["run_time"] == "2026-01-02 03:04:05"
    assert r["verdict"] == "WARN" and r["win_pct"] == "50"
    assert r["net_pnl_usd"] == "1" and r["max_dd_closed_pct"] == "0.5"
    assert r["max_dd_mtm_usd"] == ""       # no MTM curve in this fixture
    assert r["swap_total_usd"] == "-1.58"  # sum of per-trade swap
    assert r["swaps_applied"] == "Y"       # pair yaml carries a nonzero swap
    assert r["no_trade_ranges"] == "12-15..01-01"
    assert r["symbols"] == "AUDUSD" and r["pairs"] == "1"
    assert r["daily_cap"] == "20"
    assert r["notes"] == ""


def test_new_role_named_params_fill_existing_ledger_columns(tmp_path):
    root, run = _run_dir(tmp_path)
    params_path = run / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))
    params["strategy"].update({
        "entry_ema_fast_period": 18, "entry_ema_slow_period": 80,
        "bias_ema_fast_period": 24, "bias_ema_slow_period": 120,
        "bias_atr_period": 21, "entry_atr_period": 14})
    params_path.write_text(json.dumps(params), encoding="utf-8")
    append(run)
    row = _rows(root / "_ledger.csv")[0]
    assert [row[k] for k in ("h1_ema_fast", "h1_ema_slow", "h4_ema_fast",
                             "h4_ema_slow", "h4_atr_n", "atr_n")] == [
                                 "18", "80", "24", "120", "21", "14"]


def test_ledger_records_the_widened_stop_mode(tmp_path):
    root, run = _run_dir(tmp_path)
    params_path = run / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8"))
    params["default_lot"] = 0.02
    params["stop_sizing"] = {"widen_stop_to_scope": True, "fixed_lot": 0.01,
                              "max_stop_atr": 3.0, "increase_lots_if_widening_fails": True}
    params_path.write_text(json.dumps(params), encoding="utf-8")
    append(run)
    row = _rows(root / "_ledger.csv")[0]
    assert row["widen_stop"] == "Y"
    assert row["default_lot"] == "0.02"
    assert row["increase_lots_if_widening_fails"] == "Y"
    assert row["stop_lot"] == "0.01" and row["stop_max_atr"] == "3"


def test_incomplete_folder_is_skipped(tmp_path):
    root, _ = _run_dir(tmp_path)
    (root / "half_run").mkdir()
    (root / "half_run" / "summary.csv").touch()   # no params.json -> not a run
    assert append(root / "half_run") is None
    assert not (root / "_ledger.csv").exists()


def test_rebuild_covers_all_runs_drops_broken(tmp_path):
    root, run = _run_dir(tmp_path)
    _run_dir(tmp_path, "20260203_040506_trail_1R")  # stamp prefix + custom suffix
    (root / "broken_run").mkdir()  # empty folder: no artifacts
    path, n = rebuild(root)
    rows = _rows(path)
    assert (path.name, n) == ("_ledger.csv", 2)
    assert rows[0]["run_folder"] == "20260102_030405"
    assert rows[1]["run_folder"] == "20260203_040506_trail_1R"
    assert rows[1]["run_time"] == "2026-02-03 04:05:06"  # time parsed from prefix
    assert len(rows) == len({r["run_folder"] for r in rows})  # one row per folder
    assert set(rows[0]) == set(COLUMNS)  # schema is the single source of truth


def test_timeframe_suffixes_keep_ledger_append_and_rebuild_compatible(tmp_path):
    names = ["20261022_213000_H4_H1", "20261022_213001_D_H4", "20261022_213002_D_H1"]
    for name in names:
        root, run = _run_dir(tmp_path, name)
        append(run)
    original = _rows(root / "_ledger.csv")
    assert [row["run_folder"] for row in original] == names
    assert [row["run_time"] for row in original] == [
        "2026-10-22 21:30:00", "2026-10-22 21:30:01", "2026-10-22 21:30:02"]
    path, count = rebuild(root)
    assert count == 3 and _rows(path) == original
