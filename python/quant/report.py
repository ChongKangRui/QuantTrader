"""One self-contained HTML per backtest run: overview charts + trade browser.

plotly.js is embedded exactly once. The overview figures render on load; each
trade's candles are stored as a compact JSON blob and drawn only when the user
clicks the trade row (rendered in a separate popup window), so the browser
never renders the whole trade history at once. Both a 1H and a 4H window are
embedded per trade (the report browser picks the timeframe); EMA20/50 are
computed on the FULL series of each timeframe and sliced afterwards, so the
overlays do not restart at the window edge.
"""

import argparse
import json
from html import escape
from pathlib import Path

import pandas as pd

CONTEXT_BEFORE = 120     # H1 bars of context before entry (H1 window, user-requested double)
CONTEXT_AFTER = 40       # H1 bars after exit
WINDOW_CAP = 800         # hard cap on H1 chart length in bars
H4_BEFORE = 60           # H4 bars of context before entry (4H window, same doubling)
H4_AFTER = 20            # H4 bars after exit
H4_CAP = 400             # hard cap on 4H chart length in bars


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


def _run_ema_periods(run_dir: Path) -> tuple[int, int, int, int]:
    """(H1 fast, H1 slow, H4 fast, H4 slow) from the run's params.json strategy
    block; old folders with ema_fast/ema_slow keys and folderless runs fall back
    to the B1 defaults. The report must show what the engine actually used."""
    h1_fast, h1_slow, h4_fast, h4_slow = 20, 50, 20, 50
    path = Path(run_dir) / "params.json"
    if path.exists():
        try:
            st = json.loads(path.read_text(encoding="utf-8")).get("strategy") or {}
            h1_fast = int(st.get("h1_ema_fast", st.get("ema_fast")) or h1_fast)
            h1_slow = int(st.get("h1_ema_slow", st.get("ema_slow")) or h1_slow)
            h4_fast = int(st.get("h4_ema_fast") or h4_fast)
            h4_slow = int(st.get("h4_ema_slow") or h4_slow)
        except Exception:
            pass  # broken params: keep chart defaults rather than fail the report
    return h1_fast, h1_slow, h4_fast, h4_slow


def _bar_arrays(df: pd.DataFrame, e_fast_n: int, e_slow_n: int) -> dict:
    """Loose arrays per timeframe for fast window slicing."""
    from quant.backtest import _ema

    # EMA over the FULL series first, sliced per window afterwards (why: overlay
    # continuity); periods are the run's own (h1_ema_* / h4_ema_* from params)
    return {
        "ts": pd.to_datetime(df["time"]),
        "time": [str(s)[:16] for s in df["time"]],
        "efast": _ema(df["close"], e_fast_n).to_numpy(dtype=float),
        "eslow": _ema(df["close"], e_slow_n).to_numpy(dtype=float),
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
        "efast": _rounds(bars["efast"][i0:i1 + 1]),
        "eslow": _rounds(bars["eslow"][i0:i1 + 1]),
    }


def _contexts(sym: str, h1: pd.DataFrame, trades: pd.DataFrame,
              h4: pd.DataFrame | None, h1_f: int, h1_s: int,
              h4_f: int, h4_s: int) -> list[dict]:
    """Embedded candle windows (1H + optional 4H); entries outside H1 are skipped."""
    b1 = _bar_arrays(h1, h1_f, h1_s)
    b4 = _bar_arrays(h4, h4_f, h4_s) if h4 is not None else None
    out = []
    for _, tr in trades.iterrows():
        w1 = _slice_window(b1, tr["entry_time"], tr["exit_time"],
                           CONTEXT_BEFORE, CONTEXT_AFTER, WINDOW_CAP)
        if w1 is None:
            continue
        out.append({
            "id": str(tr["_id"]), "sym": sym, "side": str(tr["direction"]),
            "entryTime": str(tr["entry_time"])[:16], "exitTime": str(tr["exit_time"])[:16],
            "entry": _round(tr["entry"]), "exit": _round(tr["exit"]),
            "sl": _round(tr["sl"]), "tp": _round(tr["tp"]),
            "pnlR": _round(tr["pnl_R"]), "exitType": str(tr["exit_type"]),
            "bars": int(tr["bars_held"]),
            "pnlUsd": _round(tr["pnl_usd"]),
            "riskUsd": _num(tr, "risk_usd"), "tpUsd": _num(tr, "tp_usd"),
            **w1,
            "h4": None if b4 is None else _slice_window(b4, tr["entry_time"],
                                                        tr["exit_time"],
                                                        H4_BEFORE, H4_AFTER, H4_CAP),
        })
    return out


