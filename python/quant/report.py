"""One self-contained HTML per backtest run: overview charts + trade browser.

plotly.js is embedded exactly once. The overview figures render on load; each
trade's candles are stored as a compact JSON blob and drawn only when the user
clicks the trade row (rendered in a separate popup window), so the browser
never renders the whole trade history at once. The views follow the RUN's own
timeframes (params.json): the execution grid first (the popup default), then
the regime chart (4H baseline / Daily for the H4->D1 variant) with the
regime chart's bias direction shaded (from the run's bias_<SYM>.csv artifact),
plus the raw H1 tape whenever the execution grid is not H1. EMA periods per
view are the run's own (entry EMAs on the execution chart, regime EMAs on the
regime chart), computed on the FULL series of each timeframe and sliced
afterwards, so the overlays do not restart at the window edge.
"""

import argparse
import json
from html import escape
from pathlib import Path

import pandas as pd

from quant.signals import ENTRY_REASON_LABELS

CONTEXT_BEFORE = 120     # H1 bars of context before entry (H1 window, user-requested double)
CONTEXT_AFTER = 40       # H1 bars after exit
WINDOW_CAP = 800         # hard cap on H1 chart length in bars
H4_BEFORE = 60           # H4 bars of context before entry (4H window, same doubling)
H4_AFTER = 20            # H4 bars after exit
H4_CAP = 400             # hard cap on 4H chart length in bars
D1_BEFORE = 120          # D1 bars of context before entry (Daily regime window)
D1_AFTER = 40            # D1 bars after exit
D1_CAP = 400             # hard cap on Daily chart length in bars

# candle-window context per timeframe (before, after, cap)
_TF_VIEW = {"H1": (CONTEXT_BEFORE, CONTEXT_AFTER, WINDOW_CAP),
            "H4": (H4_BEFORE, H4_AFTER, H4_CAP),
            "D1": (D1_BEFORE, D1_AFTER, D1_CAP)}
_TF_HOURS = {"H4": 4, "D1": 24}   # engine resample hours when no broker file


def try_write_report(run_dir: Path | str, data_dir: Path | str = "data") -> bool:
    """Never lets a report problem kill the run that produced it."""
    try:
        return write_report(Path(run_dir), Path(data_dir))
    except ImportError as exc:
        print(f"report skipped: plotly not installed ({exc})", flush=True)
        return False
    except Exception as exc:
        print(f"report skipped: {exc}", flush=True)
        return False


def _round(x) -> float | None:
    # compact JSON sizes; NaN maps to null so JSON.parse never sees bare NaN
    return float(f"{x:.5g}") if x == x else None


def _rounds(a) -> list[float | None]:
    return [_round(v) for v in a]


def _esc(v) -> str:
    if v != v:
        return ""  # NaN cell
    if isinstance(v, float):
        return escape(f"{v:.4g}" if abs(v) < 1e6 else f"{v:.8g}")
    return escape(str(v))


def _summary_table(summary: pd.DataFrame) -> str:
    # readable header names for every column; unknown columns stay as-is
    LABELS = {
        "symbol": "Pair", "trades": "Trades", "net_usd": "Net P/L (USD)",
        "swap_usd": "Swap (USD)",
        "commission_usd": "Commission charged (USD)",
        "net_R": "Net R", "expect_R": "Avg P/L per trade (R)",
        "win_rate": "Win rate (%)", "profit_factor": "Profit factor",
        "max_dd": "Max drawdown (USD)", "max_dd_pct": "Max drawdown (% of account)",
        "max_dd_mtm": "Max MTM drawdown (USD)",
        "max_dd_mtm_pct": "Max MTM drawdown (% of account)",
        "exposure_pct": "Time in market (%)", "per_month": "Trades per month",
        "signals": "Signal bars", "verdict": "Verdict", "dd_band": "Drawdown band",
        "pf_band": "Profit factor band", "expect_band": "Expectancy band",
        "freq_band": "Trades/month band", "year_band": "Worst-year band",
    }
    cols = [c for c in summary.columns]
    head = "".join(f"<th>{escape(LABELS.get(c, c))}</th>" for c in cols)
    body = []
    for _, row in summary.iterrows():
        cls = ' class="tot"' if str(row.get("symbol", "")).upper() == "TOTAL" else ""
        cells = "".join(f"<td>{_esc(row[c])}</td>" for c in cols)
        body.append(f"<tr{cls}>{cells}</tr>")
    return ("<table class=\"summary\"><thead><tr>" + head + "</tr></thead><tbody>"
             + "".join(body) + "</tbody></table>")


def _comparison_html(run_dir: Path) -> str:
    """Render a saved comparison snapshot; rebuilding HTML never changes best markers."""
    try:
        saved = json.loads((run_dir / "comparison.json").read_text(encoding="utf-8"))
        if saved.get("status") != "compared":
            return ('<section id="run-comparison"><h2>Run comparison</h2><p>'
                    + _esc(saved.get("reason", "Comparison unavailable.")) + '</p></section>')
        columns = {"net_usd": "Net P/L (USD)", "max_dd_pct": "Max MTM drawdown (%)",
                   "win_rate_pct": "Win rate (%)", "profit_factor": "Profit factor",
                   "trades": "Trades"}
        header = "<th>Result</th><th>Run folder</th>" + "".join(f"<th>{v}</th>" for v in columns.values())
        rows = []
        for label, key in (("Current", "current"), ("Previous comparable", "previous"),
                            ("Previous best", "previous_best"), ("Best at comparison time", "best")):
            item = saved.get(key)
            if item is None:
                continue
            cells = "".join(f"<td>{_esc(item['metrics'].get(k, 'N/A'))}</td>" for k in columns)
            rows.append(f"<tr><td>{label}</td><td>{_esc(item['run'])}</td>{cells}</tr>")
        for label, key in (("Change vs previous", "delta_vs_previous"),
                            ("Change vs previous best", "delta_vs_previous_best")):
            delta = saved.get(key)
            if delta is not None:
                cells = "".join(f"<td>{_esc(format(delta[k], '+.4g') if delta.get(k) is not None else 'N/A')}</td>"
                                for k in columns)
                rows.append(f"<tr><td>{label}</td><td>—</td>{cells}</tr>")
        badge = "BEST SO FAR at comparison time" if saved.get("is_best") else "Not the best qualifying run"
        ceiling = saved["current"].get("max_drawdown_pct")
        policy = f"{_esc(ceiling)}% of starting balance" if ceiling is not None else "a ceiling that has not been configured"
        return ('<section id="run-comparison"><h2>Run comparison</h2>'
                f'<p><b>{badge}</b>. Highest net profit within a maximum MTM drawdown of '
                f'{policy}. '
                f'{_esc(saved["comparable_runs"])} comparable completed run(s); '
                f'{_esc(saved["excluded_runs"])} other folder(s) excluded.</p>'
                '<table class="summary"><thead><tr>' + header + '</tr></thead><tbody>'
                + "".join(rows) + '</tbody></table>'
                '<p>Percentage changes are percentage points; lower drawdown is better. '
                'No previous row means this is the first comparable run. N/A means no finite delta. '
                'This is a saved snapshot; BEST.txt identifies the current winner in this group. '
                'Best historical results do not prove future performance.</p></section>')
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ""


