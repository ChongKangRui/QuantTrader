"""Panel tests. No terminal, no real MT5 import."""
import numpy as np

from quant.monitor import (PairRow, load_pairs, poll, read_limits, read_selection,
                           read_timeframes, render_panel, should_rewrite)


def _rows():
    return [
        PairRow(symbol="EURUSD", ok=True, bias="UP"),
        PairRow(symbol="USDJPY", ok=True, bias="FLAT", has_position=True),
    ]


def test_two_column_layout_without_indicator_detail():
    txt = render_panel(_rows(), "2026-10-16 18:05:12", "2026-10-16 10:00", "DEMO")
    assert "EURUSD" in txt and "UP" in txt
    assert "NONE DETECTED" not in txt
    for dropped in ("EMA20", "EMA50", "SEP", "H1_UTC", "H4_UTC", "INFO"):
        assert dropped not in txt


def test_header_rows_show_local_and_broker_time():
    txt = render_panel(_rows(), "2026-10-16 18:05:12", "2026-10-16 10:00", "DEMO")
    assert "local time : 2026-10-16 18:05:12" in txt
    assert "broker time: 2026-10-16 10:00" in txt
    assert "account=DEMO" in txt


def test_position_star_and_legend():
    txt = render_panel(_rows(), "t", "b", "DEMO")
    assert "USDJPY  FLAT*  -" in txt
    assert "* = open position" in txt


def test_entry_column_header():
    txt = render_panel(_rows(), "t", "b", "DEMO")
    assert "ENTRY" in txt


def test_week_lines_and_halt_banner():
    weeks = {"DEMO": {"week": "2026-W42", "halted": False, "loss_pct": -2.5,
                      "start_equity": 100.0, "realized": -2.5}}
    txt = render_panel(_rows(), "t", "b", "DEMO", weeks=weeks, loss_pct=15.0)
    assert "week DEMO: -2.50%" in txt and "HALTED" not in txt
    weeks["DEMO"]["halted"] = True
    weeks["DEMO"]["loss_pct"] = 16.2
    txt = render_panel(_rows(), "t", "b", "DEMO", weeks=weeks, loss_pct=15.0)
    assert "HALTED (DEMO)" in txt


def test_all_flat_shows_none_detected():
    rows = [PairRow(symbol="EURUSD", ok=True, bias="FLAT")]
    txt = render_panel(rows, "t", "b", "DEMO")
    assert "NONE DETECTED" in txt


def test_error_row_shows_data_error():
    rows = [PairRow(symbol="EURUSD", ok=False, note="no closed-bar data")]
    txt = render_panel(rows, "t", "b", "DEMO")
    assert "DATA ERROR" in txt and "EURUSD" in txt


def test_should_rewrite_only_on_new_bar():
    assert should_rewrite(True, None, {}) is True
    assert should_rewrite(False, {"EURUSD": 5}, {"EURUSD": 5}) is False
    assert should_rewrite(False, {"EURUSD": 5}, {"EURUSD": 6}) is True


