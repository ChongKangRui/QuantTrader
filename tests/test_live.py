"""Live executor tests. Fake MT5 only, never a terminal, never orders."""
import csv
from types import SimpleNamespace

import pytest

from quant.live import build_request, pick_filling, roundtrip, snap_volume, touch_close


class _FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_FILLING_IOC = 2
    ORDER_FILLING_FOK = 1
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009

    def __init__(self, filling_mode=2, fail_open=False, fail_close=False,
                 tick_none_second=False, stops_level=5, hide_after=None):
        self.filling_mode = filling_mode
        self.fail_open = fail_open
        self.fail_close = fail_close
        self.tick_none_second = tick_none_second
        self.stops_level = stops_level
        self.hide_after = dict(hide_after or {})  # ticket -> polls left visible
        self.sent = []
        self._positions = []
        self._history = []
        self._next = 100
        self._ticks = 0

    def symbol_info(self, symbol):
        return SimpleNamespace(filling_mode=self.filling_mode, volume_min=0.01,
                               volume_max=100.0, volume_step=0.01, digits=5,
                               point=0.00001, trade_stops_level=self.stops_level)

    def symbol_select(self, symbol, flag):
        return True

    def symbol_info_tick(self, symbol):
        self._ticks += 1
        if self.tick_none_second and self._ticks >= 2:
            return None
        return SimpleNamespace(ask=1.1000, bid=1.0999, time=1_700_000_000)

    def positions_get(self, symbol=None):
        out = []
        for p in self._positions:
            left = self.hide_after.get(p.ticket)
            if left is None:
                out.append(p)
            elif left > 0:
                self.hide_after[p.ticket] = left - 1
                out.append(p)
            else:
                self._history.append(SimpleNamespace(  # broker closed it (TP win)
                    ticket=999, position_id=p.ticket, entry=1, type=1, price=1.1010,
                    volume=p.volume, profit=1.0, commission=0.0, swap=0.0,
                    magic=p.magic, symbol=p.symbol, time=1_700_000_100))
        return tuple(out)

    def history_deals_get(self, date_from, date_to):
        return tuple(self._history)

    def last_error(self):
        return (0, "ok")

    def order_send(self, req):
        self.sent.append(req)
        if req.get("position_id") is None:
            if self.fail_open:
                return SimpleNamespace(retcode=10027, deal=0, order=0, price=0.0)
            pos = SimpleNamespace(ticket=self._next, magic=req["magic"],
                                   symbol=req["symbol"], volume=req["volume"], type=0)
            self._next += 1
            self._positions.append(pos)
            return SimpleNamespace(retcode=10009, deal=55, order=56, price=req["price"])
        if self.fail_close:
            return SimpleNamespace(retcode=10027, deal=0, order=0, price=0.0)
        self._positions = [p for p in self._positions if p.ticket != req["position_id"]]
        return SimpleNamespace(retcode=10009, deal=57, order=58, price=req["price"])


def _journal_rows(p):
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_dry_run_sends_nothing(tmp_path):
    mt5 = _FakeMT5()
    j = tmp_path / "journal.csv"
    rc = roundtrip(mt5, symbol="EURUSD", side="BUY", volume=0.01,
                   magic=100001, dry_run=True, journal_path=j)
    assert rc == 0 and mt5.sent == []
    rows = _journal_rows(j)
    assert len(rows) == 1 and rows[0]["dry_run"] == "True"


def test_real_roundtrip_opens_then_closes(tmp_path):
    mt5 = _FakeMT5()
    j = tmp_path / "journal.csv"
    rc = roundtrip(mt5, symbol="EURUSD", side="BUY", volume=0.01,
                   magic=100001, dry_run=False, journal_path=j)
    assert rc == 0
    assert len(mt5.sent) == 2
    assert mt5.sent[0]["type"] == _FakeMT5.ORDER_TYPE_BUY
    assert mt5.sent[1]["type"] == _FakeMT5.ORDER_TYPE_SELL
    assert mt5.sent[1]["position_id"] == 100
    assert mt5.positions_get() == ()
    rows = _journal_rows(j)
    assert len(rows) == 2 and all(r["dry_run"] == "False" for r in rows)
    assert "roundtrip-open" in rows[0]["reason"] and "roundtrip-close" in rows[1]["reason"]


def test_open_failure_sends_no_close(tmp_path):
    mt5 = _FakeMT5(fail_open=True)
    rc = roundtrip(mt5, symbol="EURUSD", side="BUY", volume=0.01,
                   magic=100001, dry_run=False, journal_path=tmp_path / "j.csv")
    assert rc == 1 and len(mt5.sent) == 1


def test_close_tick_missing_reports_position(tmp_path):
    mt5 = _FakeMT5(tick_none_second=True)
    rc = roundtrip(mt5, symbol="EURUSD", side="BUY", volume=0.01,
                   magic=100001, dry_run=False, journal_path=tmp_path / "j.csv")
    assert rc == 2 and len(mt5.positions_get()) == 1  # open stands: close manually