def _load_trades(run_dir: Path) -> list[tuple[str, pd.DataFrame]]:
    out = []
    for path in sorted(run_dir.glob("trades_*.csv")):
        sym = path.stem.removeprefix("trades_")
        try:
            df = pd.read_csv(path)
            if "symbol" not in df.columns:
                df = df.assign(symbol=sym)
            out.append((sym, df.assign(_id=[f"{sym}-{i}" for i in range(len(df))])))
        except Exception as exc:
            print(f"report: unreadable {path.name}: {exc}", flush=True)
    return out


def _reason_code(value) -> str:
    return value if isinstance(value, str) and value in ENTRY_REASON_LABELS else "unknown"


def annotate_entry_reasons(run_dir: Path, loaded: list) -> list:
    """Old rows stay Unknown unless saved config + exact source verify the signal."""
    from quant.backtest import WIN_BARS, load_h1
    from quant.signals import check_entry

    try:
        params = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        params = {}
    strategy = params.get("strategy") or {}
    modern = ((bool(strategy.get("use_recovery_entry")) or bool(strategy.get("use_w1"))) and
               (any(k in strategy for k in ("w1_touch_from_trend_side", "w1_cross_from_other_side"))
                or bool(strategy.get("w1_cross_into_gap")) or bool(strategy.get("use_recovery_entry"))) and
              all(k in strategy for k in ("entry_ema_fast_period", "entry_ema_slow_period", "entry_atr_period")))
    jobs = {item[0]: item[1] for item in params.get("jobs", [])}
    out = []
    for symbol, original in loaded:
        df = original.copy()
        raw = df["entry_reason"] if "entry_reason" in df else pd.Series("unknown", index=df.index)
        df["entry_reason"] = raw.map(_reason_code)
        df["_entry_reason_source"] = df["entry_reason"].map(
            lambda code: "unknown" if code == "unknown" else "recorded")
        unknown = df.index[df["entry_reason"] == "unknown"]
        if modern and len(unknown):
            try:
                tf = (params.get("timeframes") or {}).get("execution", "H1")
                if params.get("broker_data"):
                    from quant.broker_data import dataset_info, chart_path
                    identity = params["broker_data"]
                    if dataset_info(identity["directory"], tf, identity.get("position_checks")) != identity:
                        raise ValueError("broker source identity changed")
                    path = chart_path(identity["directory"], symbol, tf)
                elif params.get("research_data"):
                    from quant.mkdata import research_info, research_chart_path
                    identity = params["research_data"]
                    if research_info(identity["directory"]) != identity:
                        raise ValueError("research source identity changed")
                    path = research_chart_path(identity["directory"], symbol, tf, jobs[symbol])
                else:
                    raise ValueError("no verifiable saved data identity")
                bars = load_h1(path)
                times = pd.DatetimeIndex(bars["time"])
                for idx in unknown:
                    row = df.loc[idx]
                    fill = times.get_indexer([pd.to_datetime(row["entry_time"], utc=True)])[0]
                    signal = fill - 1
                    if signal < max(WIN_BARS, int(strategy.get("warmup_bars", 300))):
                        continue
                    if "signal_bar_time" in df and pd.notna(row["signal_bar_time"]):
                        if pd.to_datetime(row["signal_bar_time"], utc=True) != times[signal]:
                            continue
                    window = bars.iloc[max(0, signal - WIN_BARS + 1):signal + 1]
                    result = check_entry(window, str(row["direction"]), strategy)
                    # ATR was stored to five decimals; mismatches mean the old path
                    # cannot be verified. Never guess a reason from the fill candle.
                    if not result["signal"] or pd.isna(row.get("atr")) or abs(
                            float(row["atr"]) - float(result["atr"])) > 0.000005 + 1e-12:
                        continue
                    reason = result.get("entry_reason", "unknown")
                    if reason in ("wick_touch", "cross_candle", "pullback_cross", "recovery_break"):
                        df.at[idx, "entry_reason"] = reason
                        df.at[idx, "_entry_reason_source"] = "reconstructed"
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print(f"report: {symbol} historical entry reasons left Unknown ({exc})", flush=True)
        out.append((symbol, df))
    return out


def entry_reason_summary(trades: pd.DataFrame) -> pd.DataFrame:
    """Descriptive, cost-inclusive results of accepted closed trades, not signals."""
    cols = ["symbol", "entry_reason", "entry_label", "trades", "wins", "losses", "scratches",
            "win_rate_pct", "net_usd", "loss_usd", "avg_usd", "avg_R"]
    if trades.empty:
        return pd.DataFrame(columns=cols)
    df = trades.copy()
    df["entry_reason"] = (df["entry_reason"] if "entry_reason" in df else
                           pd.Series("unknown", index=df.index)).map(_reason_code)
    rows = []
    groups = [("TOTAL", df)] + list(df.groupby("symbol", sort=True))
    for symbol, group in groups:
        for reason, label in ENTRY_REASON_LABELS.items():
            subset = group[group["entry_reason"] == reason]
            if subset.empty:
                continue
            pnl = subset["pnl_usd"].astype(float)
            wins, losses = int((pnl > 0).sum()), int((pnl < 0).sum())
            rows.append({"symbol": symbol, "entry_reason": reason, "entry_label": label,
                "trades": len(subset), "wins": wins, "losses": losses,
                "scratches": int((pnl == 0).sum()), "win_rate_pct": round(wins / len(subset) * 100, 2),
                "net_usd": round(float(pnl.sum()), 2), "loss_usd": round(float(pnl[pnl < 0].sum()), 2),
                "avg_usd": round(float(pnl.mean()), 4), "avg_R": round(float(subset["pnl_R"].mean()), 4)})
    return pd.DataFrame(rows, columns=cols)


