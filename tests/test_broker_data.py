"""Broker H4/D1 intake and coarse offline mode; synthetic files, no terminal."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from quant import backtest, dice_probe as dp
from quant.broker_data import (SOURCE, chart_path, closed_converter, dataset_info,
                               import_exports, import_h1_exports, pepperstone_utc,
                               resolve_broker_dir)
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


@pytest.mark.parametrize("checks", ["H4", "H1"])
def test_dice_config_selects_broker_h4_and_converters_without_vendor_feeds(tmp_path, checks):
    import yaml

    src, dest, cfg = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "configs"
    _exports(src, "EURJPY")
    _exports(src, "USDJPY")
    import_exports(src, dest, ["EURJPY", "USDJPY"])
    if checks == "H1":
        for symbol in ("EURJPY", "USDJPY"):
            _h1_exports(src, dest, symbol)
        import_h1_exports(src, dest, ["EURJPY", "USDJPY"])
    cfg.mkdir()
    (cfg / "EURJPY.yaml").write_text("symbol: EURJPY\n")
    (cfg / "_base.yaml").write_text(yaml.safe_dump({
        "timeframes": {"execution": "H4", "regime": "D1", "position_checks": "M1"},
        "backtest_data": {"use_broker_csv": True, "broker_csv_dir": str(dest), "position_checks": checks}}))
    setup = dp.resolve_setup(str(cfg), str(tmp_path / "no_vendor_data"))
    assert setup["position_checks"] == checks
    assert setup["jobs"][0][1] == dest / "EURJPY_H4.csv"
    assert setup["broker_data"]["source_type"] == SOURCE
    assert len(setup["converters"]["USDJPY"]) == (47 if checks == "H1" else 11)


@pytest.mark.parametrize("checks", ["H4", "H1"])
def test_broker_report_has_no_fabricated_raw_h1_view(tmp_path, monkeypatch, checks):
    from quant import report
    from tests.test_report import _blob, _trade_row

    src, dest, run = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "run"
    _exports(src, days=30)
    import_exports(src, dest, ["EURUSD"])
    if checks == "H1":
        _h1_exports(src, dest)
        import_h1_exports(src, dest, ["EURUSD"])
    run.mkdir()
    times = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(dest / "EURUSD_H4.csv")["time"], utc=True))
    pd.DataFrame([_trade_row("EURUSD", 100, 120, "LONG", 2.0, times)]).to_csv(run / "trades_EURUSD.csv", index=False)
    pd.DataFrame([{"symbol": "TOTAL", "trades": 1, "net_usd": 6.0, "net_R": 2.0}]).to_csv(run / "summary.csv", index=False)
    (run / "params.json").write_text(json.dumps({"broker_data": dataset_info(dest, "H4", checks),
        "timeframes": {"execution": "H4", "regime": "D1"}}))
    def forbidden(*args, **kwargs):
        pytest.fail("broker report must load exact manifest charts, not resample")
    monkeypatch.setattr(report, "_tf_bars", forbidden)
    assert report.write_report(run, tmp_path / "no_vendor_data")
    html = (run / "report.html").read_text(encoding="utf-8")
    assert ("Broker H1 position checks" if checks == "H1" else "Broker H4-only") in html
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


def _h1_exports(src, dest, symbol="EURUSD"):
    """Synthetic hourly observations with the same OHLC as the fixture's H4 bars."""
    frame = pd.read_csv(dest / "raw" / f"{symbol}_H4_test_PEPPERSTONE.csv", sep="\t")
    rows = []
    for _, row in frame.iterrows():
        stamp = pd.to_datetime(row["<DATE>"] + " " + row["<TIME>"])
        for hour in range(4):
            item = row.to_dict()
            now = stamp + pd.Timedelta(hours=hour)
            item.update({"<DATE>": now.strftime("%Y.%m.%d"), "<TIME>": now.strftime("%H:%M:%S")})
            rows.append(item)
    path = src / f"{symbol}_H1_test_PEPPERSTONE.csv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    return path