def test_fake_matches_real_mt5_api_surface():
    mt5 = pytest.importorskip("MetaTrader5")  # Windows-only wheel; skipped on CI/Linux
    for name in ("symbol_info_tick", "symbol_info", "symbol_select", "positions_get",
                 "order_send", "last_error", "initialize", "shutdown", "account_info",
                 "copy_rates_from_pos", "history_deals_get", "TRADE_ACTION_DEAL",
                 "ORDER_TYPE_BUY", "ORDER_TYPE_SELL", "ORDER_FILLING_IOC",
                 "ORDER_FILLING_FOK", "ORDER_TIME_GTC", "TRADE_RETCODE_DONE",
                 "TIMEFRAME_H1", "TIMEFRAME_H4"):
        assert hasattr(mt5, name), name
    for name in ("symbol_info_tick", "order_send", "positions_get"):
        assert hasattr(_FakeMT5(), name), f"fake missing {name}"


def test_close_failure_reports_position(tmp_path):
    mt5 = _FakeMT5(fail_close=True)
    rc = roundtrip(mt5, symbol="EURUSD", side="BUY", volume=0.01,
                   magic=100001, dry_run=False, journal_path=tmp_path / "j.csv")
    assert rc == 2 and len(mt5.positions_get()) == 1  # still open: close manually


def test_filling_mode_selection():
    mt5 = _FakeMT5()
    assert pick_filling(mt5, 2) == _FakeMT5.ORDER_FILLING_IOC
    assert pick_filling(mt5, 1) == _FakeMT5.ORDER_FILLING_FOK
    assert pick_filling(mt5, 0) is None


def test_fok_only_symbol_uses_fok(tmp_path):
    mt5 = _FakeMT5(filling_mode=1)
    rc = roundtrip(mt5, symbol="EURUSD", side="SELL", volume=0.01,
                   magic=100001, dry_run=False, journal_path=tmp_path / "j.csv")
    assert rc == 0
    assert mt5.sent[0]["type_filling"] == _FakeMT5.ORDER_FILLING_FOK
    assert mt5.sent[0]["type"] == _FakeMT5.ORDER_TYPE_SELL


def test_snap_volume_rounds_down_to_step():
    assert snap_volume(0.015, 0.01, 100.0, 0.01) == 0.01
    assert snap_volume(0.005, 0.01, 100.0, 0.01) == 0.01  # clamped to minimum
    assert snap_volume(200.0, 0.01, 100.0, 0.01) == 100.0


def test_build_request_close_carries_position_id():
    mt5 = _FakeMT5()
    req = build_request(mt5, symbol="EURUSD", side="SELL", volume=0.01, price=1.1,
                        magic=7, filling=2, comment="QT RT-S roundtrip", position_id=100)
    assert req["position_id"] == 100 and req["magic"] == 7
    assert len(req["comment"]) <= 31


def _touch(mt5, tmp_path, **kw):
    j = tmp_path / "journal.csv"
    base = dict(symbol="EURUSD", side="BUY", volume=0.01, magic=100001,
                dry_run=False, journal_path=j, distance_points=10,
                timeout=30.0, poll_secs=0.0)
    base.update(kw)
    return touch_close(mt5, **base), j


def test_touch_dry_run_sends_nothing(tmp_path):
    mt5 = _FakeMT5()
    rc, j = _touch(mt5, tmp_path, dry_run=True)
    assert rc == 0 and mt5.sent == []
    rows = _journal_rows(j)
    assert len(rows) == 1 and rows[0]["sl"] != "" and rows[0]["tp"] != ""


def test_touch_stops_clamped_to_broker_minimum(tmp_path):
    mt5 = _FakeMT5(stops_level=50)
    rc, _ = _touch(mt5, tmp_path, dry_run=True, distance_points=10)
    assert rc == 0
    assert mt5.sent == []  # dry-run: clamp visible in journal instead
    rows = _journal_rows(tmp_path / "journal.csv")
    assert rows[0]["sl"] == "1.09949"  # 51 points x 0.00001


def test_touch_tp_win_detected(tmp_path):
    mt5 = _FakeMT5(hide_after={100: 1})  # broker closes it on the 2nd poll
    rc, j = _touch(mt5, tmp_path)
    assert rc == 0
    assert len(mt5.sent) == 1  # open only; no market close needed
    rows = _journal_rows(j)
    assert "broker-closed TP" in rows[-1]["reason"]


def test_touch_timeout_falls_back_to_market_close(tmp_path):
    mt5 = _FakeMT5()  # never closes by itself
    rc, j = _touch(mt5, tmp_path, timeout=0.0)
    assert rc == 0
    assert len(mt5.sent) == 2  # open + fallback close
    assert mt5.sent[1]["position_id"] == 100
    assert "TIMEOUT" in _journal_rows(j)[-1]["reason"]