def _entry_summary_html(summary: pd.DataFrame) -> str:
    total = summary[summary["symbol"] == "TOTAL"]
    columns = {"entry_label": "Entry reason", "trades": "Trades", "wins": "Wins",
               "losses": "Losses", "win_rate_pct": "Win rate (%)", "net_usd": "Net P/L (USD)",
               "avg_usd": "Avg P/L (USD)", "avg_R": "Avg P/L (R)"}
    header = "".join(f"<th>{label}</th>" for label in columns.values())
    body = "".join("<tr>" + "".join(f"<td>{_esc(row[key])}</td>" for key in columns) + "</tr>"
                   for _, row in total.iterrows())
    return ('<section id="entry-summary"><h2>Results by entry reason — all pairs</h2>'
            '<p>Closed trades after costs and portfolio limits. Compare averages and trade counts, '
            'not total losses alone. Scratch trades count in the win-rate denominator. '
            'Small samples are not proof that one pattern is better.</p>'
            f'<table><tr>{header}</tr>{body}</table>'
            '<p>Reasons use the signal candle, not the entry candle. Historical reasons are '
            'reconstructed only from verified saved config/data; otherwise Unknown. '
            'Per-pair details: <code>entry_summary.csv</code>.</p></section>')


def _equity_spec(all_trades: pd.DataFrame, run_dir: Path | None = None) -> dict | None:
    """Portfolio equity from exit-ordered trade PnL (R + USD) and drawdown in R."""
    if all_trades.empty:
        return None
    t = all_trades.sort_values("exit_time").reset_index(drop=True)
    eqr = t["pnl_R"].cumsum()
    dd = eqr - eqr.cummax()
    x = [str(s) for s in t["exit_time"]]
    data = [
        {"x": x, "y": _rounds(eqr), "name": "cum R", "type": "scatter",
         "line": {"width": 2}},
        {"x": x, "y": _rounds(t["pnl_usd"].cumsum()), "name": "cum USD",
         "type": "scatter", "line": {"width": 1}, "yaxis": "y2"},
        {"x": x, "y": _rounds(dd), "name": "drawdown R", "type": "scatter",
         "line": {"width": 1, "dash": "dot"}},
    ]
    if run_dir is not None and (run_dir / "equity_curve.csv").exists():
        # mark-to-market account curve: open positions marked at each pair's close
        curve = pd.read_csv(run_dir / "equity_curve.csv")
        if {"time", "usd"}.issubset(curve.columns):
            data.append({"x": [str(s) for s in curve["time"]],
                         "y": _rounds(curve["usd"]), "name": "MTM USD",
                         "type": "scatter", "line": {"width": 1, "color": "#f90"},
                         "yaxis": "y2", "opacity": 0.8})
    layout = {"title": "equity (all pairs, exit order; MTM = hourly marks)",
              "legend": {"x": 0},
              "yaxis": {"title": "R"},
              "yaxis2": {"title": "USD", "overlaying": "y", "side": "right",
                         "showgrid": False}}
    return {"data": data, "layout": layout}


def _yearly_spec(run_dir: Path) -> dict | None:
    path = run_dir / "yearly.csv"
    if not path.exists():
        return None
    y = pd.read_csv(path)
    if not {"year", "net_R"}.issubset(y.columns):
        return None
    g = y.groupby("year")["net_R"].sum()
    return {"data": [{"x": [int(i) for i in g.index], "y": _rounds(g),
                      "type": "bar", "name": "net R"}],
            "layout": {"title": "net R per year (all pairs)"}}


def _num(row, key: str) -> float | None:
    # older run folders lack risk_usd/tp_usd: render as null, not an error
    v = row.get(key)
    return None if v is None or v != v else _round(v)


def _run_config(run_dir: Path) -> dict:
    """What the ENGINE ran with: timeframes + EMA periods per chart, from the
    run's params.json. Old folders (no timeframes key, ema_fast/ema_slow key
    names) and folderless runs fall back to the H1->H4/B1 defaults. The report
    must show what the engine actually used."""
    cfg = {"exec": "H1", "reg": "H4",
           "entry": {"fast": 20, "slow": 50},
           "regime": {"fast": 20, "slow": 50}}
    path = Path(run_dir) / "params.json"
    if path.exists():
        try:
            pp = json.loads(path.read_text(encoding="utf-8"))
            cfg["research_data"] = pp.get("research_data")
            cfg["broker_data"] = pp.get("broker_data")
            cfg["data_dir"] = pp.get("data_dir")
            tf = pp.get("timeframes") or {}
            cfg["exec"] = str(tf.get("execution") or "H1").upper()
            cfg["reg"] = str(tf.get("regime") or "H4").upper()
            st = pp.get("strategy") or {}
            cfg["entry"]["fast"] = int(st.get(
                "entry_ema_fast_period", st.get("h1_ema_fast", st.get("ema_fast"))) or 20)
            cfg["entry"]["slow"] = int(st.get(
                "entry_ema_slow_period", st.get("h1_ema_slow", st.get("ema_slow"))) or 50)
            cfg["regime"]["fast"] = int(st.get("bias_ema_fast_period", st.get("h4_ema_fast")) or 20)
            cfg["regime"]["slow"] = int(st.get("bias_ema_slow_period", st.get("h4_ema_slow")) or 50)
        except Exception:
            pass  # broken params: keep chart defaults rather than fail the report
    return cfg


def _tf_label(tf: str, is_regime: bool) -> str:
    # human view label: the regime Daily chart reads "Daily", others "H1"/"H4"
    return "Daily" if (is_regime and str(tf).upper() == "D1") else str(tf).upper()


def _tf_bars(data_dir: Path, sym: str, tf: str, h1: pd.DataFrame) -> pd.DataFrame | None:
    """Bars for one timeframe: the broker file FIRST (data contract), else the
    engine's own resample — the same grid the backtest traded on."""
    tf = str(tf).upper()
    if tf == "H1":
        return h1
    hours = _TF_HOURS.get(tf)
    if hours is None:
        return None
    from quant.backtest import build_htf, load_h1

    path = data_dir / f"{sym}_{tf}.csv"
    if path.exists():
        try:
            return load_h1(path)
        except Exception as exc:
            print(f"report: {sym} {tf} file unreadable — resampling ({exc})",
                  flush=True)
    try:
        return build_htf(h1, hours)
    except Exception as exc:
        print(f"report: {sym} {tf}: resample failed ({exc})", flush=True)
        return None


