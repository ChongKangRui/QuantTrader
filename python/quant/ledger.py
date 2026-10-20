"""Run ledger: one CSV row per backtest run, <results-dir>/_ledger.csv.

append(run_dir) is called by the backtest as each run finishes; rebuild() is a
CLI backfill over existing run folders. Both share _row_for_run(), which reads
ONLY the run folder itself (summary.csv TOTAL row, params.json, trades_*.csv)
so live rows and rebuilt rows can never drift apart.
A disabled gate is an empty cell, never a false. Read-only module: no orders.
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

LEDGER_NAME = "_ledger.csv"
_GATES = ("use_atr_sep", "use_e1_setup", "use_e1_trigger", "use_ext", "use_hr2",
          "use_hr3", "use_hr4", "use_trail", "use_be", "use_w1",
          "bias_flip_exit", "weekend_flat")
# knobs shown only while their owning gate is on
_LINKED = {  # gate -> ledger column(s)
    "use_e1_setup": ("lookback",),
    "use_atr_sep": ("sep_atr",),
}
COLUMNS = (
    ("run_folder", "run_time")
    + _GATES
    + ("h1_ema_fast", "h1_ema_slow", "h4_ema_fast", "h4_ema_slow", "h4_atr_n",
       "atr_n", "warmup_bars", "lookback", "sep_atr", "stop_atr", "tp_mult",
        "sizing_scope", "fixed_lot", "widen_stop", "stop_lot", "stop_max_atr",
        "increase_lots_if_widening_fails", "default_lot",
       "trades", "win_pct", "profit_factor", "expect_R", "verdict",
       "net_pnl_usd", "net_R", "max_dd_closed_usd", "max_dd_closed_pct",
       "max_dd_mtm_usd", "max_dd_mtm_pct",
       "swaps_applied", "swap_total_usd", "no_trade_ranges", "max_cost_ratio",
       "spread_points", "slippage_pips", "commission_per_lot", "pair_costs",
       "symbols", "pairs", "daily_cap", "position_checks", "notes")
)


def _s(v) -> str:
    """Compact cell text: blank for missing/NaN/False, int-form without .0."""
    if v is None or v != v:  # v != v is the NaN check
        return ""
    if isinstance(v, bool):
        return "Y" if v else ""
    if isinstance(v, float):
        if v == float("inf"):
            return "inf"
        return str(int(v)) if v == int(v) else str(round(v, 3))
    return str(v)


def _stamp(name: str) -> str:
    try:  # stamp is the 15-char prefix; custom suffixes like _no_trail keep it
        return datetime.strptime(name[:15], "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


def _row_for_run(run_dir: Path) -> dict | None:
    """Ledger row from a FINISHED run folder; None when unusable."""
    run_dir = Path(run_dir)
    row = {c: "" for c in COLUMNS}
    try:
        params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
        summary = pd.read_csv(run_dir / "summary.csv")
    except Exception:
        return None
    row["run_folder"] = run_dir.name
    row["run_time"] = _stamp(run_dir.name)
    st = params.get("strategy") or {}

    for g in _GATES:  # gates: Y or blank (never false)
        row[g] = "Y" if st.get(g) else ""
    # Keep historical CSV column names so appending to an existing ledger is safe.
    row["h1_ema_fast"] = _s(st.get("entry_ema_fast_period", st.get("h1_ema_fast", st.get("ema_fast"))))
    row["h1_ema_slow"] = _s(st.get("entry_ema_slow_period", st.get("h1_ema_slow", st.get("ema_slow"))))
    row["h4_ema_fast"] = _s(st.get("bias_ema_fast_period", st.get("h4_ema_fast")))
    row["h4_ema_slow"] = _s(st.get("bias_ema_slow_period", st.get("h4_ema_slow")))
    row["h4_atr_n"] = _s(st.get("bias_atr_period", st.get("h4_atr_n")))
    row["atr_n"] = _s(st.get("entry_atr_period", st.get("atr_n")))
    for k in ("warmup_bars", "stop_atr", "tp_mult"):
        row[k] = _s(st.get(k))
    for gate, cols in _LINKED.items():
        if st.get(gate):
            for col in cols:
                row[col] = _s(st.get(col))
    scope = params.get("sizing_scope_usd") or {}
    if scope.get("low") is not None:
        row["sizing_scope"] = f"{_s(scope.get('low'))}-{_s(scope.get('high'))}"
    row["fixed_lot"] = _s(params.get("lot"))
    row["default_lot"] = _s(params.get("default_lot"))
    # stop sizing: the widened-stop branch (fixed lot instead of more lots)
    stop_sizing = params.get("stop_sizing") or {}
    row["widen_stop"] = "Y" if stop_sizing.get("widen_stop_to_scope") else ""
    row["stop_lot"] = _s(stop_sizing.get("fixed_lot")) if row["widen_stop"] else ""
    row["stop_max_atr"] = _s(stop_sizing.get("max_stop_atr")) if row["widen_stop"] else ""
    row["increase_lots_if_widening_fails"] = (
        "Y" if row["widen_stop"] and stop_sizing.get("increase_lots_if_widening_fails") else "")

    tot = summary[summary["symbol"] == "TOTAL"]  # one row per run = portfolio row
    if len(tot):
        r = tot.iloc[0]
        wr = r.get("win_rate")
        row["trades"] = _s(r.get("trades"))
        row["win_pct"] = _s(round(100.0 * float(wr), 1)) if wr == wr else ""
        row["profit_factor"] = _s(r.get("profit_factor"))
        row["expect_R"] = _s(r.get("expect_R"))
        row["verdict"] = _s(r.get("verdict"))
        row["net_pnl_usd"] = _s(r.get("net_usd"))
        row["net_R"] = _s(r.get("net_R"))
        row["max_dd_closed_usd"] = _s(r.get("max_dd"))
        acct = float((params.get("benchmarks") or {}).get("account_usd") or 0)
        dd = r.get("max_dd")  # closed-only DD % needs the benchmark equity base
        if acct > 0 and dd == dd:
            row["max_dd_closed_pct"] = _s(round(100.0 * float(dd) / acct, 1))
        row["max_dd_mtm_usd"] = _s(r.get("max_dd_mtm"))
        row["max_dd_mtm_pct"] = _s(r.get("max_dd_mtm_pct"))

    trades_files = sorted(run_dir.glob("trades_*.csv"))
    swaps = []
    for f in trades_files:
        try:
            t = pd.read_csv(f)
        except Exception:
            continue  # corrupt file must not lose the rest of the row
        if "swap" in t.columns and len(t):
            swaps.append(float(t["swap"].sum()))
    if swaps:
        row["swap_total_usd"] = _s(sum(swaps))
    costs = params.get("costs") or {}
    pair_costs = params.get("pair_costs") or {}
    any_swap = any(float(costs.get(k) or 0) for k in
                   ("swap_long_per_0_01", "swap_short_per_0_01"))
    if isinstance(pair_costs, dict):
        any_swap = any_swap or any(
            any(float((v or {}).get(k) or 0) for k in
                ("swap_long_per_0_01", "swap_short_per_0_01"))
            for v in pair_costs.values())
    row["swaps_applied"] = "Y" if any_swap else ""
    ranges = params.get("no_trade_ranges") or []
    row["no_trade_ranges"] = "; ".join(  # shapes: ["12-15","01-01"] or {start,end}
        f"{(r_.get('start') if isinstance(r_, dict) else r_[0])}"
        f"..{(r_.get('end') if isinstance(r_, dict) else r_[1])}" for r_ in ranges)
    row["max_cost_ratio"] = _s(params.get("max_cost_ratio"))
    row["spread_points"] = _s(costs.get("spread_points"))
    row["slippage_pips"] = _s(costs.get("slippage_pips"))
    row["commission_per_lot"] = _s(costs.get("commission_per_lot"))
    row["pair_costs"] = "Y" if pair_costs else ""
    if trades_files:  # symbol list comes from the files that actually hold trades
        row["symbols"] = ", ".join(f.stem[len("trades_"):] for f in trades_files)
        row["pairs"] = str(len(trades_files))
    row["daily_cap"] = _s(params.get("max_trades_per_day"))
    row["position_checks"] = _s(params.get("position_checks"))
    return row


def append(run_dir: str | Path, results_dir: str | Path | None = None) -> Path | None:
    """Add one row for run_dir; header written only when the file is new.
    Returns the ledger path, or None when the folder is not a finished run."""
    row = _row_for_run(run_dir)
    if row is None:
        return None
    root = Path(results_dir) if results_dir else Path(run_dir).parent
    path = root / LEDGER_NAME
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS)
        if path.stat().st_size == 0:
            w.writeheader()  # file exists but is empty (also after a manual wipe)
        w.writerow(row)
    return path


def rebuild(results_dir: str | Path = "backtest_results") -> tuple[Path, int]:
    """Rebuild the whole ledger from folders with summary.csv + params.json."""
    root = Path(results_dir)
    rows = [r for d in sorted(root.iterdir()) if d.is_dir()
            for r in [_row_for_run(d)] if r is not None]
    path = root / LEDGER_NAME
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path, len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rebuild the backtest run ledger.")
    ap.add_argument("--dir", default="backtest_results")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    if a.rebuild:
        path, n = rebuild(a.dir)
        print(f"ledger {path}: {n} run(s)")
    else:
        print("nothing to do (use --rebuild)")
