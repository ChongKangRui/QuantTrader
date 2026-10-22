"""Broker H4/D1 intake and coarse offline mode; synthetic files, no terminal."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from quant import backtest, dice_probe as dp
from quant.broker_data import (SOURCE, chart_path, closed_converter, dataset_info,
                               import_exports, pepperstone_utc, resolve_broker_dir)
from tests.test_dice_probe import _setup, _zero_costs


def _exports(root, symbol="EURUSD", days=2, incomplete=False):
    root.mkdir(exist_ok=True)
    dates = pd.bdate_range("2020-01-02", periods=days)
    rows = []
    for day in dates:
        for hour in range(0, 24, 4):
            price = 1.1 + len(rows) * 0.0001
            rows.append({"time": day + pd.Timedelta(hours=hour),
                "<OPEN>": price, "<HIGH>": price + 0.0003, "<LOW>": price - 0.0002,
                "<CLOSE>": price + 0.0001, "<TICKVOL>": 10, "<VOL>": 0, "<SPREAD>": 0})
    frame = pd.DataFrame(rows)
    daily = frame.groupby(frame["time"].dt.normalize()).agg({
        "<OPEN>": "first", "<HIGH>": "max", "<LOW>": "min", "<CLOSE>": "last",
        "<TICKVOL>": "sum", "<VOL>": "sum", "<SPREAD>": "first"})
    daily.insert(0, "<DATE>", daily.index.strftime("%Y.%m.%d"))
    if incomplete:
        frame = frame.iloc[:-1]
    frame.insert(0, "<DATE>", frame["time"].dt.strftime("%Y.%m.%d"))
    frame.insert(1, "<TIME>", frame["time"].dt.strftime("%H:%M:%S"))
    frame.drop(columns="time").to_csv(root / f"{symbol}_H4_test_PEPPERSTONE.csv", sep="\t", index=False)
    daily.to_csv(root / f"{symbol}_Daily_test_PEPPERSTONE.csv", sep="\t", index=False)


def test_pepperstone_clock_uses_us_dst_not_european_dst():
    server = pd.Series(pd.to_datetime(["2020-01-02", "2020-03-09", "2020-10-26", "2020-11-02"]))
    result = pepperstone_utc(server)
    assert list(result.dt.strftime("%Y-%m-%d %H:%M")) == [
        "2020-01-01 22:00", "2020-03-08 21:00", "2020-10-25 21:00", "2020-11-01 22:00"]


def test_intake_archives_original_bytes_and_normalizes_without_h1(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    originals = {p.name: p.read_bytes() for p in src.glob("*.csv")}
    manifest = import_exports(src, dest, ["EURUSD"])
    assert manifest["source_type"] == SOURCE
    assert not list(src.glob("*.csv"))
    assert all((dest / "raw" / name).read_bytes() == content for name, content in originals.items())
    h4 = pd.read_csv(chart_path(dest, "EURUSD", "H4"))
    assert len(h4) == 12 and h4["time"].iloc[0].startswith("2020-01-01 22:00")
    assert not (dest / "EURUSD_H1.csv").exists()
    assert not manifest["warnings"]
    assert dataset_info(dest)["source_type"] == SOURCE


def test_last_day_gap_is_recorded_not_filled_or_trimmed(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src, incomplete=True)
    manifest = import_exports(src, dest, ["EURUSD"])
    assert len(pd.read_csv(dest / "EURUSD_H4.csv")) == 11
    assert len(pd.read_csv(dest / "EURUSD_D1.csv")) == 2
    assert "5 H4 candles" in manifest["warnings"][0]


def test_missing_enabled_pair_fails_before_moving_any_original(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    with pytest.raises(ValueError, match="expected one tagged export"):
        import_exports(src, dest, ["EURUSD", "USDJPY"])
    assert len(list(src.glob("*.csv"))) == 2 and not dest.exists()


def test_intake_refuses_bad_prices_and_preserves_inputs(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    path = next(src.glob("*H4*"))
    frame = pd.read_csv(path, sep="\t")
    frame.loc[0, "<HIGH>"] = 0.1
    frame.to_csv(path, sep="\t", index=False)
    with pytest.raises(ValueError, match="invalid prices"):
        import_exports(src, dest, ["EURUSD"])
    assert path.exists() and not dest.exists()


def test_converter_close_only_appears_at_following_open(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src, "USDJPY")
    import_exports(src, dest, ["USDJPY"])
    frame = pd.read_csv(chart_path(dest, "USDJPY", "H4"))
    times = pd.to_datetime(frame["time"], utc=True)
    series = closed_converter(dest, "USDJPY")
    assert pd.isna(series.asof(times.iloc[0]))
    assert series.asof(times.iloc[1]) == frame["close"].iloc[0]
    assert len(series) == len(frame) - 1


def test_dataset_tampering_and_wrong_tape_refused(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    with pytest.raises(ValueError, match="matching H4"):
        backtest.load_chart_frames("EURUSD", src / "EURUSD_H1.csv", 4, 24, None, dest)
    path = dest / "EURUSD_H4.csv"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        chart_path(dest, "EURUSD", "H4")


def test_offline_mode_can_be_disabled_and_research_is_explicit_override(tmp_path):
    base = {"backtest_data": {"use_broker_csv": True, "broker_csv_dir": str(tmp_path), "position_checks": "H4"}}
    assert resolve_broker_dir(base) == str(tmp_path.resolve())
    assert resolve_broker_dir(base, research_dir="research") is None
    base["backtest_data"]["use_broker_csv"] = False
    assert resolve_broker_dir(base) is None
    assert resolve_broker_dir(base, override=tmp_path) == str(tmp_path.resolve())
    base["backtest_data"]["use_broker_csv"] = "false"
    with pytest.raises(ValueError, match="true or false"):
        resolve_broker_dir(base)


def test_broker_h4_real_dice_parity_without_any_h1_m1(tmp_path, monkeypatch):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src, days=150)
    import_exports(src, dest, ["EURUSD"])
    setup = _setup(exec_hours=4, reg_hours=24, broker_data_dir=str(dest),
                   position_checks="H4", default_lot=0.01, stop_sizing={})
    setup["strategy"].update(bias_ema_fast_period=2, bias_ema_slow_period=5,
        use_atr_sep=False, use_e1_setup=False, use_e1_trigger=False, use_hr2=False,
        use_hr3=False, use_hr4=False, use_ext=False, use_w1=False)
    def forbidden(*args, **kwargs):
        pytest.fail("broker-only mode must never request M1")
    monkeypatch.setattr(backtest, "_load_m1", forbidden)
    monkeypatch.setattr(dp, "_load_m1", forbidden)
    monkeypatch.setattr(dp, "_STATE", {})
    tape = dest / "EURUSD_H4.csv"
    args = SimpleNamespace(exec_hours=4, reg_hours=24, broker_data_dir=str(dest),
        position_checks="H4", no_trade_ranges=(), risk_usd=3.0, max_cost_ratio=0.1,
        lot=None, scope_low=0, scope_high=0, stop_sizing={}, default_lot=0.01)
    expected = backtest.run_pair("EURUSD", tape, setup["strategy"], _zero_costs(), args)["trades"]
    _, actual, _ = dp._real_one("EURUSD", str(tape), _zero_costs(), setup)
    assert len(expected) > 0
    pd.testing.assert_frame_equal(actual, expected)
    entries, exits = pd.to_datetime(actual["entry_time"], utc=True), pd.to_datetime(actual["exit_time"], utc=True)
    assert (exits >= entries + pd.Timedelta(hours=4)).all()


def test_dice_config_selects_broker_h4_and_converters_without_vendor_feeds(tmp_path):
    import yaml

    src, dest, cfg = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "configs"
    _exports(src, "EURJPY")
    _exports(src, "USDJPY")
    import_exports(src, dest, ["EURJPY", "USDJPY"])
    cfg.mkdir()
    (cfg / "EURJPY.yaml").write_text("symbol: EURJPY\n")
    (cfg / "_base.yaml").write_text(yaml.safe_dump({
        "timeframes": {"execution": "H4", "regime": "D1", "position_checks": "M1"},
        "backtest_data": {"use_broker_csv": True, "broker_csv_dir": str(dest), "position_checks": "H4"}}))
    setup = dp.resolve_setup(str(cfg), str(tmp_path / "no_vendor_data"))
    assert setup["position_checks"] == "H4"
    assert setup["jobs"][0][1] == dest / "EURJPY_H4.csv"
    assert setup["broker_data"]["source_type"] == SOURCE
    assert len(setup["converters"]["USDJPY"]) == 11


def test_broker_report_has_no_fabricated_raw_h1_view(tmp_path, monkeypatch):
    from quant import report
    from tests.test_report import _blob, _trade_row

    src, dest, run = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "run"
    _exports(src, days=30)
    import_exports(src, dest, ["EURUSD"])
    run.mkdir()
    times = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(dest / "EURUSD_H4.csv")["time"], utc=True))
    pd.DataFrame([_trade_row("EURUSD", 100, 120, "LONG", 2.0, times)]).to_csv(run / "trades_EURUSD.csv", index=False)
    pd.DataFrame([{"symbol": "TOTAL", "trades": 1, "net_usd": 6.0, "net_R": 2.0}]).to_csv(run / "summary.csv", index=False)
    (run / "params.json").write_text(json.dumps({"broker_data": dataset_info(dest),
        "timeframes": {"execution": "H4", "regime": "D1"}}))
    def forbidden(*args, **kwargs):
        pytest.fail("broker report must load exact manifest charts, not resample")
    monkeypatch.setattr(report, "_tf_bars", forbidden)
    assert report.write_report(run, tmp_path / "no_vendor_data")
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "Broker H4-only" in html
    assert "H4-close marks" in html and "valued at H4 candle closes" in html
    payload = _blob(html, "trades-json")
    assert "raw" not in payload["embedded"]["EURUSD-0"]
    assert not payload["meta"][0]["missing"]


def test_ambiguous_h4_stop_wins_and_books_only_at_bar_close():
    frame = pd.DataFrame({"time": pd.date_range("2020-01-02", periods=3, freq="4h", tz="UTC"),
        "open": [1.1] * 3, "high": [1.1001, 1.12, 1.1001],
        "low": [1.0999, 1.08, 1.0999], "close": [1.1] * 3})
    candidates = [{"t": 0, "time": frame["time"].iloc[0], "direction": "LONG", "atr": 0.001}]
    trades, _ = backtest.simulate(frame, "EURUSD", candidates,
        {"stop_atr": 1.5, "tp_mult": 2.5, "use_trail": False, "use_be": False},
        _zero_costs(), 3.0, 0.0, bar_hours=4, default_lot=0.01, coarse_exit_at_close=True)
    assert len(trades) == 1 and trades.iloc[0]["exit_type"] == "stop"
    assert pd.Timestamp(trades.iloc[0]["entry_time"]) == frame["time"].iloc[1]
    assert pd.Timestamp(trades.iloc[0]["exit_time"]) == frame["time"].iloc[2]