def _bundle(run_dir: Path, data_dir: Path, trades: list[tuple[str, pd.DataFrame]]
            ) -> tuple[list[dict], int, int, int, int]:
    """Windows + the run's own EMA periods (read once from params.json)."""
    from quant.backtest import load_h1  # generic bars loader (columns/UTC/ascending)

    h1_f, h1_s, h4_f, h4_s = _run_ema_periods(run_dir)
    bundle: list[dict] = []
    for sym, df in trades:
        h1_path = data_dir / f"{sym}_H1.csv"
        if not h1_path.exists():
            continue
        try:
            b1 = load_h1(h1_path)
        except Exception as exc:
            print(f"report: {sym} H1 unreadable ({exc})", flush=True)
            continue
        # Broker H4 export first (data contract); today's runs resample H1 with the
        # engine's build_h4 instead, so the 4H view shows what the engine traded on.
        b4 = None
        h4_path = data_dir / f"{sym}_H4.csv"
        if h4_path.exists():
            try:
                b4 = load_h1(h4_path)
            except Exception as exc:
                print(f"report: {sym} H4 unreadable — 4H view off ({exc})", flush=True)
        else:
            from quant.backtest import build_h4
            b4 = build_h4(b1)
        try:
            bundle.extend(_contexts(sym, b1, df, b4, h1_f, h1_s, h4_f, h4_s))
        except Exception as exc:
            print(f"report: {sym} windows failed ({exc})", flush=True)
    return bundle, h1_f, h1_s, h4_f, h4_s


def write_report(run_dir: Path, data_dir: Path) -> bool:
    s_path = run_dir / "summary.csv"
    if not s_path.exists():
        print(f"report: no {s_path}", flush=True)
        return False
    from plotly.offline import get_plotlyjs

    summary = pd.read_csv(s_path)
    loaded = _load_trades(run_dir)
    all_trades = (pd.concat([df for _, df in loaded], ignore_index=True)
                  if loaded else pd.DataFrame())

    bundle, h1_f, h1_s, h4_f, h4_s = _bundle(Path(run_dir), Path(data_dir), loaded) if loaded \
        else ([], 20, 50, 20, 50)
    embedded = {c["id"]: c for c in bundle}
    embedded_ids = set(embedded)
    meta = [{"id": r["_id"], "sym": r["symbol"], "side": r["direction"],
             "entry": str(r["entry_time"])[:16], "pnlR": _round(r["pnl_R"]),
             "pnlUsd": _round(r["pnl_usd"]),
             "exitType": str(r["exit_type"]), "bars": int(r["bars_held"]),
             "riskUsd": _num(r, "risk_usd"), "tpUsd": _num(r, "tp_usd"),
             "missing": r["_id"] not in embedded_ids}
            for _, r in all_trades.iterrows()]

    verdict_cell = ""
    if "verdict" in summary.columns and len(summary):
        tot = summary[summary["symbol"] == "TOTAL"]
        if len(tot):
            verdict_cell = (f'<div id="verdict">TOTAL verdict: '
                            f"<b>{_esc(tot['verdict'].iloc[0])}</b></div>")

    figs = {"equity": _equity_spec(all_trades, run_dir), "yearly": _yearly_spec(run_dir)}
    no_nan = lambda d: json.dumps(d, separators=(",", ":")).replace("</", "<\\/")
    html = _html(run_dir.name, get_plotlyjs(), _summary_table(summary), verdict_cell,
                 no_nan(figs),
                 no_nan({"embedded": embedded, "meta": meta,
                         "emaH1": {"fast": h1_f, "slow": h1_s},
                         "emaH4": {"fast": h4_f, "slow": h4_s}}))
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
const msgEl = document.getElementById('msg');
const countEl = document.getElementById('count');
const syms = Array.from(new Set(TB.meta.map(function (r) { return r.sym; }))).sort();
pairSel.innerHTML = syms.map(function (s) { return '<option>' + s + '</option>'; }).join('');
const exitTypes = Array.from(new Set(TB.meta.map(function (r) { return r.exitType; }))).sort();
exitSel.innerHTML = '<option value="all">All exits</option>' +
  exitTypes.map(function (t) { return '<option>' + t + '</option>'; }).join('');
