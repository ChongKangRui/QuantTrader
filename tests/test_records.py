"""Records tests. No terminal, no real MT5 import."""
from types import SimpleNamespace

from quant.records import (
    COLUMNS,
    load_conditions,
    position_row,
    read_watermark,
    sync_closed_positions,
)

MAGIC = 100001


def _deal(ticket, typ, entry, price, volume=0.01, profit=0.0, commission=0.0,
          swap=0.0, magic=MAGIC, pid=11, time=1_700_000_000, symbol="EURUSD"):
    return SimpleNamespace(ticket=ticket, type=typ, entry=entry, price=price,
                            volume=volume, profit=profit, commission=commission,
                            swap=swap, magic=magic, position_id=pid, time=time,
                            symbol=symbol)


class _FakeMT5:
    def __init__(self, deals):
        self._deals = deals

    def history_deals_get(self, date_from, date_to):
        return tuple(self._deals)


def _closed_buy(pid=11, t0=1_700_000_000):
    return [_deal(5, 0, 0, 1.1000, time=t0, pid=pid),
            _deal(6, 1, 1, 1.1100, profit=10.0, commission=-0.5, swap=-0.2,
                  time=t0 + 3600, pid=pid)]


def test_closed_buy_row_values():
    row = position_row(11, _closed_buy(), "stack+HR1a", "DEMO")
    assert row["side"] == "BUY"
    assert row["entry_price"] == 1.1 and row["close_price"] == 1.11
    assert row["profit"] == 10.0 and row["commission"] == -0.5 and row["swap"] == -0.2
    assert row["ticket"] == 6 and row["magic"] == MAGIC
    assert row["entry_condition"] == "stack+HR1a" and row["account"] == "DEMO"
    assert set(row.keys()) == set(COLUMNS)


def test_open_position_without_out_deal_is_skipped():
    assert position_row(11, [_deal(5, 0, 0, 1.1)], "", "DEMO") is None


def test_wrong_magic_and_open_positions_excluded_from_sync(tmp_path):
    p = tmp_path / "demo.csv"
    mt5 = _FakeMT5(_closed_buy() + [_deal(7, 0, 0, 1.1, magic=999),
                                   _deal(8, 0, 0, 1.2, pid=12)])
    n = sync_closed_positions(mt5, p, MAGIC, {}, "DEMO")
    assert n == 1
    assert read_watermark(p) == 6


def test_watermark_prevents_duplicates_on_restart(tmp_path):
    p = tmp_path / "demo.csv"
    mt5 = _FakeMT5(_closed_buy())
    assert sync_closed_positions(mt5, p, MAGIC, {}, "DEMO") == 1
    assert sync_closed_positions(mt5, p, MAGIC, {}, "DEMO") == 0  # restart: nothing new
    ds = _closed_buy(pid=13, t0=1_700_010_000)
    ds = [SimpleNamespace(**{**vars(d), "ticket": d.ticket + 10}) for d in ds]
    assert sync_closed_positions(_FakeMT5(_closed_buy() + ds), p, MAGIC, {}, "DEMO") == 1
    assert read_watermark(p) == 16


def test_entry_missing_from_window_derives_side(tmp_path):
    p = tmp_path / "demo.csv"
    out_only = [_deal(9, 1, 1, 1.1100, profit=-3.0, time=1_700_005_000, pid=14)]
    assert sync_closed_positions(_FakeMT5(out_only), p, MAGIC, {}, "REAL") == 1
    row = position_row(14, out_only, "", "REAL")
    assert row["side"] == "BUY" and row["entry_price"] == ""  # out SELL closes BUY


def test_early_opened_position_keeps_entry_after_watermark_ran_ahead(tmp_path):
    # A opens (ticket 1) while B (tickets 2-3) opens and closes; A's IN deal sits
    # BELOW the watermark the old per-deal filter produced -> lost entry data.
    p = tmp_path / "demo.csv"
    b = [_deal(2, 0, 0, 1.1000, pid=21), _deal(3, 1, 1, 1.1050, profit=1.0, pid=21)]
    assert sync_closed_positions(_FakeMT5(b), p, MAGIC, {}, "DEMO") == 1
    full = [_deal(1, 0, 0, 1.2000, commission=-0.3, pid=20), b[0], b[1],
            _deal(4, 1, 1, 1.2200, profit=-2.0, commission=-0.4, pid=20)]
    assert sync_closed_positions(_FakeMT5(full), p, MAGIC, {"1": "stack+HR1a"}, "DEMO") == 1
    import pandas as pd
    rows = pd.read_csv(p)
    a = rows[rows["ticket"] == 4].iloc[0]
    assert a["entry_price"] == 1.2          # IN deal survived below the watermark
    assert a["commission"] == -0.7          # IN + OUT commissions both counted
    assert a["entry_condition"] == "stack+HR1a"


def test_conditions_join_on_ticket(tmp_path):
    j = tmp_path / "journal.csv"
    j.write_text("ticket,reason,comment\n5,stack+HR1a,QT B1-L E1\n", encoding="utf-8")
    assert load_conditions(j) == {"5": "stack+HR1a"}
    assert load_conditions(tmp_path / "missing.csv") == {}
