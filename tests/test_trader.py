"""Trader tests. Fake MT5 only, never a terminal, never orders, dry-run first."""
import csv
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from quant import trader as tr
from tests.test_signals import _go_bars, _mirror

NOW = datetime(2026, 10, 12, 14, 30, tzinfo=timezone.utc)
MAGIC = 100001


def cfg(**over):
    base = {"max_total_positions": 4, "max_ccy_net": 2, "max_trades_per_day": 20,
            "max_cost_ratio": 0.30, "scope_low": 0.05, "scope_high": 0.50,
            "costs": {"slippage_pips": 0.3}, "halted": False}
    base.update(over)
    return base


def _scale(bars, s=0.0015):
    # linear rescale: signal rules are scale-free, ATR keeps proportions
    f = lambda p: 1.0 + (p - 100.0) * s
    return [[f(o), f(h), f(lo), f(c)] for o, h, lo, c in bars]


class _FakeMT5:
    ORDER_FILLING_IOC = 2
    ORDER_FILLING_FOK = 1
    ORDER_FILLING_RETURN = 0
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009

    def __init__(self, fail_open=False, mirror=False, spread=15):
        self.fail_open = fail_open
        self.spread = spread
        self.sent = []
        self.modifications = []
        self._positions = []
        bars = _go_bars()[0]
        self._bars = _mirror(_scale(bars), 2.4) if mirror else _scale(bars)
        self._next = 100

    def symbol_info(self, symbol):
        return SimpleNamespace(symbol=symbol, filling_mode=2, volume_min=0.01,
                               volume_max=100.0, volume_step=0.01, digits=5,
                               point=0.00001, spread=self.spread,
                               trade_tick_size=0.00001, trade_tick_value=0.0001)

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(ask=1.10000, bid=1.09990, time=1_770_000_000)

    def copy_rates_from_pos(self, symbol, tf, start, n):
        # broker rows: ascending time, closed bars only
        return tuple({"time": 1_700_000_000 + i * 3600, "open": o, "high": h,
                      "low": lo, "close": c}
                     for i, (o, h, lo, c) in enumerate(self._bars[-n:]))

    def positions_get(self, symbol=None):
        return tuple(self._positions)

    def history_deals_get(self, date_from, date_to):
        return (SimpleNamespace(magic=MAGIC, symbol="EURUSD", entry=0,
                                position_id=3000, time=NOW.timestamp(),
                                volume=0.01, price=1.1, ticket=3000, profit=0.0),)

    def order_send(self, req):
        if req.get("action") == 24:  # SLTP modify
            self.modifications.append(req)
            pos = next((p for p in self._positions
                        if p.ticket == req["position"]), None)
            if pos is not None:
                pos.sl = req["sl"]
            return SimpleNamespace(retcode=10009, deal=0, order=0, price=0.0)
        self.sent.append(req)
        if self.fail_open:
            return SimpleNamespace(retcode=10027, deal=0, order=0, price=0.0)
        pos = SimpleNamespace(ticket=self._next, magic=req["magic"],
                              symbol=req["symbol"], volume=req["volume"], type=0,
                              price_open=req["price"], sl=req.get("sl", 0.0),
                              tp=req.get("tp", 0.0), time=NOW.timestamp())
        self._next += 1
        self._positions.append(pos)
        return SimpleNamespace(retcode=10009, deal=55, order=56, price=req["price"])

    @staticmethod
    def deal(*, symbol="EURUSD", entry=0, magic=MAGIC, position_id=2000,
             time_=None):
        return SimpleNamespace(magic=magic, symbol=symbol, entry=entry,
                               position_id=position_id, volume=0.01, price=1.1,
                               ticket=position_id, profit=0.0,
                               time=time_ if time_ is not None else NOW.timestamp())


def _trade(mt5, mem, j, *, dry=True, direction="LONG", cfg_=None, deals=(),
           ranges=(), bar=1_800_000_000_000, params=None):
    return tr.trade_on_bar(mt5, "EURUSD", "EURUSD", direction, bar, NOW,
                           magic=MAGIC, dry=dry,
                           params=params or {"stop_atr": 1.5, "tp_mult": 3.0},
                           journal_path=j, mem=mem,
                           cfg=cfg_ if cfg_ is not None else cfg(),
                           deals=deals, ranges=ranges)