def _bias_spans(run_dir: Path, sym: str, pad_hours: int = 0) -> list[dict]:
    """The regime chart's per-bar direction (run artifact bias_<SYM>.csv)
    merged into consecutive spans {t0, t1, d}; t1 padded to the bar close."""
    path = run_dir / f"bias_{sym}.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        print(f"report: {sym} bias artifact unreadable ({exc})", flush=True)
        return []
    if not {"time", "direction"}.issubset(df.columns):
        return []
    spans: list[dict] = []
    prev = start = end = None
    for t, d in zip(df["time"], df["direction"]):
        ts = str(t)[:16]
        if d != prev:
            if prev is not None:
                spans.append({"t0": start,
                              "t1": str(pd.Timestamp(end) + pd.Timedelta(hours=pad_hours))[:16],
                              "d": prev})
            start = ts
            prev = d
        end = ts
    if prev is not None:
        spans.append({"t0": start,
                      "t1": str(pd.Timestamp(end) + pd.Timedelta(hours=pad_hours))[:16],
                      "d": prev})
    return spans


def _bar_arrays(df: pd.DataFrame, e_fast_n: int, e_slow_n: int,
                with_ema: bool = True) -> dict:
    """Loose arrays per timeframe for fast window slicing."""
    from quant.backtest import _ema

    # EMA over the FULL series first, sliced per window afterwards (why: overlay
    # continuity); periods are the run's own (entry EMAs on the execution chart,
    # regime EMAs on the regime chart). with_ema=False for views the engine has
    # no EMA on (the raw H1 tape) — the JS then skips the overlay.
    return {
        "ts": pd.to_datetime(df["time"]),
        "time": [str(s)[:16] for s in df["time"]],
        "efast": _ema(df["close"], e_fast_n).to_numpy(dtype=float) if with_ema else None,
        "eslow": _ema(df["close"], e_slow_n).to_numpy(dtype=float) if with_ema else None,
        "o": df["open"].to_numpy(dtype=float),
        "h": df["high"].to_numpy(dtype=float),
        "l": df["low"].to_numpy(dtype=float),
        "c": df["close"].to_numpy(dtype=float),
    }


def _slice_window(bars: dict, entry_time, exit_time,
                   before: int, after: int, cap: int) -> dict | None:
    """One candle window around entry/exit; None when entry is outside the frame."""
    ts = bars["ts"]
    n = len(ts)
    try:
        i_in = int(ts.searchsorted(pd.Timestamp(entry_time), side="right") - 1)
        i_out = int(ts.searchsorted(pd.Timestamp(exit_time), side="right") - 1)
    except Exception:
        return None
    if i_in < 0 or i_in >= n:
        return None
    i0 = max(0, i_in - before)
    i1 = min(n - 1, max(i_out, i_in) + after, i0 + cap - 1)
    return {
        "t": bars["time"][i0:i1 + 1],
        "o": _rounds(bars["o"][i0:i1 + 1]),
        "h": _rounds(bars["h"][i0:i1 + 1]),
        "l": _rounds(bars["l"][i0:i1 + 1]),
        "c": _rounds(bars["c"][i0:i1 + 1]),
        "efast": _rounds(bars["efast"][i0:i1 + 1]) if bars["efast"] is not None else None,
        "eslow": _rounds(bars["eslow"][i0:i1 + 1]) if bars["eslow"] is not None else None,
    }


def _contexts(sym: str, charts: dict, trades: pd.DataFrame,
              spans: list[dict]) -> list[dict]:
    """One embedded record per trade: candles for EACH chart of this run's
    combo (charts maps view key -> (timeframe, bars); insertion order keeps
    exec first), plus the regime chart's bias spans clipped to the window.
    An entry outside the EXECUTION frame skips the trade, as before."""
    out = []
    for _, tr in trades.iterrows():
        rec = {
            "id": str(tr["_id"]), "sym": sym, "side": str(tr["direction"]),
            "entryTime": str(tr["entry_time"])[:16], "exitTime": str(tr["exit_time"])[:16],
            "entry": _round(tr["entry"]), "exit": _round(tr["exit"]),
            "sl": _round(tr["sl"]), "tp": _round(tr["tp"]),
            "pnlR": _round(tr["pnl_R"]), "exitType": str(tr["exit_type"]),
            "bars": int(tr["bars_held"]),
            "pnlUsd": _round(tr["pnl_usd"]),
            "riskUsd": _num(tr, "risk_usd"), "tpUsd": _num(tr, "tp_usd"),
        }
        embedded = True
        for key, (tf, bars) in charts.items():
            before, after, cap = _TF_VIEW[tf]
            w = _slice_window(bars, tr["entry_time"], tr["exit_time"],
                              before, after, cap)
            if key == "exec" and w is None:
                embedded = False
                break
            if w is None:
                rec[key] = None
                continue
            if key == "reg" and spans:
                lo, hi = w["t"][0], w["t"][-1]
                rec["spans"] = [{"t0": max(s["t0"], lo), "t1": min(s["t1"], hi),
                                 "d": s["d"]}
                                for s in spans if s["t1"] >= lo and s["t0"] <= hi]
            rec[key] = w
        if embedded:
            out.append(rec)
    return out