function usd(v) { return v == null ? '-' : '$' + v; }
function listTrades() {
  var p = pairSel.value, f = filterSel.value, e = exitSel.value;
  return TB.meta.filter(function (r) {
    if (r.sym !== p) return false;
    if (e !== 'all' && r.exitType !== e) return false;
    return f === 'all' || (f === 'losses' ? r.pnlR < 0 : r.pnlR > 0);
  });
}
function drawList() {
  var rows = listTrades();
  countEl.textContent = rows.length + ' trades (' +
    rows.filter(function (r) { return r.pnlR < 0; }).length + ' losses)';
  rowsEl.innerHTML = '<tr><th>Entry time</th><th>Side</th><th>P/L (USD)</th>' +
    '<th>P/L (R)</th><th>Exit type</th><th>Held (bars)</th>' +
    '<th>1R (USD)</th><th>TP amount (USD)</th></tr>' +
    rows.map(function (r) {
      var col = r.pnlR < 0 ? '#f66' : '#6c6';
      return '<tr data-id="' + r.id + '"' + (r.missing ? ' class="nochart"' : '') +
        '><td>' + r.entry + '</td><td>' + r.side +
        '</td><td style="color:' + col + '">' + usd(r.pnlUsd) +
        '</td><td style="color:' + col + '">' + r.pnlR + '</td><td>' + r.exitType +
        '</td><td>' + r.bars + '</td><td>' + usd(r.riskUsd) +
        '</td><td>' + usd(r.tpUsd) + '</td></tr>';
    }).join('');
}
pairSel.onchange = drawList;
filterSel.onchange = drawList;
exitSel.onchange = drawList;
rowsEl.onclick = function (e) {
  var tr = e.target.closest('tr');
  if (tr && tr.dataset.id) openChart(tr.dataset.id);
};
var curTf = '1h';  // sticks across trades while browsing
var chartWin = null;
var POP_CSS = "body{font:13px system-ui,sans-serif;margin:6px;background:#111;color:#ddd}" +
  "#tfbtns button{background:#222;color:#ddd;border:1px solid #555;padding:3px 14px;cursor:pointer}" +
  "#tfbtns button.on{background:#4a6cf7;border-color:#4a6cf7}" +
  "#tfnote{color:#888;margin-left:8px}";