def test_h1_extension_preserves_base_identity_and_originals(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    before = dataset_info(dest)
    original_manifest = (dest / "manifest.json").read_bytes()
    path = _h1_exports(src, dest)
    original = path.read_bytes()
    manifest = import_h1_exports(src, dest, ["EURUSD"])
    assert not path.exists()
    assert (dest / "raw" / path.name).read_bytes() == original
    assert (dest / "manifest.json").read_bytes() == original_manifest
    assert dataset_info(dest) == before
    identity = dataset_info(dest, "H1")
    assert identity["h1_manifest_sha256"] and "Broker H1-only" in identity["warning"]
    assert manifest["symbols"]["EURUSD"]["H1"]["bars"] == 48
    hourly = pd.read_csv(chart_path(dest, "EURUSD", "H1"))
    assert hourly.time.iloc[0].startswith("2020-01-01 22:00")
    times = pd.to_datetime(hourly.time, utc=True)
    converter = closed_converter(dest, "EURUSD", "H1")
    assert pd.isna(converter.asof(times.iloc[0]))
    assert converter.asof(times.iloc[1]) == hourly.close.iloc[0]
    with pytest.raises(FileExistsError, match="already exists"):
        import_h1_exports(src, dest, ["EURUSD"])
    (dest / "EURUSD_H1.csv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        chart_path(dest, "EURUSD", "H1")


@pytest.mark.parametrize("fault", ["missing_pair", "different_price", "missing_period"])
def test_h1_failure_does_not_publish_or_move_inputs(tmp_path, fault):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    path = _h1_exports(src, dest)
    symbols = ["EURUSD"]
    if fault == "missing_pair":
        symbols.append("USDJPY")
    else:
        frame = pd.read_csv(path, sep="\t")
        if fault == "different_price":
            frame.loc[0, "<HIGH>"] += 0.01
        else:
            frame = frame.iloc[4:]
        frame.to_csv(path, sep="\t", index=False)
    before = dataset_info(dest)
    with pytest.raises(ValueError):
        import_h1_exports(src, dest, symbols)
    assert path.exists() and dataset_info(dest) == before
    assert not (dest / "manifest_h1.json").exists()
    assert not (dest / "EURUSD_H1.csv").exists()


def test_h1_partial_period_is_warned_not_filled(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    path = _h1_exports(src, dest)
    frame = pd.read_csv(path, sep="\t").iloc[1:]
    frame.to_csv(path, sep="\t", index=False)
    manifest = import_h1_exports(src, dest, ["EURUSD"])
    assert "1 H4 periods" in manifest["warnings"][0]
    assert "no hours filled" in manifest["warnings"][0]
    assert len(pd.read_csv(chart_path(dest, "EURUSD", "H1"))) == 47


@pytest.mark.parametrize("reg_hours,reg_bars", [(4, 12), (24, 2)])
def test_h1_grid_uses_broker_regime_without_resampling(tmp_path, monkeypatch, reg_hours, reg_bars):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    def forbidden(*args, **kwargs):
        pytest.fail("broker charts must not be resampled")
    monkeypatch.setattr(backtest, "build_htf", forbidden)
    tape, execution, regime, closed = backtest.load_chart_frames(
        "EURUSD", dest / "EURUSD_H1.csv", 1, reg_hours, None, dest)
    assert len(tape) == len(execution) == 48 and len(regime) == reg_bars and closed
    with pytest.raises(ValueError, match="matching H1"):
        backtest.load_chart_frames("EURUSD", src / "EURUSD_H1.csv", 1, reg_hours, None, dest)


@pytest.mark.parametrize("regime,reg_hours", [("H4", 4), ("D1", 24)])
def test_broker_h1_real_dice_parity_and_source_resolution(tmp_path, monkeypatch, regime, reg_hours):
    import yaml

    src, dest, cfg = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "configs"
    _exports(src, days=40)
    import_exports(src, dest, ["EURUSD"])
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    cfg.mkdir()
    strategy = {"warmup_bars": 10, "bias_ema_fast_period": 2, "bias_ema_slow_period": 5,
        "use_atr_sep": False, "use_e1_setup": False, "use_e1_trigger": False,
        "use_hr2": False, "use_hr3": False, "use_hr4": False, "use_ext": False,
        "use_w1": False, "use_trail": False, "use_be": False}
    (cfg / "EURUSD.yaml").write_text("symbol: EURUSD\n")
    (cfg / "_base.yaml").write_text(yaml.safe_dump({
        "timeframes": {"execution": "H1", "regime": regime},
        "strategy": strategy, "costs": _zero_costs(),
        "backtest_data": {"use_broker_csv": True, "broker_csv_dir": str(dest), "position_checks": "H1"}}))
    setup = dp.resolve_setup(str(cfg), str(tmp_path / "no_vendor"))
    assert setup["jobs"][0][1] == dest / "EURUSD_H1.csv"
    assert setup["position_checks"] == "H1" and setup["broker_data"]["h1_manifest_sha256"]
    assert setup["regime"] == regime and setup["reg_hours"] == reg_hours
    def forbidden(*args, **kwargs):
        pytest.fail("broker-only H1 must never request vendor M1")
    monkeypatch.setattr(backtest, "_load_m1", forbidden)
    monkeypatch.setattr(dp, "_load_m1", forbidden)
    monkeypatch.setattr(dp, "_STATE", {})
    args = SimpleNamespace(exec_hours=1, reg_hours=reg_hours, broker_data_dir=str(dest),
        position_checks="H1", no_trade_ranges=(), risk_usd=3.0, max_cost_ratio=0.1,
        lot=None, scope_low=0, scope_high=0, stop_sizing={}, default_lot=0.01)
    expected = backtest.run_pair("EURUSD", dest / "EURUSD_H1.csv", setup["strategy"], _zero_costs(), args)["trades"]
    _, actual, _ = dp._real_one("EURUSD", str(dest / "EURUSD_H1.csv"), _zero_costs(), setup)
    assert len(expected) > 0
    pd.testing.assert_frame_equal(actual, expected)
    assert (pd.to_datetime(actual.exit_time, utc=True) >= pd.to_datetime(actual.entry_time, utc=True)
            + pd.Timedelta(hours=1)).all()


@pytest.mark.parametrize("regime", ["H4", "D1"])
def test_h1_report_uses_exact_hourly_charts_and_labels(tmp_path, monkeypatch, regime):
    from quant import report
    from tests.test_report import _blob, _trade_row

    src, dest, run = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "run"
    _exports(src, days=30)
    import_exports(src, dest, ["EURUSD"])
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    run.mkdir()
    times = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(dest / "EURUSD_H1.csv").time, utc=True))
    pd.DataFrame([_trade_row("EURUSD", 100, 120, "LONG", 2.0, times)]).to_csv(run / "trades_EURUSD.csv", index=False)
    pd.DataFrame([{"symbol": "TOTAL", "trades": 1, "net_usd": 6.0, "net_R": 2.0}]).to_csv(run / "summary.csv", index=False)
    (run / "params.json").write_text(json.dumps({"broker_data": dataset_info(dest, "H1"),
        "timeframes": {"execution": "H1", "regime": regime}}))
    def forbidden(*args, **kwargs):
        pytest.fail("broker H1/H4 report must not resample prices")
    monkeypatch.setattr(report, "_tf_bars", forbidden)
    assert report.write_report(run, tmp_path / "no_vendor")
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "Broker H1-only" in html and "H1-close marks" in html
    assert "valued at H1 candle closes" in html
    payload = _blob(html, "trades-json")
    assert not payload["meta"][0]["missing"]
    assert payload["tf"]["reg"] == ("Daily" if regime == "D1" else "H4")


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_h4_entries_trail_on_completed_h1_checks_only(side):
    execution = pd.DataFrame({"time": pd.date_range("2020-01-02", periods=3, freq="4h", tz="UTC"),
        "open": [100.] * 3, "high": [100., 120., 100.],
        "low": [100., 99., 100.], "close": [100.] * 3})
    hourly = pd.DataFrame({"time": pd.date_range("2020-01-02", periods=12, freq="h", tz="UTC"),
        "open": [100.] * 12, "high": [100.] * 12, "low": [100.] * 12, "close": [100.] * 12})
    hourly.loc[4, ["high", "low", "close"]] = [115., 99., 110.]
    hourly.loc[5, ["open", "high", "low", "close"]] = [110., 120., 104., 110.]
    if side == "SHORT":
        for frame in (execution, hourly):
            frame["open"], frame["close"] = 200 - frame.open, 200 - frame.close
            frame["high"], frame["low"] = 200 - frame.low, 200 - frame.high
    trades, _ = backtest.simulate(execution, "EURUSD",
        [{"t": 0, "direction": side, "atr": 10.}],
        {"stop_atr": 1., "tp_mult": 10., "use_trail": True, "trail_r": 1., "use_be": False},
        _zero_costs(), 3., 0., bar_hours=4, default_lot=0.01, position_bars=hourly)
    assert len(trades) == 1
    trade = trades.iloc[0]
    assert pd.Timestamp(trade.entry_time) == execution.time.iloc[1]
    assert pd.Timestamp(trade.exit_time) == hourly.time.iloc[5] + pd.Timedelta(hours=1)
    assert trade.exit_type == "stop"
    assert trade["exit"] == (105. if side == "LONG" else 95.)


def test_required_hourly_checks_never_fall_back_to_h4():
    execution = pd.DataFrame({"time": pd.date_range("2020-01-02", periods=3, freq="4h", tz="UTC"),
        "open": [1.1] * 3, "high": [1.2] * 3, "low": [1.] * 3, "close": [1.1] * 3})
    for hourly in (execution.iloc[:0], execution.iloc[:1]):
        with pytest.raises(ValueError, match="broker H1"):
            backtest.simulate(execution, "EURUSD", [{"t": 0, "direction": "LONG", "atr": .01}],
                {"use_trail": False}, _zero_costs(), 3., 0., bar_hours=4,
                default_lot=.01, position_bars=hourly)


def test_h4_h1_checks_real_dice_and_manifest_parity(tmp_path, monkeypatch):
    import yaml

    src, dest, cfg = tmp_path / "inbox", tmp_path / "pepperstone", tmp_path / "configs"
    _exports(src, days=80)
    import_exports(src, dest, ["EURUSD"])
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    cfg.mkdir()
    strategy = {"warmup_bars": 10, "bias_ema_fast_period": 2, "bias_ema_slow_period": 5,
        "use_atr_sep": False, "use_e1_setup": False, "use_e1_trigger": False,
        "use_hr2": False, "use_hr3": False, "use_hr4": False, "use_ext": False,
        "use_w1": False, "use_trail": True, "trail_r": 1., "use_be": False}
    (cfg / "EURUSD.yaml").write_text("symbol: EURUSD\n")
    (cfg / "_base.yaml").write_text(yaml.safe_dump({
        "timeframes": {"execution": "H4", "regime": "D1"},
        "strategy": strategy, "costs": _zero_costs(),
        "backtest_data": {"use_broker_csv": True, "broker_csv_dir": str(dest), "position_checks": "H1"}}))
    setup = dp.resolve_setup(str(cfg), str(tmp_path / "no_vendor"))
    assert setup["position_checks"] == "H1"
    assert setup["execution"] == "H4" and setup["regime"] == "D1"
    assert setup["broker_data"]["h1_manifest_sha256"]
    assert "H1 position checks" in setup["broker_data"]["warning"]
    assert "H4 closes" in setup["broker_data"]["warning"]
    monkeypatch.setattr(dp, "_STATE", {})
    args = SimpleNamespace(exec_hours=4, reg_hours=24, broker_data_dir=str(dest),
        position_checks="H1", no_trade_ranges=(), risk_usd=3., max_cost_ratio=.1,
        lot=None, scope_low=0, scope_high=0, stop_sizing={}, default_lot=.01, compare_results=True)
    tape = dest / "EURUSD_H4.csv"
    result = backtest.run_pair("EURUSD", tape, setup["strategy"], _zero_costs(), args)
    _, actual, _ = dp._real_one("EURUSD", str(tape), _zero_costs(), setup)
    assert len(actual) > 0
    pd.testing.assert_frame_equal(actual, result["trades"])
    assert result["comparison_inputs"]["position_bars"]
    assert result["available_seconds"] == result["n_bars"] * 4 * 3600
    assert result["metrics"]["exposure_pct"] == round(
        100 * result["trades"].exposure_seconds.sum() / result["available_seconds"], 2)
    # An old H4-only identity cannot validate the new H1-check dataset.
    assert dataset_info(dest, "H4") != setup["broker_data"]
    hourly = backtest.load_h1(chart_path(dest, "EURUSD", "H1"))
    execution = backtest.load_h1(tape)
    monkeypatch.setattr(backtest, "load_h1", lambda path: hourly.iloc[4:])
    with pytest.raises(ValueError, match="coverage missing"):
        backtest.load_position_bars("EURUSD", execution, dest, "H1", 4)


def test_h1_checks_require_valid_broker_extension(tmp_path):
    src, dest = tmp_path / "inbox", tmp_path / "pepperstone"
    _exports(src)
    import_exports(src, dest, ["EURUSD"])
    with pytest.raises(FileNotFoundError):
        dataset_info(dest, "H4", "H1")
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    (dest / "EURUSD_H1.csv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        backtest.load_position_bars("EURUSD", backtest.load_h1(dest / "EURUSD_H4.csv"), dest, "H1", 4)


def _api_collection(root, start="2019-12-31 22:00Z", *, price=1.1):
    from quant.broker_data import API_SOURCE
    from quant.mkdata import file_digest

    root.mkdir()
    files = {}
    for tf in ("H1", "H4", "D1"):
        name = f"EURUSD_{tf}.csv"
        pd.DataFrame({"time": [pd.Timestamp(start)], "open": [price], "high": [price + .001],
            "low": [price - .001], "close": [price], "tick_volume": [10]}).to_csv(root / name, index=False)
        files[name] = {"sha256": file_digest(root / name)}
        meta = f"EURUSD_{tf}.meta.json"
        (root / meta).write_text(json.dumps({"symbol": "EURUSD", "timeframe": tf,
            "timestamp_timezone": "UTC", "source_type": API_SOURCE, "broker_server": "Pepperstone-Demo"}))
        files[meta] = {"sha256": file_digest(root / meta)}
    (root / "quality_audit.json").write_text(json.dumps({"issues": [], "warnings": ["source gap retained"]}))
    spec = {"version": 1, "source_type": API_SOURCE, "status": "quality_checks_passed_with_session_warnings",
        "broker_server": "Pepperstone-Demo", "files": files,
        "quality_audit": {"file": "quality_audit.json", "sha256": file_digest(root / "quality_audit.json")}}
    (root / "collection_spec.json").write_text(json.dumps(spec))
    return spec


def test_bundle_verified_api_and_chart_sources_without_rewriting_originals(tmp_path):
    from quant.broker_data import BUNDLE_SOURCE, bundle_sources

    src, old, prep, same, dest = [tmp_path / name for name in ("inbox", "old", "prep", "same", "combined")]
    _exports(src)
    import_exports(src, old, ["EURUSD"])
    _h1_exports(src, old)
    import_h1_exports(src, old, ["EURUSD"])
    _api_collection(prep)
    _api_collection(same)  # Identical overlap is not duplicated or averaged.
    originals = {p: p.read_bytes() for root in (old, prep, same) for p in root.rglob("*") if p.is_file()}
    manifest = bundle_sources([prep, same, old], dest)
    assert manifest["source_type"] == BUNDLE_SOURCE
    assert all(path.read_bytes() == content for path, content in originals.items())
    assert manifest["symbols"]["EURUSD"]["H1"]["identical_overlap_bars"] == 1
    assert len(pd.read_csv(chart_path(dest, "EURUSD", "H1"))) == 49
    assert not (dest / "manifest_h1.json").exists()
    identity = dataset_info(dest, "H4", "H1")
    assert identity["h1_manifest_sha256"] == identity["manifest_sha256"]
    assert "source gap retained" in identity["coverage_warnings"]
    assert len(closed_converter(dest, "EURUSD", "H1")) == 48
    (dest / "EURUSD_H1.csv").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        chart_path(dest, "EURUSD", "H1")


@pytest.mark.parametrize("problem", ["price", "volume", "metadata", "audit", "unverified", "traversal"])
def test_bundle_refuses_conflicts_and_unverified_sources_without_publication(tmp_path, problem):
    from quant.broker_data import bundle_sources
    from quant.mkdata import file_digest

    left, right, dest = [tmp_path / name for name in ("left", "right", "combined")]
    _api_collection(left)
    spec = _api_collection(right, price=1.2 if problem == "price" else 1.1)
    if problem == "volume":
        path = right / "EURUSD_H1.csv"
        frame = pd.read_csv(path)
        frame["tick_volume"] = 11
        frame.to_csv(path, index=False)
        spec["files"][path.name]["sha256"] = file_digest(path)
    if problem == "metadata":
        (right / "EURUSD_H1.meta.json").write_text("tampered")
    if problem == "audit":
        (right / "quality_audit.json").write_text("tampered")
    if problem == "unverified":
        spec["status"] = "collection_started_not_validated"
    if problem == "traversal":
        spec["quality_audit"]["file"] = "../left/quality_audit.json"
    (right / "collection_spec.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        bundle_sources([left, right], dest)
    assert not dest.exists() and (left / "EURUSD_H1.csv").exists()


def test_bundle_cli_is_offline_and_refuses_overwrite(tmp_path, monkeypatch):
    import sys
    from quant.mkdata import main

    src, dest = tmp_path / "source", tmp_path / "combined"
    _api_collection(src)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    assert main(["--bundle-broker", str(src), "--out-dir", str(dest)]) == 0
    before = (dest / "manifest.json").read_bytes()
    assert main(["--bundle-broker", str(src), "--out-dir", str(dest)]) == 2
    assert (dest / "manifest.json").read_bytes() == before


def test_evaluation_window_has_full_trade_parity_with_dice_real_path(tmp_path, monkeypatch):
    from quant.backtest import read_evaluation_window
    src, dest = tmp_path / "inbox", tmp_path / "broker"
    _exports(src, days=80)
    import_exports(src, dest, ["EURUSD"])
    _h1_exports(src, dest)
    import_h1_exports(src, dest, ["EURUSD"])
    tape = dest / "EURUSD_H4.csv"
    frame = backtest.load_h1(tape)
    window = read_evaluation_window({"backtest_evaluation": {"enabled": True,
        "start": str(frame.time.iloc[450]), "end": str(frame.time.iloc[474])}})
    setup = _setup(exec_hours=4, reg_hours=24, broker_data_dir=str(dest), position_checks="H1",
                   default_lot=.01, stop_sizing={}, evaluation_window=window)
    setup["strategy"].update(warmup_bars=10, bias_ema_fast_period=2, bias_ema_slow_period=5,
        use_atr_sep=False, use_e1_setup=False, use_e1_trigger=False, use_hr2=False,
        use_hr3=False, use_hr4=False, use_ext=False, use_w1=False)
    monkeypatch.setattr(dp, "_STATE", {})
    args = SimpleNamespace(exec_hours=4, reg_hours=24, broker_data_dir=str(dest), position_checks="H1",
        risk_usd=3., max_cost_ratio=.1, lot=None, default_lot=.01, evaluation_window=window)
    result = backtest.run_pair("EURUSD", tape, setup["strategy"], _zero_costs(), args)
    _, actual, _ = dp._real_one("EURUSD", str(tape), _zero_costs(), setup)
    assert len(actual) > 0
    pd.testing.assert_frame_equal(result["trades"], actual)
    assert result["n_bars"] == 24
    assert (pd.to_datetime(actual.entry_time, utc=True) >= pd.Timestamp(window["start"])).all()
    assert (pd.to_datetime(actual.exit_time, utc=True) <= pd.Timestamp(window["end"])).all()


def test_verified_bundle_report_loads_exact_charts_without_h1_extension(tmp_path, monkeypatch):
    from quant import report
    from quant.broker_data import bundle_sources
    from tests.test_report import _blob, _trade_row

    src, imported, bundled, run = [tmp_path / n for n in ("inbox", "imported", "bundle", "run")]
    _exports(src, days=30)
    import_exports(src, imported, ["EURUSD"])
    _h1_exports(src, imported)
    import_h1_exports(src, imported, ["EURUSD"])
    bundle_sources([imported], bundled)
    run.mkdir()
    times = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(bundled / "EURUSD_H4.csv").time, utc=True))
    pd.DataFrame([_trade_row("EURUSD", 100, 120, "LONG", 2., times)]).to_csv(run / "trades_EURUSD.csv", index=False)
    pd.DataFrame([{"symbol": "TOTAL", "trades": 1, "net_usd": 6., "net_R": 2.}]).to_csv(run / "summary.csv", index=False)
    (run / "params.json").write_text(json.dumps({"broker_data": dataset_info(bundled, "H4", "H1"),
        "timeframes": {"execution": "H4", "regime": "D1"}}))
    monkeypatch.setattr(report, "_tf_bars", lambda *a: pytest.fail("must not resample broker bundle"))
    assert report.write_report(run, tmp_path / "no_vendor")
    payload = _blob((run / "report.html").read_text(encoding="utf-8"), "trades-json")
    assert not payload["meta"][0]["missing"]
    assert "raw" not in payload["embedded"]["EURUSD-0"]