def _bundle(run_dir: Path, data_dir: Path, trades: list[tuple[str, pd.DataFrame]]
            ) -> tuple[list[dict], dict]:
    """Per-view windows + the run's own config (timeframes, EMA periods)."""
    from quant.backtest import load_h1  # generic bars loader (columns/UTC/ascending)

    cfg = _run_config(run_dir)
    if data_dir == Path("data") and cfg.get("data_dir"):
        data_dir = Path(cfg["data_dir"])
    # the view set follows THIS run's timeframes: execution chart + regime
    # chart, and the raw H1 tape whenever the execution grid is not H1
    view_tfs = {"exec": cfg["exec"], "reg": cfg["reg"]}
    if cfg["exec"] != "H1" and not cfg.get("broker_data"):
        view_tfs["raw"] = "H1"
    bundle: list[dict] = []
    for sym, df in trades:
        if cfg.get("broker_data"):
            from quant.broker_data import chart_path
            data_dir = Path(cfg["broker_data"]["directory"])
        h1_path = data_dir / f"{sym}_{cfg['exec'] if cfg.get('broker_data') else 'H1'}.csv"
        if not h1_path.exists():
            continue
        try:
            h1 = load_h1(h1_path)
        except Exception as exc:
            print(f"report: {sym} H1 unreadable ({exc})", flush=True)
            continue
        try:
            charts: dict[str, tuple[str, dict]] = {}
            for key, tf in view_tfs.items():
                if cfg.get("broker_data"):
                    from quant.broker_data import chart_path, dataset_info
                    root = cfg["broker_data"]["directory"]
                    if dataset_info(root, cfg["exec"], cfg["broker_data"].get("position_checks")) != cfg["broker_data"]:
                        raise ValueError("broker dataset changed; refusing substitute charts")
                    bars = load_h1(chart_path(root, sym, tf))
                elif cfg.get("research_data"):
                    from quant.mkdata import research_info, research_chart_path
                    root = cfg["research_data"]["directory"]
                    if research_info(root) != cfg["research_data"]:
                        raise ValueError("research manifest changed since this run; refusing substitute charts")
                    bars = load_h1(research_chart_path(root, sym, tf, h1_path))
                else:
                    bars = _tf_bars(data_dir, sym, tf, h1)
                if bars is None:
                    if key == "exec":
                        raise ValueError(f"no candles on the {tf} execution grid")
                    print(f"report: {sym} {tf} unavailable — {key} view off",
                          flush=True)
                    continue
                per = cfg["entry"] if tf == cfg["exec"] else cfg["regime"]
                with_ema = key != "raw"  # the raw tape: the engine has no EMA there
                charts[key] = (tf, _bar_arrays(bars, per["fast"], per["slow"],
                                               with_ema=with_ema))
            spans = _bias_spans(run_dir, sym, pad_hours=_TF_HOURS.get(cfg["reg"], 0))
            bundle.extend(_contexts(sym, charts, df, spans))
        except Exception as exc:
            print(f"report: {sym} windows failed ({exc})", flush=True)
    return bundle, cfg


def write_report(run_dir: Path, data_dir: Path) -> bool:
    s_path = run_dir / "summary.csv"
    if not s_path.exists():
        print(f"report: no {s_path}", flush=True)
        return False
    from plotly.offline import get_plotlyjs

    summary = pd.read_csv(s_path)
    from quant.performance import PerformanceSettings, account_performance, performance_html

    params_path = run_dir / "params.json"
    params = json.loads(params_path.read_text(encoding="utf-8")) if params_path.exists() else {}
    performance_settings = PerformanceSettings.from_dict(params.get("performance"))
    ratios_html = ""
    if performance_settings.enabled:
        curve_path = run_dir / "equity_curve.csv"
        valid = (params.get("equity_cost_timing") == "accrued"
                 and params.get("performance_equity_complete") is True and curve_path.exists())
        curve = pd.read_csv(curve_path) if valid else pd.DataFrame()
        performance = account_performance(curve, performance_settings)
        if not valid:
            performance["reason"] = "Complete cost-timed equity unavailable (legacy or incomplete run)"
        (run_dir / "performance.json").write_text(
            json.dumps(performance, indent=1, allow_nan=False), encoding="utf-8")
        ratios_html = performance_html(performance,
            "TOTAL portfolio only. Configured spread/slippage are in fills; entry commission and "
            "overnight swap accrue while positions are open; closing costs apply on exit. "
            "Open positions use the available bar-close price marks, not tick-by-tick equity.")
    loaded = annotate_entry_reasons(run_dir, _load_trades(run_dir))
    all_trades = (pd.concat([df for _, df in loaded], ignore_index=True)
                   if loaded else pd.DataFrame())
    entry_summary = entry_reason_summary(all_trades)
    entry_summary.to_csv(run_dir / "entry_summary.csv", index=False)

    bundle, cfg = _bundle(Path(run_dir), Path(data_dir), loaded) if loaded \
        else ([], _run_config(Path(run_dir)))
    embedded = {c["id"]: c for c in bundle}
    embedded_ids = set(embedded)
    meta = [{"id": r["_id"], "sym": r["symbol"], "side": r["direction"],
              "entry": str(r["entry_time"])[:16], "pnlR": _round(r["pnl_R"]),
              "entryMalaysia": pd.to_datetime(r["entry_time"], utc=True).tz_convert(
                  "UTC+08:00").strftime("%Y-%m-%d %H:%M"),
              "lot": _num(r, "lot"),
              "entryReason": r["entry_reason"],
              "entryReasonLabel": ENTRY_REASON_LABELS[r["entry_reason"]],
              "entryReasonSource": r["_entry_reason_source"],
             "pnlUsd": _round(r["pnl_usd"]),
             "exitType": str(r["exit_type"]), "bars": int(r["bars_held"]),
             "swap": _num(r, "swap"),  # null when the run predates the swap column
             "riskUsd": _num(r, "risk_usd"), "tpUsd": _num(r, "tp_usd"),
             "missing": r["_id"] not in embedded_ids}
            for _, r in all_trades.iterrows()]

    verdict_cell = ""
    if cfg.get("broker_data"):
        text = cfg["broker_data"]["warning"] + " " + " ".join(cfg["broker_data"].get("coverage_warnings", []))
        verdict_cell = f'<div id="broker-data-warning">{_esc(text)}</div>'
    if cfg.get("research_data"):
        from quant.mkdata import RESEARCH_WARNING
        verdict_cell = f'<div id="research-warning">{_esc(RESEARCH_WARNING)}</div>'
    if "verdict" in summary.columns and len(summary):
        tot = summary[summary["symbol"] == "TOTAL"]
        if len(tot):
            verdict_cell += (f'<div id="verdict">TOTAL verdict: '
                            f"<b>{_esc(tot['verdict'].iloc[0])}</b></div>")

    figs = {"equity": _equity_spec(all_trades, run_dir), "yearly": _yearly_spec(run_dir)}
    if cfg.get("broker_data") and figs["equity"]:
        figs["equity"]["layout"]["title"] = f"equity (all pairs, exit order; MTM = {cfg['exec']}-close marks)"
    no_nan = lambda d: json.dumps(d, separators=(",", ":")).replace("</", "<\\/")
    html = _html(run_dir.name, get_plotlyjs(), _summary_table(summary) + ratios_html, verdict_cell,
                 no_nan(figs),
                 no_nan({"embedded": embedded, "meta": meta,
                         "tf": {"exec": _tf_label(cfg["exec"], False),
                                "reg": _tf_label(cfg["reg"], True)},
                          "emaExec": cfg["entry"], "emaRegime": cfg["regime"]}),
                  coarse_marks=bool(cfg.get("broker_data")),
                  mark_tf=cfg["exec"],
                  entry_summary_html=_entry_summary_html(entry_summary),
                  exposure_note=("Time in market = held seconds / observed execution-candle seconds; "
                                 "gaps excluded, short sessions clipped." if params.get("exposure_timing") ==
                                 "observed_execution_seconds" else "Time in market is a legacy bar-count estimate."),
                  comparison_html=_comparison_html(run_dir))
    out = run_dir / "report.html"
    out.write_text(html, encoding="utf-8")
    print(f"report -> {out}", flush=True)
    return True