def test_load_pairs_tolerates_bad_encoding_and_bad_yaml(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {hr1: c}\n", encoding="utf-8")
    (d / "good.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    (d / "latin.yaml").write_bytes("symbol: USDJPY\n# caf\xe9 comment\n".encode("latin-1"))
    (d / "broken.yaml").write_text(":\n: not yaml\n", encoding="utf-8")
    pairs = load_pairs(d)
    by_name = {p["name"]: p for p in pairs}
    assert by_name["good"]["symbol"] == "EURUSD" and by_name["good"]["hr1"] == "c"
    assert by_name["latin"]["symbol"] == "USDJPY"  # cp1252 fallback, no raise
    assert "load_error" in by_name["broken"]  # one bad file, rest survive


def test_load_pairs_defaults_hr1_to_a(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {hr1: zzz}\n", encoding="utf-8")
    (d / "x.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    assert load_pairs(d)[0]["hr1"] == "a"


def test_load_pairs_strategy_comes_only_from_base(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {use_atr_sep: true, hr1: b}\n", encoding="utf-8")
    (d / "a.yaml").write_text(
        "symbol: EURUSD\nstrategy: {use_atr_sep: false, hr1: c}\n", encoding="utf-8")
    p = load_pairs(d)[0]
    assert (p["use_atr_sep"], p["hr1"]) == (True, "b")  # pair key ignored
    assert p["params"]["hr1"] == "b"


def test_load_pairs_carries_pair_costs(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {hr1: b}\n", encoding="utf-8")
    (d / "a.yaml").write_text(
        "symbol: EURUSD\ncosts: {spread_points: 2, swap_long_per_0_01: -0.072}\n",
        encoding="utf-8")
    (d / "b.yaml").write_text(":\n: not yaml\n", encoding="utf-8")
    pairs = load_pairs(d)
    good = [p for p in pairs if not p.get("load_error")][0]
    assert good["costs"]["spread_points"] == 2   # live spreadcheck calibration
    bad = [p for p in pairs if p.get("load_error")][0]
    assert bad["costs"] == {}                    # error path still exposes the key


def test_load_pairs_skips_base_and_scan_selection(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {hr1: a}\n", encoding="utf-8")
    (d / "scan-selection.yml").write_text("pairs: {EURUSD: {enabled: true}}\n", encoding="utf-8")
    (d / "OLD_untrade.yaml").write_text("symbol: OLD\n", encoding="utf-8")
    (d / "a.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    assert [p["name"] for p in load_pairs(d)] == ["a"]


def test_read_selection_mapping_and_missing_file(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "scan-selection.yml").write_text(
        "pairs:\n  EURUSD: {enabled: true}\n  GBPUSD: {enabled: false}\n", encoding="utf-8")
    assert read_selection(d) == {"EURUSD": True, "GBPUSD": False}
    assert read_selection(d / "nodir") is None


def test_read_limits_from_base_with_default(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("limits: {weekly_loss_pct: 20}\n", encoding="utf-8")
    assert read_limits(d) == 20.0
    assert read_limits(d / "nodir") == 15.0


def test_read_timeframes_default_and_upscale(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("timeframes: {position_checks: M1}\n", encoding="utf-8")
    assert read_timeframes(d) == ("H1", "H4")          # missing keys = default pair
    (d / "_base.yaml").write_text(
        "timeframes: {execution: H4, regime: D1}\n", encoding="utf-8")
    assert read_timeframes(d) == ("H4", "D1")           # the allowed upscale
    assert read_timeframes(d / "nodir") == ("H1", "H4")  # no file = default pair


def test_read_timeframes_rejects_unknown_and_unlocked(tmp_path):
    import pytest

    d = tmp_path / "configs"
    d.mkdir()
    for yml in ("timeframes: {execution: H1, regime: D1}\n",   # un-locked combo
                "timeframes: {execution: H4, regime: H4}\n",   # regime == execution
                "timeframes: {execution: W1, regime: D1}\n"):  # unknown TF
        (d / "_base.yaml").write_text(yml, encoding="utf-8")
        with pytest.raises(ValueError):
            read_timeframes(d)


def test_poll_resolves_tf_names_via_getattr():
    # exec/reg TFs are mt5 ATTRIBUTE names, resolved on the (mock) mt5 module
    class _Rec:
        TIMEFRAME_H1 = 11
        TIMEFRAME_H4 = 12
        TIMEFRAME_D1 = 13

        def __init__(self):
            self.used = []

        def symbol_info(self, symbol):
            return object()

        def symbol_select(self, symbol, flag):
            return True

        def positions_get(self, symbol=None):
            return []

        def copy_rates_from_pos(self, symbol, tf, start, n):
            self.used.append(tf)
            return None  # poll reports "no closed-bar data"; the codes are the point

    mt5 = _Rec()
    poll(mt5, [{"name": "EURUSD", "symbol": "EURUSD"}],
         exec_tf="TIMEFRAME_H1", reg_tf="TIMEFRAME_D1")
    assert mt5.used == [11, 13]


def test_render_shows_ma_only_mode():
    txt = render_panel(_rows(), "t", "b", "DEMO", mode="MA-only")
    assert txt.startswith("QuantTrader H4 bias panel (H4 MA-only, bias only)")


def test_mode_reflects_base_switch(tmp_path):
    from quant.monitor import _mode

    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy: {use_atr_sep: false}\n", encoding="utf-8")
    (d / "a.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    assert _mode(load_pairs(d)) == "MA-only"


class _FakeMT5:
    TIMEFRAME_H1 = 1
    TIMEFRAME_H4 = 2

    def __init__(self, closes, positions=()):
        self.closes = closes
        self._positions = positions

    def symbol_info(self, symbol):
        return object() if symbol == "EURUSD" else None

    def symbol_select(self, symbol, flag):
        return True

    def positions_get(self, symbol=None):
        return self._positions

    def copy_rates_from_pos(self, symbol, tf, start, n):
        closes = self.closes[-n:]
        t0 = 1_700_000_000
        step = 3600 if tf == 1 else 14_400
        rows = [(t0 + i * step, c - 0.3, c + 0.3, c - 0.3, c, 1, 0, 0)
                for i, c in enumerate(closes)]
        return np.array(rows, dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"),
                                     ("low", "f8"), ("close", "f8"), ("tick_volume", "i8"),
                                     ("spread", "i4"), ("real_volume", "i8")])


def test_poll_maps_long_bias_to_up():
    mt5 = _FakeMT5([100.0 + i * 1.0 for i in range(400)])
    rows, times = poll(mt5, [{"name": "EURUSD", "symbol": "EURUSD", "sep": 0.3, "hr1": "a"}])
    assert rows[0].ok and rows[0].bias == "UP"
    assert rows[0].entry == "HR4"  # monotonic rise forms no pivot low
    assert times["EURUSD"] > 0


def test_poll_unknown_symbol_is_error_row():
    mt5 = _FakeMT5([100.0] * 150)
    rows, _ = poll(mt5, [{"name": "X", "symbol": "NOPE", "sep": 0.3, "hr1": "a"}])
    assert not rows[0].ok and "not found" in rows[0].note


def test_poll_ma_only_never_flat_on_pullback():
    import pandas as pd

    closes = [100.0 + i * 1.0 for i in range(399)]
    e50 = float(pd.Series(closes).ewm(span=50, adjust=False).mean().iloc[-1])
    closes.append(e50 - 30.0)  # under EMA50 (HR1a veto) but stack still up
    mt5 = _FakeMT5(closes)
    base = {"name": "EURUSD", "symbol": "EURUSD", "sep": 0.3, "hr1": "a"}
    rows, _ = poll(mt5, [dict(base, use_atr_sep=True)])
    assert rows[0].bias == "FLAT"
    rows, _ = poll(mt5, [dict(base, use_atr_sep=False)])
    assert rows[0].bias == "UP"


def test_flatten_strategy_reads_sections_and_flat():
    from quant.monitor import flatten_strategy

    nested = flatten_strategy({"strategy": {"bias": {"hr1": "b"}, "entry": {"atr_n": 7}}})
    assert nested == {"hr1": "b", "atr_n": 7}
    assert flatten_strategy({"strategy": {"hr1": "a"}}) == {"hr1": "a"}


def test_load_pairs_reads_nested_base(tmp_path):
    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text("strategy:\n  bias: {use_atr_sep: false, hr1: b}\n",
                                  encoding="utf-8")
    (d / "a.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    p = load_pairs(d)[0]
    assert p["hr1"] == "b" and p["use_atr_sep"] is False