def _rows(p):
    with open(p, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _pos(ticket=100, symbol="EURUSD", ptype=0, sl=1.0900, vol=0.02, magic=MAGIC):
    return SimpleNamespace(ticket=ticket, magic=magic, symbol=symbol,
                           volume=vol, type=ptype, sl=sl, tp=0.0,
                           price_open=1.1000, time=NOW.timestamp())


# ------------------------------------------------------------------ entry flow

def test_dry_run_plans_never_sends(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    msg = _trade(mt5, mem, j)
    assert msg.startswith("PLAN") and mt5.sent == []
    row = _rows(j)[0]
    assert row["dry_run"] == "True" and row["trigger"] == "E1"
    assert float(row["sl"]) < float(row["tp"]) and float(row["sl"]) < 1.1
    assert row["position"] == "0" and float(row["risk_usd"]) > 0
    assert mem["bars"]["EURUSD"] == "1800000000000"
    # same bar again -> deduped by stamp (the double-order guard)
    assert _trade(mt5, mem, j) == "seen"
    assert _rows(j) == [row] and mt5.sent == []


def test_real_order_attaches_broker_sl_tp(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    msg = _trade(mt5, mem, j, dry=False)
    assert msg.startswith("ORDER pos=100")
    assert len(mt5.sent) == 1
    req = mt5.sent[0]
    assert req["type"] == 0 and req["magic"] == MAGIC            # BUY at ask
    assert 1.09 < req["sl"] < 1.0999 and req["sl"] < req["tp"]   # stops attach
    assert req["volume"] >= 0.01 and req["comment"].startswith("QT")
    assert abs(req["volume"] % 0.01) < 1e-9  # snapped to the broker lot step
    row = _rows(j)[0]
    assert row["position"] == "100" and row["dry_run"] == "False"
    assert float(row["risk_usd"]) == pytest.approx(0.05, rel=0.02)  # scope floor
    assert row["entry"].startswith("1.1")
    assert bool(mem["open"]) and mem["open"]["100"]["journaled"]


def test_short_plan_mirrors(tmp_path):
    mt5, j, mem = _FakeMT5(mirror=True), tmp_path / "j.csv", {}
    msg = _trade(mt5, mem, j, dry=False, direction="SHORT")
    assert msg.startswith("ORDER pos=100")
    req = mt5.sent[0]
    assert req["type"] == 1 and req["magic"] == MAGIC            # SELL at bid
    assert req["sl"] > 1.1001 and req["tp"] < req["sl"]


def test_failed_send_retries_then_succeeds(tmp_path):
    mt5, j, mem = _FakeMT5(fail_open=True), tmp_path / "j.csv", {}
    assert _trade(mt5, mem, j, dry=False).startswith("ORDER FAILED")
    assert mem.get("bars") is None  # bar unstamped -> the next cycle may retry
    mt5.fail_open = False
    assert _trade(mt5, mem, j, dry=False).startswith("ORDER pos=100")


def test_guards_pair_open_and_weekly_halt(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    mt5._positions = [_pos(sl=1.0, vol=0.01)]
    assert _trade(mt5, mem, j, bar=1) == "skip pair-open"
    assert mem["bars"]["EURUSD"] == "1"
    mt5._positions = []
    out = _trade(mt5, mem, j, cfg_=cfg(halted=True), bar=2)
    assert out == "skip weekly-halt" and mem["bars"]["EURUSD"] == "2"


def test_daily_caps_portfolio_and_pair(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    d1 = _FakeMT5.deal(symbol="GBPUSD", position_id=2000)
    d2 = _FakeMT5.deal(symbol="AUDUSD", position_id=2100)
    mine = _FakeMT5.deal(symbol="EURUSD", position_id=3000)
    out = _trade(mt5, mem, j, cfg_=cfg(max_trades_per_day=2), deals=[d1, d2], bar=1)
    assert out == "skip cap-day"
    out = _trade(mt5, mem, j, cfg_=cfg(max_trades_per_day=3), deals=[d1, mine], bar=2)
    assert out == "skip cap-day-pair"  # 1 entry/pair/day is structural


def test_no_trade_window(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    out = _trade(mt5, mem, j, ranges=[("10-12", "10-12")])
    assert out.startswith("skip window") and mem["bars"]["EURUSD"]


def test_gate_fail_stamps_bar(tmp_path):
    mt5, j, mem = _FakeMT5(), tmp_path / "j.csv", {}
    assert _trade(mt5, mem, j, direction="SHORT", bar=1).startswith("skip gate")
    assert mem["bars"]["EURUSD"] == "1"
    mt5b = _FakeMT5(mirror=False)
    mem2 = {}
    out = _trade(mt5b, mem2, j, direction="SHORT")   # mirror-off cannot pass SHORT gates
    assert out.startswith("skip gate")


def test_bad_data_leaves_bar_unstamped(tmp_path):
    mt5 = _FakeMT5()
    mt5.symbol_info = lambda s: None
    out = _trade(mt5, {}, tmp_path / "j.csv")
    assert out.startswith("DATA ERROR")


# ------------------------------------------------------------------ portfolio

def test_positions_breach_total_and_ccy():
    open_ = [SimpleNamespace(symbol="EURUSD", type=0),
             SimpleNamespace(symbol="GBPUSD", type=0)]
    assert tr.positions_breach(open_, "AUDUSD", "LONG", 2, 0) == "cap-total"
    assert tr.positions_breach(open_[:1], "EURUSD", "LONG", 4, 1) == "cap-ccy"
    # shorting what we hold nets to zero: allowed while hedging is on
    assert tr.positions_breach(open_[:1], "EURUSD", "SHORT", 4, 2) is None
    assert tr.positions_breach([], "XAUUSD", "LONG", 0, 0) is None  # 0 = off


def test_opened_positions_today_counts_our_in_deals():
    day_ts = NOW.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    deals = [
        _FakeMT5.deal(position_id=11), _FakeMT5.deal(position_id=12),
        _FakeMT5.deal(position_id=13, magic=999),                 # foreign
        _FakeMT5.deal(position_id=14, entry=1),                   # OUT, not IN
        _FakeMT5.deal(position_id=15, time_=day_ts - 3600),       # yesterday
    ]
    assert tr.opened_positions_today(deals, MAGIC, day_ts) == 2


# --------------------------------------------------------------------- adoption

def test_sync_orphan_adopted_once_and_ghost_closed(tmp_path):
    mt5, j = _FakeMT5(), tmp_path / "j.csv"
    mt5._positions = [_pos()]
    info = mt5.symbol_info("EURUSD")
    mem = tr.sync_book(mt5, MAGIC, "EURUSD", info, {}, {}, {}, j)
    assert "100" in mem["open"]
    assert abs(mem["open"]["100"]["stop_dist"] - 0.01) < 1e-9  # from current SL
    assert len(_rows(j)) == 1 and _rows(j)[0]["trigger"] == "adopt"
    # restart with the same position + the recovered journal row: no new row
    jrows = tr.journal_by_position(j)
    assert 100 in jrows
    mem2 = tr.sync_book(mt5, MAGIC, "EURUSD", info, {}, jrows,
                        tr.load_mem(tmp_path / "x.json"), j)
    assert "100" in mem2["open"] and len(_rows(j)) == 1
    # position gone from the terminal -> one close row, dropped from the book
    mt5._positions = []
    mem3 = tr.sync_book(mt5, MAGIC, "EURUSD", info, {}, jrows, mem2, j)
    assert "100" not in mem3["open"]
    last = _rows(j)[-1]
    assert last["trigger"] == "close" and last["position"] == "100"


def test_sync_prefers_journal_initial_stop(tmp_path):
    mt5, j = _FakeMT5(), tmp_path / "j.csv"
    mt5._positions = [_pos(sl=1.1050)]  # SL already trailed past entry
    info = mt5.symbol_info("EURUSD")
    jrows = {100: {"entry": "1.1000", "sl": "1.0900", "risk_usd": "12.5"}}
    mem = tr.sync_book(mt5, MAGIC, "EURUSD", info, {}, jrows, {}, j)
    ctx = mem["open"]["100"]
    assert abs(ctx["stop_dist"] - 0.0100) < 1e-9     # journal initial stop, not the SL
    assert ctx["risk_usd"] == 12.5                    # 1R from the journal row
    assert ctx["init_sl"] == 1.0900                   # no adopt noise
    assert not j.exists() or len(_rows(j)) == 0


# ------------------------------------------------------------------- trailing

def _ctx(direction="BUY", entry=1.1000, stop=0.0100, best=None):
    return {"symbol": "EURUSD", "direction": direction, "entry": entry,
            "stop_dist": stop, "risk_usd": 10.0, "lots": 0.02,
            "best": best if best is not None else entry,
            "init_sl": entry - stop if direction == "BUY" else entry + stop,
            "journaled": True, "open_time": 1}


def test_trail_arms_on_trigger_and_only_improves():
    params = {"use_trail": True, "use_be": False, "trail_r": 1.0, "be_trigger_r": 1.0}
    # LONG: not activated -> nothing
    new, best, act = tr.trail_decision(_ctx(), 1.1020, params, 1.0900)
    assert (new, best, act) == (None, 1.1020, False)
    # activated: SL trails the best bid by 1R
    new, best, act = tr.trail_decision(_ctx(), 1.1150, params, 1.0900)
    assert new == 1.1050 and act and best == 1.1150
    # broker SL already there -> sub-nudge, no call
    new, best, act = tr.trail_decision(_ctx(), 1.1150, params, 1.10500)
    assert new is None
    # SHORT mirror: SL walks down as the bid falls
    new, best, act = tr.trail_decision(_ctx("SHORT"), 1.0850, params, 1.1150)
    assert new == 1.0950 and act and best == 1.0850


def test_trail_be_overlay():
    p = {"use_trail": True, "use_be": True, "trail_r": 1.0,
         "be_trigger_r": 1.0, "be_buffer": 0.0001}
    new, best, act = tr.trail_decision(_ctx(), 1.1100, p, 1.0900)
    assert new == 1.1001  # BE floor lifts the stop while the trail cannot yet
    new, best, act = tr.trail_decision(_ctx(), 1.1150, p, 1.0900)
    assert new == 1.1050  # trail overtakes BE once far enough
    # no BE/trail configured (config off) -> the system never touches stops
    assert tr.trail_decision(_ctx(), 1.1999, {"use_trail": False, "use_be": False,
                                              "trail_r": 1.0}, 1.09)[0] is None


def test_manage_book_trails_and_journals(tmp_path):
    mt5, j = _FakeMT5(), tmp_path / "j.csv"
    mt5._positions = [_pos(sl=1.0850)]
    # the position exists in the journal from an earlier entry (restart path)
    jrows = {100: {"entry": "1.0900", "sl": "1.0850", "risk_usd": "10"}}
    context = _ctx(entry=1.0900, stop=0.0050)
    context["symbol"] = "EURUSD"
    mem = {"open": {"100": context}}
    msgs = tr.manage_book(mt5, "EURUSD", "EURUSD",
                          {"use_trail": True, "use_be": False, "trail_r": 1.0},
                          MAGIC, False, j, mem, jrows)
    assert msgs and msgs[0].startswith("TRAIL pos=100")
    assert mt5._positions[0].sl == 1.0949  # bid 1.09990 - 1R (0.0050)
    row = _rows(j)[-1]
    assert row["trigger"] == "trail" and row["position"] == "100"
    assert mem["open"]["100"]["best"] == 1.0999  # monotonic best for the next pass


def test_manage_dry_run_plans_only(tmp_path):
    mt5, j = _FakeMT5(), tmp_path / "j.csv"
    mt5._positions = [_pos(sl=1.0850)]
    jrows = {100: {"entry": "1.0900", "sl": "1.0850", "risk_usd": "10"}}
    context = _ctx(entry=1.0900, stop=0.0050)
    context["symbol"] = "EURUSD"
    mem = {"open": {"100": context}}
    msgs = tr.manage_book(mt5, "EURUSD", "EURUSD",
                          {"use_trail": True, "use_be": False, "trail_r": 1.0},
                          MAGIC, True, j, mem, jrows)
    assert msgs[0].startswith("TRAIL(plan)")
    assert mt5.sent == [] and mt5._positions[0].sl == 1.0850


def test_modify_sl_request_shape():
    mt5 = _FakeMT5()
    ok, _ = tr.modify_sl(mt5, _pos(), 1.1050)
    req = mt5.modifications[-1]
    assert ok and req["action"] == 24 and req["position"] == 100
    assert req["tp"] == 0.0 and req["sl"] == 1.1050


def test_mem_roundtrip(tmp_path):
    p = tmp_path / "live.json"
    mem = {"bars": {"EURUSD": "1"}, "open": {"100": _ctx()}}
    tr.save_mem(p, mem)
    assert tr.load_mem(p) == mem
    assert tr.load_mem(tmp_path / "missing.json") == {"bars": {}, "open": {}}


def test_read_trade_cfg_same_yaml_paths_as_engine(tmp_path):
    import yaml

    from quant.monitor import read_trade_cfg

    d = tmp_path / "configs"
    d.mkdir()
    (d / "_base.yaml").write_text(yaml.safe_dump({
        "live": {"magic": 777, "dry_run_default": True},
        "risk": {"max_total_positions": 4, "max_ccy_net": 2,
                 "sizing_scope_usd": {"low": 12, "high": 30}},
        "limits": {"max_trades_per_day": 20, "max_cost_ratio": 0.15,
                   "weekly_loss_pct": 15, "no_trade_ranges": []},
        "costs": {"spread_pips": 1.5, "slippage_pips": 0.3},
    }), encoding="utf-8")
    cfg = read_trade_cfg(d)
    assert cfg["magic"] == 777 and cfg["dry_run_default"] is True
    assert cfg["max_total_positions"] == 4 and cfg["max_ccy_net"] == 2
    assert (cfg["scope_low"], cfg["scope_high"]) == (12.0, 30.0)
    assert cfg["max_trades_per_day"] == 20 and cfg["max_cost_ratio"] == 0.15
    assert cfg["ranges"] == () and cfg["costs"]["spread_pips"] == 1.5
    # missing file -> engine defaults, everything still a working dict
    cfg2 = read_trade_cfg(tmp_path / "nope")
    assert cfg2["magic"] == 100001 and cfg2["dry_run_default"] is True
    assert cfg2["max_total_positions"] == 0 and cfg2["scope_high"] == 0.0