_APP_JS = """
const FIGS = JSON.parse(document.getElementById('figs-json').textContent);
const TB = JSON.parse(document.getElementById('trades-json').textContent);
const cfg = {displayModeBar: false};
if (FIGS.equity) Plotly.newPlot('fig-equity', FIGS.equity.data, FIGS.equity.layout, cfg);
if (FIGS.yearly) Plotly.newPlot('fig-yearly', FIGS.yearly.data, FIGS.yearly.layout, cfg);
const pairSel = document.getElementById('pair');
const rowsEl = document.getElementById('rows');
const filterSel = document.getElementById('filter');
const exitSel = document.getElementById('exitFilter');
const reasonSel = document.getElementById('reasonFilter');
const msgEl = document.getElementById('msg');
const countEl = document.getElementById('count');
const syms = Array.from(new Set(TB.meta.map(function (r) { return r.sym; }))).sort();
pairSel.innerHTML = syms.map(function (s) { return '<option>' + s + '</option>'; }).join('');
const exitTypes = Array.from(new Set(TB.meta.map(function (r) { return r.exitType; }))).sort();
exitSel.innerHTML = '<option value="all">All exits</option>' +
  exitTypes.map(function (t) { return '<option>' + t + '</option>'; }).join('');
const reasonCodes = Array.from(new Set(TB.meta.map(function (r) { return r.entryReason; }))).sort();
reasonSel.innerHTML = '<option value="all">All entry reasons</option>' +
  reasonCodes.map(function (code) {
    var label = TB.meta.find(function (r) { return r.entryReason === code; }).entryReasonLabel;
    return '<option value="' + code + '">' + label + '</option>';
  }).join('');
function usd(v) { return v == null ? '-' : '$' + v; }
function listTrades() {
  var p = pairSel.value, f = filterSel.value, e = exitSel.value, reason = reasonSel.value;
  return TB.meta.filter(function (r) {
    if (r.sym !== p) return false;
    if (e !== 'all' && r.exitType !== e) return false;
    if (reason !== 'all' && r.entryReason !== reason) return false;
    return f === 'all' || (f === 'losses' ? r.pnlR < 0 : r.pnlR > 0);
  });
}
function drawList() {
  var rows = listTrades();
  countEl.textContent = rows.length + ' trades (' +
    rows.filter(function (r) { return r.pnlR < 0; }).length + ' losses)';
  // totals row = sums over the FILTERED selection (pair + loss/exit filters),
  // styled like the summary table's TOTAL row; swap shows '-' when the run
  // predates the swap column
  var sum = function (get) {
    return rows.reduce(function (a, r) { return a + (get(r) || 0); }, 0);
  };
  var rnd = function (v) { return Math.round(v * 100) / 100; };
  var hasSwap = rows.some(function (r) { return r.swap != null; });
  rowsEl.innerHTML = '<tr><th>Entry time (UTC)</th><th>Entry time (Malaysia UTC+8)</th><th>Side</th><th>Lots</th><th>Entry reason</th><th>P/L (USD)</th>' +
    '<th>P/L (R)</th><th>Exit type</th><th>Held (' + TB.tf.exec + ' bars)</th>' +
    '<th>1R (USD)</th><th>TP amount (USD)</th><th>Swap (USD)</th></tr>' +
    '<tr class="tot"><td>TOTAL ' + rows.length + '</td><td></td><td></td><td></td><td></td>' +
    '<td>' + usd(rnd(sum(function (r) { return r.pnlUsd; }))) + '</td>' +
    '<td>' + rnd(sum(function (r) { return r.pnlR; })) + '</td>' +
    '<td></td><td></td><td></td><td></td>' +
    '<td>' + (hasSwap ? usd(rnd(sum(function (r) { return r.swap; }))) : '-') +
    '</td></tr>' +
    rows.map(function (r) {
      var col = r.pnlR < 0 ? '#f66' : '#6c6';
      return '<tr data-id="' + r.id + '"' + (r.missing ? ' class="nochart"' : '') +
        '><td>' + r.entry + '</td><td>' + r.entryMalaysia + '</td><td>' + r.side +
        '</td><td>' + (r.lot == null ? '-' : r.lot) +
        '</td><td title="' + (r.entryReasonSource === 'reconstructed' ?
        'Reconstructed from verified saved signal candle' :
        (r.entryReasonSource === 'recorded' ? 'Recorded at candidate generation' : 'Not recorded or not verified')) +
        '">' + r.entryReasonLabel +
        '</td><td style="color:' + col + '">' + usd(r.pnlUsd) +
        '</td><td style="color:' + col + '">' + r.pnlR + '</td><td>' + r.exitType +
        '</td><td>' + r.bars + '</td><td>' + usd(r.riskUsd) +
        '</td><td>' + usd(r.tpUsd) + '</td><td>' +
        (r.swap == null ? '-' : usd(r.swap)) + '</td></tr>';
    }).join('');
  syncChartSelection(rows);
}
pairSel.onchange = drawList;
filterSel.onchange = drawList;
exitSel.onchange = drawList;
reasonSel.onchange = drawList;
rowsEl.onclick = function (e) {
  var tr = e.target.closest('tr');
  if (tr && tr.dataset.id) openChart(tr.dataset.id);
};
var curTf = 'exec';  // sticks across trades while browsing (execution view first)
var chartWin = null;
var POP_CSS = "body{font:13px system-ui,sans-serif;margin:6px;background:#111;color:#ddd}" +
  "button{background:#222;color:#ddd;border:1px solid #555;padding:3px 14px;cursor:pointer}" +
  "button:disabled{opacity:0.4;cursor:default}" +
  "#tradenav{display:flex;align-items:center;gap:8px;margin-bottom:8px}" +
  "#tradedetail{margin-bottom:8px;color:#aaa}" +
  "#tfbtns button.on{background:#4a6cf7;border-color:#4a6cf7}" +
  "#tfnote{color:#888;margin-left:8px}";
function chartNavigation(w, rows) {
  var index = rows.findIndex(function (r) { return r.id === w.__tid; });
  w.document.getElementById('tradecount').textContent =
    'Trade ' + (index < 0 ? 0 : index + 1) + ' of ' + rows.length;
  w.document.getElementById('prevtrade').disabled = index <= 0;
  w.document.getElementById('nexttrade').disabled = index < 0 || index >= rows.length - 1;
}
function clearChart(w, message) {
  var plot = w.document.getElementById('pop-chart');
  w.Plotly.purge(plot);
  plot.textContent = message;
  w.document.getElementById('tfbtns').innerHTML = '';
}
function syncChartSelection(rows) {
  if (!chartWin || chartWin.closed) return;
  if (!rows.some(function (r) { return r.id === chartWin.__tid; })) {
    if (rows.length) { openChart(rows[0].id); return; }
    chartWin.__tid = null;
    chartWin.document.getElementById('tradedetail').textContent = '';
    clearChart(chartWin, 'No trades match the current report filters.');
  }
  chartNavigation(chartWin, rows);
}
function navigateTrade(step) {
  if (!chartWin || chartWin.closed) return;
  var rows = listTrades();
  var index = rows.findIndex(function (r) { return r.id === chartWin.__tid; });
  var next = index + step;
  if (index >= 0 && next >= 0 && next < rows.length) openChart(rows[next].id);
}
function chartWindow() {
  var w = chartWin && !chartWin.closed ? chartWin :
    window.open('', 'tradechart', 'width=1080,height=720');
  if (!w) { msgEl.textContent = 'popup blocked — allow popups for this file'; return null; }
  msgEl.textContent = '';
  if (!w.__init) {
    // the popup gets its OWN plotly (copied once from the embedded lib):
    // drawing into a foreign document from the opener mis-applies layout
    // (axis ranges, shapes) — that is what made stop/target lines vanish
    var lib = document.getElementById('plotly-lib').textContent;
    w.document.open();
    w.document.write('<!doctype html><html><head><title>Trade chart</title><style>' + POP_CSS +
      '</style><scr' + 'ipt>' + lib + '</scr' + 'ipt></head><body>' +
      '<div id="tradenav"><button id="prevtrade" type="button">&#8592; Previous trade</button>' +
      '<span id="tradecount" aria-live="polite"></span>' +
      '<button id="nexttrade" type="button">Next trade &#8594;</button></div>' +
      '<div id="tradedetail"></div><div id="tfbtns"></div>' +
      '<div id="pop-chart" style="margin-top:6px"></div></body></html>');
    w.document.close();
    w.document.getElementById('tfbtns').onclick = function (e) {
      var b = e.target.closest('button');
      // chartWin always holds the live popup; __tid is that window's trade
      if (b && chartWin && chartWin.__tid) openChart(chartWin.__tid, b.getAttribute('data-tf'));
    };
    w.document.getElementById('prevtrade').onclick = function () { navigateTrade(-1); };
    w.document.getElementById('nexttrade').onclick = function () { navigateTrade(1); };
    w.document.addEventListener('keydown', function (e) {
      if (e.defaultPrevented || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
      var target = e.target;
      if (target && (target.isContentEditable || (target.closest &&
          target.closest('input, textarea, select, [contenteditable="true"]')))) return;
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      navigateTrade(e.key === 'ArrowLeft' ? -1 : 1);
    });
    w.__init = true;
  }
  chartWin = w;
  return w;
}
function openChart(id, forceTf) {
  var row = TB.meta.find(function (r) { return r.id === id; });
  if (!row) return;
  var ctx = TB.embedded[id];
  if (forceTf) curTf = forceTf;
  if (ctx && !ctx[curTf]) curTf = 'exec';
  var w = chartWindow();
  if (!w) return;
  w.__tid = id;
  chartNavigation(w, listTrades());
  w.document.getElementById('tradedetail').textContent =
    row.sym + ' ' + row.side + ' | Entry: ' + row.entry + ' UTC | ' +
    row.entryReasonLabel + ' | ' + usd(row.pnlUsd) + ' (' + row.pnlR + 'R)';
  w.document.title = row.sym + ' ' + row.side + ' - Trade chart';
  if (!ctx) {
    clearChart(w, 'Chart not embedded (no quote data for this trade). Use Previous/Next to continue.');
    return;
  }
  w.document.getElementById('pop-chart').textContent = '';
  function btn(key, label) {
    return ctx[key] ? ('<button data-tf="' + key + '"' +
      (curTf === key ? ' class="on"' : '') + '>' + label + '</button>') : '';
  }
  w.document.getElementById('tfbtns').innerHTML =
    btn('exec', TB.tf.exec) + btn('reg', TB.tf.reg) + btn('raw', 'H1') +
    (ctx.reg ? '' : '<span id="tfnote">no ' + TB.tf.reg + ' data for this run</span>') +
    (ctx.spans && curTf === 'reg' ?
      '<span id="tfnote">shading: LONG green / SHORT red / NEUTRAL grey</span>' : '');
  drawChart(w, ctx);
}
function drawChart(w, ctx) {
  var d = ctx[curTf] || ctx.exec;
  var tfName = TB.tf[curTf] || TB.tf.exec;
  // pin the y zoom to candles + levels: shapes are NOT auto-included by Plotly,
  // so a stop/target away from the candle span would otherwise be cut off
  var yMin = null, yMax = null;
  function grow(v) {
    if (v == null) return;
    if (yMin == null || v < yMin) yMin = v;
    if (yMax == null || v > yMax) yMax = v;
  }
  for (var i = 0; i < d.l.length; i++) { grow(d.l[i]); grow(d.h[i]); }
  [ctx.entry, ctx.exit, ctx.sl, ctx.tp].forEach(grow);
  var yrange = null;
  if (yMin != null) {
    var pad = (yMax - yMin) * 0.15;
    yrange = [yMin - pad, yMax + pad];
  }
  function level(y, color) {
    // runs older than the sl/tp columns: no object instead of a broken shape
    if (y == null) return null;
    return {type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y',
            y0: y, y1: y, line: {color: color, width: 1, dash: 'dot'}};
  }
  function money(y, text, color) {
    // dashed line labelled with its USD value (skip when the run predates the column)
    return (y == null) ? null : {
      x: d.t[0], y: y, xref: 'x', yref: 'y', text: text, showarrow: false,
      xanchor: 'left', yanchor: 'bottom', font: {color: color, size: 10}};
  }
  var per = (TB[curTf === 'reg' ? 'emaRegime' : 'emaExec'] || {});
  var traces = [
    {type: 'candlestick', x: d.t, open: d.o, high: d.h, low: d.l, close: d.c,
     name: tfName, increasing_line_color: '#3ddc84', decreasing_line_color: '#ff5f5f'},
    // entry marker must be unmistakable on dark candles: yellow, not green
    {x: [ctx.entryTime], y: [ctx.entry], type: 'scatter', mode: 'markers', name: 'entry',
     marker: {size: 13, symbol: 'triangle-up', color: '#ffd400'}},
    {x: [ctx.exitTime], y: [ctx.exit], type: 'scatter', mode: 'markers', name: 'exit',
     marker: {size: 11, symbol: 'triangle-down', color: '#f66'}}
  ];
  // the engine's own EMA overlays (regime EMAs on the regime chart, entry EMAs
  // on the execution chart); the raw H1 tape carries none (raw: efast = null)
  if (d.efast) {
    traces.splice(1, 0,
      {x: d.t, y: d.efast, type: 'scatter', mode: 'lines',
       name: 'EMA' + per.fast, line: {width: 1.2}},
      {x: d.t, y: d.eslow, type: 'scatter', mode: 'lines',
       name: 'EMA' + per.slow, line: {width: 1.2}});
  }
  // regime-chart bias shading first (layer below), then the trade highlight;
  // shading belongs to the regime chart only (spans are regime-grid stamps)
  var spans = (curTf === 'reg' && ctx.spans) ? ctx.spans : [];
  var shade = {LONG: 'rgba(46,204,113,0.10)', SHORT: 'rgba(231,76,60,0.10)',
               NEUTRAL: 'rgba(150,150,150,0.07)'};
  var shapes = spans.map(function (s) {
    return {type: 'rect', xref: 'x', yref: 'paper', x0: s.t0, x1: s.t1,
            y0: 0, y1: 1, line: {width: 0},
            fillcolor: shade[s.d] || shade.NEUTRAL, layer: 'below'};
  });
  shapes.push({type: 'rect', xref: 'x', yref: 'paper',
               x0: ctx.entryTime, x1: ctx.exitTime, y0: 0, y1: 1,
               line: {width: 0}, fillcolor: 'rgba(120,150,255,0.08)'});
  var s1 = level(ctx.sl, '#d33');
  var s2 = level(ctx.tp, '#3a3');
  if (s1) shapes.push(s1);
  if (s2) shapes.push(s2);
  w.Plotly.newPlot(w.document.getElementById('pop-chart'), traces, {
    width: 1040, height: 620,
    paper_bgcolor: '#111', plot_bgcolor: '#111', font: {color: '#ddd'},
    title: ctx.sym + ' ' + ctx.side + ' ' + usd(ctx.pnlUsd) +
           ' (' + ctx.pnlR + 'R, ' + ctx.exitType + ', ' + tfName + ')',
    xaxis: {rangeslider: {visible: false}},
    yaxis: (yrange ? {range: yrange} : {}),
    shapes: shapes,
    annotations: [
      money(ctx.sl, 'stop: -' + usd(Math.abs(ctx.riskUsd)), '#d33'),
      money(ctx.tp, 'target: +' + usd(ctx.tpUsd), '#3a3')
    ].filter(Boolean),
    legend: {x: 0}
  }, cfg);
}
drawList();
"""