function chartWindow() {
  var w = window.open('', 'tradechart', 'width=1080,height=720');
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
      '<div id="tfbtns"></div><div id="pop-chart" style="margin-top:6px"></div></body></html>');
    w.document.close();
    w.document.getElementById('tfbtns').onclick = function (e) {
      var b = e.target.closest('button');
      // chartWin always holds the live popup; __tid is that window's trade
      if (b && chartWin && chartWin.__tid) openChart(chartWin.__tid, b.getAttribute('data-tf'));
    };
    w.__init = true;
  }
  chartWin = w;
  return w;
}
function openChart(id, forceTf) {
  var ctx = TB.embedded[id];
  if (!ctx) { msgEl.textContent = 'chart not embedded (no H1 quote data for that trade)'; return; }
  if (forceTf) curTf = forceTf;
  if (!ctx.h4) curTf = '1h';
  var w = chartWindow();
  if (!w) return;
  w.__tid = id;
  w.document.getElementById('tfbtns').innerHTML =
    '<button data-tf="1h"' + (curTf === '1h' ? ' class="on"' : '') + '>1H</button>' +
    (ctx.h4 ? ('<button data-tf="4h"' + (curTf === '4h' ? ' class="on"' : '') + '>4H</button>') : '') +
    (ctx.h4 ? '' : '<span id="tfnote">no H4 data for this run</span>');
  drawChart(w, ctx);
}
function drawChart(w, ctx) {
  var d = (curTf === '4h' && ctx.h4) ? ctx.h4 : ctx;
  var tfName = (d === ctx.h4) ? 'H4' : 'H1';
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
  var per = (TB[tfName === 'H4' ? 'emaH4' : 'emaH1'] || {});
  var traces = [
    {type: 'candlestick', x: d.t, open: d.o, high: d.h, low: d.l, close: d.c,
     name: tfName, increasing_line_color: '#3ddc84', decreasing_line_color: '#ff5f5f'},
    {x: d.t, y: d.efast, type: 'scatter', mode: 'lines',
     name: 'EMA' + per.fast, line: {width: 1.2}},
    {x: d.t, y: d.eslow, type: 'scatter', mode: 'lines',
     name: 'EMA' + per.slow, line: {width: 1.2}},
    // entry marker must be unmistakable on dark candles: yellow, not green
    {x: [ctx.entryTime], y: [ctx.entry], type: 'scatter', mode: 'markers', name: 'entry',
     marker: {size: 13, symbol: 'triangle-up', color: '#ffd400'}},
    {x: [ctx.exitTime], y: [ctx.exit], type: 'scatter', mode: 'markers', name: 'exit',
     marker: {size: 11, symbol: 'triangle-down', color: '#f66'}}
  ];
  var shapes = [{type: 'rect', xref: 'x', yref: 'paper',
                 x0: ctx.entryTime, x1: ctx.exitTime, y0: 0, y1: 1,
                 line: {width: 0}, fillcolor: 'rgba(120,150,255,0.08)'}];
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
select { background: #222; color: #ddd; border: 1px solid #555; padding: 2px 6px; }
.fig { display: inline-block; vertical-align: top; margin: 4px; }
#hint { color: #888; margin-left: 10px; }
h1 { font-size: 18px; }
#glossary { color: #999; margin-bottom: 8px; }
#msg { color: #f90; }
"""


def _html(title: str, plotlyjs: str, summary_html: str, verdict_cell: str,
          figs_json: str, trades_json: str) -> str:
    glossary = ('<div id="glossary">R = distance from entry to the initial stop. '
                "1R = account currency at risk on that trade (net of spread, slippage "
                "and swap). MTM = mark-to-market: open positions are valued hourly at "
                "each pair's close, so drawdown on the TOTAL row includes open "
                "floating losses. All pairs share ONE account, so per-pair drawdowns "
                "are not additive. Acceptance bands live in <code>configs/_base.yaml"
                "</code>, section <code>benchmarks:</code>.</div>")
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>run report - {escape(title)}</title>"
            f"<style>{_CSS}</style><script id=\"plotly-lib\">{plotlyjs}</script></head>\n<body>\n"
            f"<h1>run report - {escape(title)}</h1>\n{glossary}\n{verdict_cell}\n{summary_html}\n"
            '<section id="overview"><div class="fig" id="fig-equity"></div>'
            '<div class="fig" id="fig-yearly"></div></section>\n'
            '<section id="browser">\n<select id="pair"></select>\n'
            '<select id="filter"><option value="all">All</option>'
            '<option value="losses">Losses</option>'
            '<option value="winners">Winners</option></select>\n'
            '<select id="exitFilter"><option value="all">All exits</option></select>\n'
            '<span id="count"></span>\n'
            '<table id="rows"></table>\n'
            '<span id="hint">click a row → chart opens in its own window</span>\n'
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
