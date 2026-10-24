"""mkdata tests. Synthetic M1 only, never data/."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from quant.mkdata import (broker_plan, coverage, export_broker, load_m1, main,
                          to_h1, validate_broker_rates, write_m1)


def _m1_rows(date="2020.01.06"):
    rows = []
    for h in (10, 11):
        for m in range(60):
            c = 1.1000 + h * 0.0010 + m * 0.00001
            rows.append(f"{date},{h:02d}:{m:02d},{c - 0.0001:.5f},{c + 0.0001:.5f},"
                        f"{c - 0.0002:.5f},{c:.5f},7")
    return rows


def _m1_rows_for(year):
    return _m1_rows(f"{year}.01.06")


def test_h1_aggregation(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "DAT_MT_TST_M1_2020.csv").write_text("\n".join(_m1_rows()) + "\n", encoding="utf-8")
    m1 = load_m1(d, "TST")
    assert len(m1) == 120
    h1 = to_h1(m1)
    assert len(h1) == 2
    assert list(h1["time"].dt.strftime("%H:%M")) == ["10:00", "11:00"]
    assert h1["open"].iloc[0] == m1["open"].iloc[0]
    assert h1["close"].iloc[0] == m1["close"].iloc[59]
    assert h1["high"].iloc[0] == m1["high"].iloc[:60].max()
    assert h1["tick_volume"].iloc[0] == 7 * 60
    assert list(h1["n_minutes"]) == [60, 60]


def test_coverage_and_missing_symbol(tmp_path):
    import zipfile

    d = tmp_path / "data"
    d.mkdir()
    (d / "DAT_MT_TST_M1_2020.csv").write_text("\n".join(_m1_rows()) + "\n", encoding="utf-8")
    cov = coverage(load_m1(d, "TST"), to_h1(load_m1(d, "TST")))
    assert cov["year"].iloc[0] == 2020 and cov["short_hours"].iloc[0] == 0
    try:
        load_m1(d, "NOPE")
        raise SystemExit("should have raised")
    except FileNotFoundError:
        pass
    with zipfile.ZipFile(d / "HISTDATA_COM_MT_ZIP_M12021.zip", "w") as zf:
        zf.writestr("DAT_MT_ZIP_M1_2021.csv", "\n".join(_m1_rows_for(2021)) + "\n")
    m1 = load_m1(d, "ZIP")
    assert len(m1) == 120 and int(m1["time"].dt.year.unique()[0]) == 2021


def test_write_m1_csv_roundtrip(tmp_path):
    from quant.backtest import load_h1

    d = tmp_path / "data"
    d.mkdir()
    (d / "DAT_MT_TST_M1_2020.csv").write_text("\n".join(_m1_rows()) + "\n", encoding="utf-8")
    m1 = load_m1(d, "TST")
    out = write_m1(m1, d / "TST_M1.csv")
    back = load_h1(out)
    assert len(back) == 120
    assert list(back.columns[:5]) == ["time", "open", "high", "low", "close"]
    assert float(back["close"].iloc[59]) == float(m1["close"].iloc[59])  # 10:59 close preserved


def _configs(tmp_path, *, execution="H4", regime="D1", checks="M1"):
    import yaml

    root = tmp_path / "configs"
    root.mkdir()
    base = {"timeframes": {"execution": execution, "regime": regime,
                            "position_checks": checks},
            "strategy": {"bias": {"warmup_bars": 2}},
            "account": {"currency": "USD"}}
    (root / "_base.yaml").write_text(yaml.safe_dump(base), encoding="utf-8")
    for symbol in ("EURUSD", "EURJPY", "GBPUSD"):
        (root / f"{symbol}.yaml").write_text(f"symbol: {symbol}\n", encoding="utf-8")
    (root / "scan-selection.yml").write_text(
        "pairs:\n  EURUSD: {enabled: true}\n  EURJPY: {enabled: true}\n"
        "  GBPUSD: {enabled: false}\n", encoding="utf-8")
    return root


def _rate(ts, **override):
    row = dict(time=int(pd.Timestamp(ts).timestamp()), open=1.1, high=1.2,
               low=1.0, close=1.15, tick_volume=10)
    row.update(override)
    return row


class _Broker:
    TIMEFRAME_M1, TIMEFRAME_H1, TIMEFRAME_H2, TIMEFRAME_H4, TIMEFRAME_D1 = range(5)

    def __init__(self):
        self.initializations = 0
        self.shutdowns = 0
        self.selected = []
        self.range_calls = []
        self.init_ok = True
        self.rates = {tf: [_rate(t) for t in pd.date_range(
            "2020-01-01", "2020-01-10", freq=freq, tz="UTC")]
                      for tf, freq in enumerate(("min", "h", "2h", "4h", "D"))}

    def initialize(self):
        self.initializations += 1
        return self.init_ok

    def shutdown(self):
        self.shutdowns += 1

    def account_info(self):
        return SimpleNamespace(server="Test-Broker", login="MUST NOT BE RECORDED")

    def symbol_info(self, symbol):
        return SimpleNamespace() if symbol.endswith(".pro") else None

    def symbol_select(self, symbol, selected):
        self.selected.append(symbol)
        return True

    def copy_rates_from_pos(self, symbol, tf, pos, count):
        assert pos == 1  # Last candle is forming: never export it as closed.
        return self.rates[tf][-2:-1]

    def copy_rates_from(self, symbol, tf, at, count):
        return [r for r in self.rates[tf] if r["time"] <= at.timestamp()][-count:]

    def copy_rates_range(self, symbol, tf, start, end):
        self.range_calls.append((symbol, tf, start, end))
        return [r for r in self.rates[tf] if start.timestamp() <= r["time"] <= end.timestamp()]


def _dates():
    return (datetime(2020, 1, 4, tzinfo=timezone.utc),
            datetime(2020, 1, 6, tzinfo=timezone.utc))


def test_broker_plan_selection_timeframes_and_conversion(tmp_path):
    plan = broker_plan(_configs(tmp_path), None, True)
    assert plan["symbols"] == ["EURJPY", "EURUSD"]
    assert plan["warmup_bars"] == 2
    assert ("USDJPY", "H1") in plan["jobs"]
    assert ("EURUSD", "M1") in plan["jobs"]
    assert ("EURUSD", "H4") in plan["jobs"]
    assert ("EURUSD", "D1") in plan["jobs"]
    assert not any(s == "GBPUSD" for s, _ in plan["jobs"])


@pytest.mark.parametrize("enabled", [True, False])
def test_broker_plan_respects_effective_position_checks(tmp_path, enabled):
    import yaml

    root = _configs(tmp_path)
    path = root / "_base.yaml"
    base = yaml.safe_load(path.read_text(encoding="utf-8"))
    base["backtest_data"] = {"use_broker_csv": enabled, "position_checks": "H1"}
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    plan = broker_plan(root, None, True)
    assert plan["position_checks"] == ("H1" if enabled else "M1")
    assert (("EURUSD", "M1") in plan["jobs"]) is not enabled
    assert {("EURUSD", tf) for tf in ("H1", "H4", "D1")} <= set(plan["jobs"])
    assert ("USDJPY", "H1") in plan["jobs"]


def test_exporter_accepts_chart_combos_beyond_engine_without_resampling(tmp_path):
    plan = broker_plan(_configs(tmp_path, execution="H2", regime="W1", checks="H2"),
                       "EURUSD", False, 0)
    assert plan["jobs"] == [("EURUSD", "H1"), ("EURUSD", "H2"), ("EURUSD", "W1")]
    assert plan["warmup_bars"] == 0


def test_broker_export_closed_bars_metadata_warmup_and_chunks(tmp_path):
    plan = broker_plan(_configs(tmp_path), "EURUSD", False)
    broker = _Broker()
    output = tmp_path / "export"
    files = export_broker(broker, plan, *_dates(), output, chunk_days=1)
    assert len(files) == 8
    assert broker.shutdowns == 1
    assert broker.selected == ["EURUSD.pro"]
    df = pd.read_csv(output / "EURUSD_D1.csv")
    assert len(df) == 5  # Jan 1-3 prefix + Jan 4-5 requested window.
    assert pd.to_datetime(df["time"], utc=True).max() < pd.Timestamp("2020-01-06", tz="UTC")
    meta_text = (output / "EURUSD_D1.meta.json").read_text(encoding="utf-8")
    meta = json.loads(meta_text)
    assert meta["broker_server"] == "Test-Broker"
    assert meta["broker_symbol"] == "EURUSD.pro"
    assert "login" not in meta_text and "MUST NOT BE RECORDED" not in meta_text
    assert meta["warmup_bars"] == 2
    assert meta["gap_count"] == 0
    assert meta["export_start_with_warmup_utc"].startswith("2020-01-01")
    assert all((end - start).total_seconds() <= 86400 for _, _, start, end in broker.range_calls)


def test_broker_current_candle_excluded_even_if_requested_end_is_later(tmp_path):
    plan = broker_plan(_configs(tmp_path, checks="H4"), "EURUSD", False, 0)
    start, _ = _dates()
    output = tmp_path / "export"
    export_broker(_Broker(), plan, start, datetime(2020, 1, 12, tzinfo=timezone.utc), output)
    df = pd.read_csv(output / "EURUSD_D1.csv")
    assert pd.to_datetime(df["time"], utc=True).max() == pd.Timestamp("2020-01-09", tz="UTC")


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r + r, "duplicate"),
    (lambda r: r[::-1], "descending"),
    (lambda r: [dict(r[0], high=0.5)], "invalid prices"),
    (lambda r: [dict(r[0], close=float("nan"))], "non-finite"),
    (lambda r: [dict(r[0], tick_volume=-1)], "invalid prices"),
])
def test_bad_broker_candles_rejected(mutation, match):
    rows = [_rate("2020-01-01"), _rate("2020-01-02")]
    with pytest.raises(ValueError, match=match):
        validate_broker_rates(mutation(rows), "fake")


def test_gap_report_includes_internal_and_cross_chunk_gaps(tmp_path):
    plan = broker_plan(_configs(tmp_path, checks="H4"), "EURUSD", False, 0)
    broker = _Broker()
    broker.rates[broker.TIMEFRAME_H4] = [r for r in broker.rates[broker.TIMEFRAME_H4]
        if r["time"] not in {int(pd.Timestamp(t, tz="UTC").timestamp())
                             for t in ("2020-01-04 08:00", "2020-01-05 00:00")}]
    output = tmp_path / "export"
    export_broker(broker, plan, *_dates(), output, chunk_days=1)
    meta = json.loads((output / "EURUSD_H4.meta.json").read_text())
    assert meta["gap_count"] == 2
    assert meta["bars"] == 10  # Original 12 candles, no gap filling.


def test_existing_data_refused_before_connection(tmp_path):
    plan = broker_plan(_configs(tmp_path), "EURUSD", False)
    (tmp_path / "EURUSD_H1.csv").write_text("user data", encoding="utf-8")
    broker = _Broker()
    with pytest.raises(FileExistsError, match="overwrite"):
        export_broker(broker, plan, *_dates(), tmp_path)
    assert broker.initializations == 0
    assert (tmp_path / "EURUSD_H1.csv").read_text() == "user data"


@pytest.mark.parametrize("problem", ["warmup", "history", "candles", "init", "missing_m1"])
def test_failed_export_publishes_no_csvs_and_shuts_down(tmp_path, problem):
    plan = broker_plan(_configs(tmp_path), "EURUSD", False)
    broker = _Broker()
    if problem == "warmup":
        broker.rates[broker.TIMEFRAME_D1] = broker.rates[broker.TIMEFRAME_D1][-2:]
    elif problem == "history":
        broker.copy_rates_range = lambda *args: None
    elif problem == "candles":
        broker.rates[broker.TIMEFRAME_H4][20]["high"] = 0.1
    elif problem == "init":
        broker.init_ok = False
    else:
        broker.rates[broker.TIMEFRAME_M1] = broker.rates[broker.TIMEFRAME_M1][-2:]
    output = tmp_path / "export"
    with pytest.raises(ValueError):
        export_broker(broker, plan, *_dates(), output)
    assert broker.shutdowns == 1
    assert not list(output.glob("*.csv"))
    assert not list(output.glob("*.meta.json"))


def test_plan_cli_never_connects_or_writes(tmp_path, capsys, monkeypatch):
    import sys

    root = _configs(tmp_path)
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)
    output = tmp_path / "output"
    assert main(["--broker", "--batch", "--config-dir", str(root), "--start", "2020-01-04",
                 "--end", "2020-01-06", "--out-dir", str(output), "--plan"]) == 0
    assert "USDJPY" in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize("symbol,batch", [(None, False), ("EURUSD", True), ("../EURUSD", False)])
def test_invalid_symbol_selection_rejected(tmp_path, symbol, batch):
    with pytest.raises(ValueError):
        broker_plan(_configs(tmp_path), symbol, batch)


def test_broker_timeframe_must_exist_in_bridge(tmp_path):
    plan = broker_plan(_configs(tmp_path, regime="W1"), "EURUSD", False, 0)
    broker = _Broker()
    with pytest.raises(ValueError, match="MT5 does not support W1"):
        export_broker(broker, plan, *_dates(), tmp_path / "output")
    assert broker.shutdowns == 1


def test_explicit_overwrite_requires_successful_validation_first(tmp_path):
    plan = broker_plan(_configs(tmp_path), "EURUSD", False)
    output = tmp_path / "export"
    output.mkdir()
    target = output / "EURUSD_H1.csv"
    target.write_text("original", encoding="utf-8")
    broker = _Broker()
    broker.copy_rates_range = lambda *args: None
    with pytest.raises(ValueError):
        export_broker(broker, plan, *_dates(), output, overwrite=True)
    assert target.read_text() == "original"
    export_broker(_Broker(), plan, *_dates(), output, overwrite=True)
    assert "open,high,low,close" in target.read_text()


def test_monthly_gaps_use_calendar_months_and_are_not_filled(tmp_path):
    from quant.mkdata import _stream_broker_csv

    broker = _Broker()
    broker.TIMEFRAME_MN1 = 5
    broker.rates[5] = [_rate(t) for t in ("2020-01-01", "2020-02-01", "2020-04-01", "2020-05-01")]
    result = _stream_broker_csv(
        broker, "EURUSD.pro", "MN1", datetime(2020, 1, 1, tzinfo=timezone.utc),
        datetime(2020, 5, 1, tzinfo=timezone.utc), pd.Timestamp("2020-05-01", tz="UTC"),
        tmp_path / "monthly.csv", 31)
    assert result["bars"] == 3
    assert result["gap_count"] == 1
    assert result["gap_samples"][0]["after"].startswith("2020-02-01")


def test_broker_none_and_empty_are_distinct():
    with pytest.raises(ValueError, match="no data"):
        validate_broker_rates(None, "fake")
    assert validate_broker_rates([], "fake").empty


def test_existing_vendor_cli_still_builds_from_synthetic_minutes(tmp_path):
    (tmp_path / "DAT_MT_TST_M1_2020.csv").write_text(
        "\n".join(_m1_rows()) + "\n", encoding="utf-8")
    target = tmp_path / "built.csv"
    assert main(["--symbol", "TST", "--src", str(tmp_path), "--out", str(target)]) == 0
    assert len(pd.read_csv(target)) == 2


def test_unknown_timeframe_and_bad_selection_fail_loudly(tmp_path):
    root = _configs(tmp_path, execution="H99")
    with pytest.raises(ValueError, match="unsupported broker timeframe"):
        broker_plan(root, "EURUSD", False)
    (root / "_base.yaml").write_text("timeframes: {execution: H1, regime: H4}\n", encoding="utf-8")
    (root / "scan-selection.yml").write_text("pairs: {EURUSD: {enabled: 'false'}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="enabled values"):
        broker_plan(root, None, True)


@pytest.mark.parametrize("server,utc", [
    ("2020-01-02 00:00Z", "2020-01-01 22:00Z"),
    ("2020-03-09 00:00Z", "2020-03-08 21:00Z"),
    ("2020-10-26 00:00Z", "2020-10-25 21:00Z"),
    ("2020-11-02 00:00Z", "2020-11-01 22:00Z")])
def test_api_clock_roundtrip_preserves_ohlc_and_uses_us_dst(server, utc):
    from quant.mkdata import broker_query_date

    row = _rate(server)
    converted = validate_broker_rates([row], "fake", "new_york_plus_7")
    assert converted.time.iloc[0] == pd.Timestamp(utc)
    assert int(broker_query_date(pd.Timestamp(utc), "new_york_plus_7").timestamp()) == row["time"]
    for column in ("open", "high", "low", "close", "tick_volume"):
        assert converted[column].iloc[0] == row[column]


def test_pepperstone_export_normalizes_queries_warmup_closure_and_metadata(tmp_path):
    plan = broker_plan(_configs(tmp_path, checks="H4"), "EURUSD", False)
    broker = _Broker()
    broker.account_info = lambda: SimpleNamespace(server="Pepperstone-Demo")
    out = tmp_path / "export"
    export_broker(broker, plan, *_dates(), out, chunk_days=1)
    frame = pd.read_csv(out / "EURUSD_D1.csv")
    stamps = pd.to_datetime(frame.time, utc=True)
    assert stamps.iloc[0] == pd.Timestamp("2020-01-01 22:00Z")
    assert stamps.iloc[-1] == pd.Timestamp("2020-01-05 22:00Z")
    meta = json.loads((out / "EURUSD_D1.meta.json").read_text())
    assert meta["broker_api_clock"] == "new_york_plus_7"
    assert meta["requested_start_utc"] == _dates()[0].isoformat()
    assert meta["api_query_start_label"].startswith("2020-01-02T00:00")
    assert meta["api_query_end_exclusive_label"].startswith("2020-01-06T02:00")
    assert meta["last_closed_open_utc"].startswith("2020-01-08T22:00")
    assert broker.shutdowns == 1


def test_explicit_utc_override_does_not_double_convert_pepperstone(tmp_path):
    plan = broker_plan(_configs(tmp_path, checks="H4"), "EURUSD", False, 0)
    plan["api_clock"] = "utc"
    broker = _Broker()
    broker.account_info = lambda: SimpleNamespace(server="Pepperstone-Demo")
    out = tmp_path / "export"
    export_broker(broker, plan, *_dates(), out)
    assert pd.read_csv(out / "EURUSD_D1.csv").time.iloc[0].startswith("2020-01-04 00:00")


def test_bad_api_clock_rejected_with_shutdown(tmp_path):
    plan = broker_plan(_configs(tmp_path), "EURUSD", False)
    plan["api_clock"] = "fixed_offset_guess"
    broker = _Broker()
    with pytest.raises(ValueError, match="clock"):
        export_broker(broker, plan, *_dates(), tmp_path / "bad")
    assert broker.shutdowns == 1 and not (tmp_path / "bad").exists()


def test_api_stream_keeps_actual_utc_bounds_across_us_dst_weekend(tmp_path):
    from quant.mkdata import _stream_broker_csv
    broker = _Broker()
    broker.rates[broker.TIMEFRAME_H1] = [_rate(stamp) for stamp in (
        "2020-03-06 23:00Z", "2020-03-09 00:00Z", "2020-03-09 01:00Z")]
    path = tmp_path / "dst.csv"
    result = _stream_broker_csv(broker, "EURUSD.pro", "H1",
        datetime(2020, 3, 6, 20, tzinfo=timezone.utc), datetime(2020, 3, 9, tzinfo=timezone.utc),
        pd.Timestamp("2020-03-09 23:00Z"), path, 1, "new_york_plus_7")
    times = pd.to_datetime(pd.read_csv(path).time, utc=True)
    assert result["bars"] == 3
    assert list(times.dt.strftime("%Y-%m-%d %H:%M")) == [
        "2020-03-06 21:00", "2020-03-08 21:00", "2020-03-08 22:00"]
    assert broker.range_calls[0][2] == datetime(2020, 3, 6, 22, tzinfo=timezone.utc)
    assert broker.range_calls[-1][3].hour == 2  # Exclusive UTC midnight maps to server 03:00 minus one microsecond.