_CSS = """
body { font: 13px system-ui, sans-serif; margin: 16px; background: #111; color: #ddd; }
table { border-collapse: collapse; }
td, th { border: 1px solid #444; padding: 1px 6px; text-align: right; }
th { background: #222; }
tr.tot td { font-weight: bold; background: #333; }
#rows td { cursor: pointer; }
#rows tr:hover td { background: #2a2a2a; }
#rows tr.nochart td { opacity: 0.4; }  /* no embedded window: click shows only the note */
#rows tr.tot td { cursor: default; }   /* totals row is not a trade; no chart opens */
select { background: #222; color: #ddd; border: 1px solid #555; padding: 2px 6px; }
.fig { display: inline-block; vertical-align: top; margin: 4px; }
#hint { color: #888; margin-left: 10px; }
h1 { font-size: 18px; }
#glossary { color: #999; margin-bottom: 8px; }
#msg { color: #f90; }
"""


def _html(title: str, plotlyjs: str, summary_html: str, verdict_cell: str,
           figs_json: str, trades_json: str, coarse_marks: bool = False,
           entry_summary_html: str = "", mark_tf: str = "H4", comparison_html: str = "",
           exposure_note: str = "") -> str:
    mark_timing = f"at {_esc(mark_tf)} candle closes" if coarse_marks else "hourly at each pair's close"
    glossary = ('<div id="glossary">R = distance from entry to the initial stop. '
                "1R = account currency at risk on that trade (net of spread, slippage "
                f"and swap). MTM = mark-to-market: open positions are valued {mark_timing}, "
                "so drawdown on the TOTAL row includes open "
                "floating losses. All pairs share ONE account, so per-pair drawdowns "
                f"are not additive. {_esc(exposure_note)} Acceptance bands live in <code>configs/_base.yaml"
                "</code>, section <code>benchmarks:</code>.</div>")
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>run report - {escape(title)}</title>"
            f"<style>{_CSS}</style><script id=\"plotly-lib\">{plotlyjs}</script></head>\n<body>\n"
            f"<h1>run report - {escape(title)}</h1>\n{glossary}\n{verdict_cell}\n{summary_html}\n{comparison_html}\n{entry_summary_html}\n"
            '<section id="overview"><div class="fig" id="fig-equity"></div>'
            '<div class="fig" id="fig-yearly"></div></section>\n'
            '<section id="browser">\n<select id="pair"></select>\n'
            '<select id="filter"><option value="all">All</option>'
            '<option value="losses">Losses</option>'
            '<option value="winners">Winners</option></select>\n'
            '<select id="exitFilter"><option value="all">All exits</option></select>\n'
            '<select id="reasonFilter"><option value="all">All entry reasons</option></select>\n'
            '<span id="count"></span>\n'
            '<table id="rows"></table>\n'
            '<span id="hint">click a row → chart opens in its own window; use Previous/Next or Left/Right arrows to browse trades</span>\n'
            '<div id="msg"></div>\n'
            "</section>\n"
            f'<script id="figs-json" type="application/json">{figs_json}</script>\n'
            f'<script id="trades-json" type="application/json">{trades_json}</script>\n'
            f"<script>{_APP_JS}</script>\n</body></html>\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a backtest run folder to one HTML.")
    ap.add_argument("--run", required=True, help="backtest_results/<id> folder")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default=None, help="override output path")
    args = ap.parse_args(argv)
    ok = try_write_report(Path(args.run), Path(args.data_dir))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
