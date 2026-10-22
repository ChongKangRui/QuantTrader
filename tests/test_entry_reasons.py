"""Entry diagnostics must never change entries, money or old-reference parity."""
import json

import numpy as np
import pandas as pd
import pytest

from quant import backtest, dice_probe as dp, report
from quant.broker_data import dataset_info, import_exports
from quant.signals import check_entry
from tests.test_broker_data import _exports
from tests.test_dice_probe import _h1, _mapped
from tests.test_report import _blob, _run_dir
from tests.test_signals import _frame, _w1_bars, _W1_ISO


def test_disabled_and_legacy_w1_do_not_claim_modern_patterns():
    bars, _ = _w1_bars("LONG")
    frame = _frame(bars)
    assert check_entry(frame, "LONG", dict(_W1_ISO))["entry_reason"] == "legacy_w1"
    assert check_entry(frame, "LONG", dict(_W1_ISO, use_w1=False))["entry_reason"] == "other"


def test_entry_summary_uses_net_money_counts_scratches_and_keeps_unknowns():
    trades = pd.DataFrame({"symbol": ["EURUSD"] * 4 + ["USDJPY"],
        "entry_reason": ["wick_touch", "wick_touch", "wick_touch", "cross_candle", None],
        "pnl_usd": [10.0, -4.0, 0.0, -1.0, -2.0], "pnl_R": [2.0, -1.0, 0.0, -0.2, -0.4]})
    summary = report.entry_reason_summary(trades)
    total = summary[summary["symbol"] == "TOTAL"].set_index("entry_reason")
    wick = total.loc["wick_touch"]
    assert wick["trades"] == 3 and wick["wins"] == 1 and wick["losses"] == 1
    assert wick["scratches"] == 1 and wick["win_rate_pct"] == 33.33
    assert wick["net_usd"] == 6.0 and wick["loss_usd"] == -4.0 and wick["avg_usd"] == 2.0
    assert total["trades"].sum() == len(trades)
    assert total["net_usd"].sum() == trades["pnl_usd"].sum()
    assert total.loc["unknown", "trades"] == 1
    assert report.entry_reason_summary(pd.DataFrame()).empty


