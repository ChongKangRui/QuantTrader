"""Run ledger: one CSV row per backtest run, <results-dir>/_ledger.csv.

append(run_dir) is called by the backtest as each run finishes; rebuild() is a
CLI backfill over existing run folders. Both share _row_for_run(), which reads
ONLY the run folder itself (summary.csv TOTAL row, params.json, trades_*.csv)
so live rows and rebuilt rows can never drift apart.
A disabled gate is an empty cell, never a false. Read-only module: no orders.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

LEDGER_NAME = "_ledger.csv"
COMPARISON_NAME = "comparison.json"
BEST_NAME = "BEST.txt"
_BEST_OWNER = "quant.ledger.best.v1"
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


def comparison_settings(base: dict, enabled: bool | None = None,
                        max_drawdown_pct: float | None = None) -> dict:
    """Reporting only: inherit the configured drawdown ceiling, never invent one."""
    raw = base.get("backtest_comparison")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("backtest_comparison must be a mapping")
    enabled = raw.get("enabled", True) if enabled is None else enabled
    if not isinstance(enabled, bool):
        raise ValueError("backtest_comparison.enabled must be true or false")
    if not enabled:
        return {"enabled": False, "max_drawdown_pct": None}
    ceiling = max_drawdown_pct if max_drawdown_pct is not None else raw.get("max_drawdown_pct")
    if ceiling is None:
        bands = (base.get("benchmarks") or {}).get("max_dd_pct") or {}
        ceiling = bands.get("ok", bands.get("good"))
    if ceiling is not None:
        if (isinstance(ceiling, bool) or not isinstance(ceiling, (int, float))
                or not math.isfinite(ceiling) or ceiling <= 0):
            raise ValueError("comparison max_drawdown_pct must be a finite number > 0")
        ceiling = float(ceiling)
    return {"enabled": True, "max_drawdown_pct": ceiling}


def data_identity(frame: pd.DataFrame | pd.Series) -> dict:
    """Small saved fingerprint of the actual loaded prices, not mutable file paths."""
    if isinstance(frame, pd.Series):
        frame = frame.rename("close").rename_axis("time").reset_index()
    digest = hashlib.sha256()
    digest.update(json.dumps([str(c) for c in frame.columns]).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    times = pd.to_datetime(frame["time"], utc=True)
    return {"bars": len(frame), "first": times.iloc[0].isoformat() if len(frame) else None,
            "last": times.iloc[-1].isoformat() if len(frame) else None,
            "sha256": digest.hexdigest()}


def comparison_context(params: dict, results: dict[str, dict]) -> dict:
    """Only strategy/entry/exit and admission knobs may vary within one comparison group."""
    symbols = sorted(job[0] for job in params["jobs"])
    if len(symbols) != len(set(symbols)) or set(symbols) != set(results):
        raise ValueError("comparison requires every requested pair to finish")
    broker, research = params.get("broker_data") or {}, params.get("research_data") or {}
    return {"version": 1, "pandas_version": pd.__version__, "symbols": symbols,
            "inputs": {s: results[s]["comparison_inputs"] for s in symbols},
            "costs": {s: results[s]["comparison_costs"] for s in symbols},
            "account_usd": float((params.get("benchmarks") or {}).get("account_usd") or 0),
            "source": {"broker": broker.get("source_type"),
                       "research": research.get("source_type"),
                       "broker_mode": bool(broker), "research_mode": bool(research)},
            "timeframes": params["timeframes"], "position_checks": params["position_checks"],
            "raw_tape_tf": params.get("raw_tape_tf"),
            "coarse_exit_timing": params.get("coarse_exit_timing"),
            "simulation_timing": params.get("simulation_timing"),
            "evaluation_window": params.get("evaluation_window") or {"enabled": False},
            "equity_cost_timing": params.get("equity_cost_timing"),
            "sizing": {k: params.get(k) for k in (
                "risk_usd", "sizing_scope_usd", "scale_lot_with_balance", "balance_risk_pct",
                "stop_sizing", "default_lot", "lot")},
            "max_drawdown_pct": params["backtest_comparison"]["max_drawdown_pct"]}


def _json_key(value: dict) -> str:
    packed = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _write_json(path: Path, value: dict) -> None:
    import tempfile

    # Publish atomically; never overwrite an unrelated user's temporary file.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                      prefix=f".{path.name}.", suffix=".tmp", delete=False) as fh:
        temporary = Path(fh.name)
        try:
            json.dump(value, fh, indent=2, allow_nan=False)
        except Exception:
            fh.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _comparison_lock(root: Path):
    """One marker publisher at a time, including separate backtest processes."""
    with (root / "_comparison.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _completed_result(run: Path) -> dict | None:
    """Legacy/partial/unverifiable artifacts cannot win by looking deceptively cheap."""
    try:
        params = _read_json(run / "params.json")
        context = params["comparison_context"]
        if (params.get("run_status") != "completed" or params.get("failed")
                or context.get("version") != 1 or not params["backtest_comparison"]["enabled"]):
            return None
        completed = pd.Timestamp(params["completed_at_utc"])
        if completed.tzinfo is None or pd.isna(completed):
            return None
        completed = completed.tz_convert("UTC")
        symbols = context["symbols"]
        if (not symbols or len(symbols) != len(set(symbols))
                or sorted(job[0] for job in params["jobs"]) != sorted(symbols)
                or set(context["inputs"]) != set(symbols) or set(context["costs"]) != set(symbols)):
            return None
        summary = pd.read_csv(run / "summary.csv")
        pairs = summary[summary["symbol"] != "TOTAL"]
        if sorted(pairs["symbol"].tolist()) != sorted(symbols):
            return None
        for _, pair in pairs.iterrows():
            count = float(pair["trades"])
            if not math.isfinite(count) or count < 0 or not count.is_integer():
                return None
            pnl = pd.read_csv(run / f"trades_{pair['symbol']}.csv", usecols=["pnl_usd"])["pnl_usd"]
            if (len(pnl) != count or not all(math.isfinite(float(v)) for v in pnl)
                    or round(float(pnl.sum()), 2) != round(float(pair["net_usd"]), 2)):
                return None
        account = float(context["account_usd"])
        if account <= 0 or not math.isfinite(account):
            return None
        total = summary[summary["symbol"] == "TOTAL"]
        if len(total) == 1:
            row = total.iloc[0]
            traded = sorted(pairs.loc[pairs["trades"] > 0, "symbol"].tolist())
            if traded != sorted(params["comparison_mtm_symbols"]):
                return None
            # Raw MTM precision and full verified coverage prevent false passes at the ceiling.
            dd_usd = float(params["comparison_mtm_drawdown_usd"])
            if round(dd_usd, 2) != round(float(row["max_dd_mtm"]), 2):
                return None
            dd_pct = dd_usd / account * 100
            metrics = {"net_usd": float(row["net_usd"]), "max_dd_pct": dd_pct,
                       "win_rate_pct": float(row["win_rate"]) * 100,
                       "profit_factor": float(row["profit_factor"]), "trades": float(row["trades"])}
        elif total.empty and (pairs["trades"] == 0).all():
            metrics = {"net_usd": 0.0, "max_dd_pct": 0.0, "win_rate_pct": 0.0,
                       "profit_factor": 0.0, "trades": 0.0}
        else:
            return None
        pf = metrics["profit_factor"]
        if (any(not math.isfinite(v) for k, v in metrics.items() if k != "profit_factor")
                or math.isnan(pf) or pf < 0 or metrics["max_dd_pct"] < 0
                or not 0 <= metrics["win_rate_pct"] <= 100
                or metrics["trades"] < 0 or not metrics["trades"].is_integer()
                or metrics["trades"] != float(pairs["trades"].sum())
                or round(metrics["net_usd"], 2) != round(float(pairs["net_usd"].sum()), 2)):
            return None
        ceiling = context.get("max_drawdown_pct")
        if ceiling is not None and (isinstance(ceiling, bool) or not isinstance(ceiling, (int, float))
                                    or not math.isfinite(ceiling) or ceiling <= 0):
            return None
        eligible = (metrics["trades"] > 0 and ceiling is not None
                    and metrics["max_dd_pct"] <= float(ceiling))
        if math.isinf(pf):
            metrics["profit_factor"] = "Infinity"  # Standards-compliant JSON for all-win runs.
        return {"run": run.name, "completed_at_utc": completed.isoformat(),
                "group": _json_key(context), "metrics": metrics, "eligible": eligible,
                "max_drawdown_pct": ceiling}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _best(results: list[dict]) -> dict | None:
    eligible = [r for r in results if r["eligible"]]
    # Profit wins; a profit tie prefers lower drawdown, then the earlier completed run.
    return min(eligible, key=lambda r: (-r["metrics"]["net_usd"], r["metrics"]["max_dd_pct"],
                                       r["completed_at_utc"], r["run"])) if eligible else None


def _delta(current: dict, other: dict | None) -> dict | None:
    if other is None:
        return None
    return {key: round(value - other["metrics"][key], 6)
            if isinstance(value, (int, float)) and isinstance(other["metrics"][key], (int, float))
            else None for key, value in current["metrics"].items()}


def compare_run(run_dir: str | Path) -> dict | None:
    """Compare finished sibling runs and manage only our own same-group BEST.txt markers."""
    run = Path(run_dir).resolve()
    params = _read_json(run / "params.json")
    if not (params.get("backtest_comparison") or {}).get("enabled", False):
        return None
    current = _completed_result(run)
    if current is None:
        result = {"status": "unavailable", "reason": "Run failed, incomplete, or missing verified comparison inputs/MTM metrics."}
        _write_json(run / COMPARISON_NAME, result)
        print(f"comparison: unavailable ({result['reason']})", flush=True)
        return result
    with _comparison_lock(run.parent):
        folders = [p for p in run.parent.iterdir() if p.is_dir() and not p.is_symlink()]
        completed = [r for p in folders for r in [_completed_result(p)] if r is not None]
        comparable = [r for r in completed if r["group"] == current["group"]]
        prior = [r for r in comparable if (r["completed_at_utc"], r["run"]) <
                 (current["completed_at_utc"], current["run"])]
        previous = max(prior, key=lambda r: (r["completed_at_utc"], r["run"])) if prior else None
        previous_best, winner = _best(prior), _best(comparable)
        result = {"status": "compared", "compared_at_utc": datetime.now(timezone.utc).isoformat(),
                  "group": current["group"], "current": current, "previous": previous,
                  "previous_best": previous_best, "best": winner,
                  "is_best": bool(winner and winner["run"] == run.name),
                  "comparable_runs": len(comparable),
                  "excluded_runs": len(folders) - len(comparable),
                  "delta_vs_previous": _delta(current, previous),
                  "delta_vs_previous_best": _delta(current, previous_best)}
        # Publish the new winner first. User-authored BEST.txt files are never overwritten.
        if winner:
            marker = run.parent / winner["run"] / BEST_NAME
            if marker.is_symlink() or (marker.exists() and _read_json(marker).get("owner") != _BEST_OWNER):
                raise FileExistsError(f"refusing to overwrite unmanaged {marker}")
            _write_json(marker, {"owner": _BEST_OWNER, "group": current["group"],
                                 "meaning": "Highest net profit among comparable completed runs within the drawdown ceiling; not a prediction.",
                                 "run": winner["run"], "metrics": winner["metrics"],
                                 "max_drawdown_pct": current["max_drawdown_pct"]})
        for folder in folders:
            if winner and folder.name == winner["run"]:
                continue
            marker = folder / BEST_NAME
            try:
                if marker.is_symlink():
                    continue
                saved = _read_json(marker)
                if saved.get("owner") == _BEST_OWNER and saved.get("group") == current["group"]:
                    marker.unlink()
            except (OSError, ValueError):
                continue
        _write_json(run / COMPARISON_NAME, result)
    for label, other, delta in (("previous", previous, result["delta_vs_previous"]),
                                ("previous best", previous_best, result["delta_vs_previous_best"])):
        if other is None:
            continue
        pf = f"{delta['profit_factor']:+.3f}" if delta["profit_factor"] is not None else "N/A"
        print(f"comparison: vs {label} {other['run']}: net {delta['net_usd']:+.2f} USD; "
              f"MTM drawdown {delta['max_dd_pct']:+.2f} percentage points; "
              f"win rate {delta['win_rate_pct']:+.2f} percentage points; profit factor {pf}", flush=True)
    if previous is None:
        print("comparison: first comparable completed run", flush=True)
    label = winner["run"] if winner else "none qualify"
    print(f"comparison: best = {label}; drawdown ceiling {current['max_drawdown_pct']}%", flush=True)
    return result


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
