"""Report tests: hermetic run folder, lazy plotly embed, per-trade JSON blobs."""

import json
import re

import numpy as np
import pandas as pd
import pytest

from quant.report import try_write_report, write_report


def test_summary_table_readable_labels():
    from quant.report import _summary_table

    html = _summary_table(pd.DataFrame(
        [{"symbol": "TOTAL", "expect_R": -0.062, "per_month": 56.3}]))
    assert "Avg P/L per trade (R)" in html and "Trades per month" in html


def _h1(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    times = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    close = 1.1 + rng.normal(0, 0.0005, n).cumsum()
    return pd.DataFrame({"time": times, "open": close, "high": close + 0.0004,
                         "low": close - 0.0004, "close": close})


def _h4(n: int = 75) -> pd.DataFrame:
    # 01:00-anchored grid so broker-file bars differ from build_h4's 00:00 resample
    rng = np.random.default_rng(11)
    times = pd.date_range("2020-01-01 01:00", periods=n, freq="4h", tz="UTC")
    close = 1.1 + rng.normal(0, 0.0005, n).cumsum()
    return pd.DataFrame({"time": times, "open": close, "high": close + 0.0004,
                         "low": close - 0.0004, "close": close})


def _trade_row(sym: str, i_in: int, i_out: int, side: str, pnl_r: float,
               times: pd.DatetimeIndex) -> dict:
    return {"symbol": sym, "direction": side,
            "entry_time": str(times[i_in]), "entry": 1.105,
            "sl": 1.09, "tp": 1.14,
            "exit_time": str(times[i_out]), "exit": 1.12, "exit_type": "target",
            "lot": 0.01, "pnl_usd": pnl_r * 3, "pnl_R": pnl_r, "swap": 0.0,
            "atr": 0.0012, "bars_held": i_out - i_in}


def _run_dir(tmp_path, with_h1: bool = True):
    run = tmp_path / "run1"
    run.mkdir()
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    times = pd.DatetimeIndex(pd.date_range("2020-01-01", periods=300, freq="1h", tz="UTC"))
    trades = pd.DataFrame([
        _trade_row("S1", 100, 120, "LONG", 2.0, times),
        _trade_row("S1", 200, 230, "SHORT", -1.0, times),
    ])
    trades.to_csv(run / "trades_S1.csv", index=False)
    if with_h1:
        _h1().to_csv(data / "S1_H1.csv", index=False)
    summary = pd.DataFrame([
        {"trades": 1, "net_usd": 6.0, "net_R": 2.0, "win_rate": 1.0, "symbol": "S1",
         "verdict": "PASS"},
        {"trades": 2, "net_usd": 3.0, "net_R": 1.0, "win_rate": 0.5, "symbol": "TOTAL",
         "verdict": "FAIL"},
    ])
    summary.to_csv(run / "summary.csv", index=False)
    return run, data, times


def _blob(html: str, marker: str) -> dict:
    m = re.search(rf'<script id="{marker}" type="application/json">(.*?)</script>',
                  html, re.S)
    return json.loads(m.group(1))


def test_write_report_full(tmp_path):
    from plotly.offline import get_plotlyjs

    run, data, times = _run_dir(tmp_path)
    assert write_report(run, data) is True
    html = (run / "report.html").read_text(encoding="utf-8")
    assert html.count(get_plotlyjs()) == 1  # embedded exactly once, no CDN
    tb = _blob(html, "trades-json")
    figs = _blob(html, "figs-json")
    assert len(tb["meta"]) == 2 and all(not r["missing"] for r in tb["meta"])
    assert all(r["swap"] == 0.0 for r in tb["meta"])  # per-trade swap feeds the JS totals
    assert set(tb["embedded"]) == {"S1-0", "S1-1"}
    ctx = tb["embedded"]["S1-0"]
    # entry at index 100: window 0..160 (120 before, 40 after exit at 120)
    assert len(ctx["t"]) == len(ctx["o"]) == len(ctx["c"]) == 161
    assert ctx["efast"][0] is not None and ctx["eslow"][0] is not None
    assert tb["emaH1"] == {"fast": 20, "slow": 50}   # no params.json -> B1 defaults
    assert tb["emaH4"] == {"fast": 20, "slow": 50}
    assert figs["equity"] is not None and figs["yearly"] is None  # no yearly.csv
    assert 'class="tot"' in html  # TOTAL row highlighted
    assert "TOTAL verdict" in html
    # no broker H4 CSV -> the engine's H1 resample (build_h4) feeds the 4H view
    assert ctx["h4"] is not None and ctx["h4"]["t"][0] == "2020-01-01 00:00"


def test_h4_window_embedded(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    _h4().to_csv(data / "S1_H4.csv", index=False)
    assert write_report(run, data) is True
    html = (run / "report.html").read_text(encoding="utf-8")
    ctx = _blob(html, "trades-json")["embedded"]["S1-0"]
    h4 = ctx["h4"]
    # broker file wins over the resample: its 01:00-anchored grid, bar 25 holds
    # the 04:00 entry; window is 60 bars before (clamped to bar 0) .. 20 after exit
    assert h4 is not None
    assert h4["t"][0] == "2020-01-01 01:00" and len(h4["t"]) == 50 == len(h4["c"])
    assert h4["efast"][0] is not None and h4["eslow"][-1] is not None
    assert h4["t"] != ctx["t"]                       # the two views differ
    assert '#ffd400' in html                         # yellow entry marker
    assert 'window.open' in html                     # chart renders in a popup
    assert '<script id="plotly-lib">' in html        # popup copies the lib at runtime
    assert "document.getElementById('plotly-lib')" in html
    assert '<div id="trade-chart"></div>' not in html  # inline chart gone


def test_ema_periods_follow_params(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    (run / "params.json").write_text(json.dumps(
        {"strategy": {"h1_ema_fast": 20, "h1_ema_slow": 100,
                      "h4_ema_fast": 10, "h4_ema_slow": 200}}), encoding="utf-8")
    assert write_report(run, data) is True
    html = (run / "report.html").read_text(encoding="utf-8")
    tb = _blob(html, "trades-json")
    ctx = tb["embedded"]["S1-0"]
    assert tb["emaH1"] == {"fast": 20, "slow": 100}
    assert tb["emaH4"] == {"fast": 10, "slow": 200}
    # keys rename: the window carries whichever period the run was configured with
    assert ctx["efast"] is not None and ctx["eslow"] is not None and ctx["h4"]["eslow"] is not None


def test_ema_periods_fall_back_to_old_key_names(tmp_path):
    # runs recorded before the rename stored plain ema_fast/ema_slow
    run, data, _ = _run_dir(tmp_path)
    (run / "params.json").write_text(json.dumps(
        {"strategy": {"ema_fast": 20, "ema_slow": 33}}), encoding="utf-8")
    assert write_report(run, data) is True
    tb = _blob((run / "report.html").read_text(encoding="utf-8"), "trades-json")
    assert tb["emaH1"] == {"fast": 20, "slow": 33}
    assert tb["emaH4"] == {"fast": 20, "slow": 50}


def test_missing_h1_and_yearly_skip(tmp_path):
    run, data, _ = _run_dir(tmp_path, with_h1=False)
    assert write_report(run, data) is True
    html = (run / "report.html").read_text(encoding="utf-8")
    tb = _blob(html, "trades-json")
    assert not tb["embedded"] and all(r["missing"] for r in tb["meta"])
    assert _blob(html, "figs-json")["equity"] is not None  # equity needs no candles


def test_empty_and_broken_dirs(tmp_path):
    assert try_write_report(tmp_path / "nope") is False  # no summary -> False, no raise
    empty = tmp_path / "empty"
    empty.mkdir()
    assert try_write_report(empty) is False