def test_report_renders_labels_summary_and_filter_without_changing_original_csv(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    path = run / "trades_S1.csv"
    trades = pd.read_csv(path)
    trades["entry_reason"] = ["wick_touch", "cross_candle"]
    trades.to_csv(path, index=False)
    original = path.read_bytes()
    assert report.write_report(run, data)
    assert path.read_bytes() == original
    html = (run / "report.html").read_text(encoding="utf-8")
    assert 'id="reasonFilter"' in html and "Entry reason</th>" in html
    assert "Results by entry reason" in html and "Small samples" in html
    assert "reasonSel.onchange = drawList" in html and "r.entryReason !== reason" in html
    payload = _blob(html, "trades-json")
    assert "<th>Lots</th>" in html and "Entry time (UTC)" in html
    assert "Entry time (Malaysia UTC+8)" in html
    assert [r["lot"] for r in payload["meta"]] == trades["lot"].tolist()
    assert payload["meta"][0]["entryMalaysia"] == (
        pd.to_datetime(trades.iloc[0]["entry_time"], utc=True) + pd.Timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    assert [r["entryReasonLabel"] for r in payload["meta"]] == ["Wick touch", "Cross candle"]
    assert all(r["entryReasonSource"] == "recorded" for r in payload["meta"])
    saved = pd.read_csv(run / "entry_summary.csv")
    assert saved[saved["symbol"] == "TOTAL"]["trades"].sum() == 2


def test_old_report_without_verified_source_keeps_unknown_and_escapes_bad_labels(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    path = run / "trades_S1.csv"
    trades = pd.read_csv(path)
    trades["entry_reason"] = [None, '<img src=x onerror="alert(1)">']
    trades.to_csv(path, index=False)
    assert report.write_report(run, data)
    html = (run / "report.html").read_text(encoding="utf-8")
    payload = _blob(html, "trades-json")
    assert all(r["entryReasonLabel"] == "Unknown" for r in payload["meta"])
    assert '<img src=x' not in html


def test_dice_candidates_are_labelled_random_not_candle_patterns():
    env = {"symbol": "EURUSD", "h1": _h1(), "mapped": _mapped(800),
           "t0": 450, "atr": np.full(800, 0.0002)}
    for variant, label in (("A", "dice_a"), ("B", "dice_b")):
        candidates = dp._Stream(env, variant, np.random.default_rng(7)).draw(3)
        assert all(c["entry_reason"] == label for c in candidates)


def test_diagnostic_metadata_cannot_change_trade_execution_or_pnl():
    frame = pd.DataFrame({"time": pd.date_range("2020-01-02", periods=3, freq="4h", tz="UTC"),
        "open": [1.1] * 3, "high": [1.1001, 1.12, 1.1001],
        "low": [1.0999, 1.08, 1.0999], "close": [1.1] * 3})
    candidate = {"t": 0, "time": frame["time"].iloc[0], "direction": "LONG", "atr": 0.001}
    settings = {"stop_atr": 1.5, "tp_mult": 2.5, "use_trail": False, "use_be": False}
    from tests.test_dice_probe import _zero_costs
    plain, funnel = backtest.simulate(frame, "EURUSD", [candidate], settings, _zero_costs(), 3.0, 0.0)
    labelled, labelled_funnel = backtest.simulate(frame, "EURUSD",
        [{**candidate, "entry_reason": "wick_touch"}], settings, _zero_costs(), 3.0, 0.0)
    assert funnel == labelled_funnel
    pd.testing.assert_frame_equal(plain.drop(columns="entry_reason"), labelled.drop(columns="entry_reason"))
    assert labelled.iloc[0]["entry_reason"] == "wick_touch"
    assert labelled.iloc[0]["signal_bar_time"] == str(frame["time"].iloc[0])


def test_old_reference_ignores_only_missing_diagnostic_columns(tmp_path):
    old = pd.DataFrame([{"entry_time": "2020-01-01 00:00+00:00",
        "exit_time": "2020-01-01 04:00+00:00", "pnl_usd": 1.0, "pnl_R": 1.0}])
    old.to_csv(tmp_path / "trades_EURUSD.csv", index=False)
    total = {"trades": 1, "net_usd": 1.0, "expect_R": 1.0, "swap_usd": 0.0}
    pd.DataFrame([{"symbol": "TOTAL", **total}]).to_csv(tmp_path / "summary.csv", index=False)
    current = old.assign(entry_reason="wick_touch", signal_bar_time="2019-12-31 20:00+00:00")
    assert dp.check_parity({"EURUSD": 1}, total, tmp_path, {"EURUSD": current})[0]
    current.loc[0, "pnl_usd"] = 2.0
    assert not dp.check_parity({"EURUSD": 1}, total, tmp_path, {"EURUSD": current})[0]


@pytest.mark.parametrize("problem", [None, "atr", "source", "fill_time", "signal_time", "failed_signal"])
def test_historical_reconstruction_requires_saved_config_source_signal_and_atr(tmp_path, monkeypatch, problem):
    src, dataset, run = tmp_path / "inbox", tmp_path / "broker", tmp_path / "run"
    _exports(src, days=100)
    import_exports(src, dataset, ["EURUSD"])
    run.mkdir()
    frame = backtest.load_h1(dataset / "EURUSD_H4.csv")
    strategy = dict(_W1_ISO, w1_touch_from_trend_side=True, w1_cross_from_other_side=True,
                    entry_ema_fast_period=20, entry_ema_slow_period=100, entry_atr_period=7)
    params = {"broker_data": dataset_info(dataset), "strategy": strategy,
              "timeframes": {"execution": "H4", "regime": "D1"}}
    (run / "params.json").write_text(json.dumps(params))
    row = pd.DataFrame([{"entry_time": str(frame["time"].iloc[501]), "direction": "LONG", "atr": 0.001}])
    checked = []
    def fake_check(window, direction, saved_params):
        checked.append(window["time"].iloc[-1])
        assert saved_params == strategy
        assert len(window) == backtest.WIN_BARS
        return {"signal": problem != "failed_signal", "atr": 0.001, "entry_reason": "cross_candle"}
    monkeypatch.setattr("quant.signals.check_entry", fake_check)
    if problem == "atr":
        row.loc[0, "atr"] = 0.1
    elif problem == "source":
        manifest = json.loads((dataset / "manifest.json").read_text())
        manifest["imported_at_utc"] = "changed"
        (dataset / "manifest.json").write_text(json.dumps(manifest))
    elif problem == "fill_time":
        row.loc[0, "entry_time"] = str(frame["time"].iloc[501] + pd.Timedelta(minutes=1))
    elif problem == "signal_time":
        row["signal_bar_time"] = str(frame["time"].iloc[499])
    original = row.copy()
    annotated = report.annotate_entry_reasons(run, [("EURUSD", row)])[0][1]
    pd.testing.assert_frame_equal(row, original)
    if problem is None:
        assert annotated.iloc[0]["entry_reason"] == "cross_candle"
        assert annotated.iloc[0]["_entry_reason_source"] == "reconstructed"
        assert checked == [frame["time"].iloc[500]]  # Never uses the entry/future candle.
    else:
        assert annotated.iloc[0]["entry_reason"] == "unknown"
