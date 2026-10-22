"""Pair guards use accepted entries and closed losses; no terminal or local data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from quant.backtest import portfolio_filter
from quant.dice_probe import apply_filters
from quant.limits import read_pair_limits, read_entry_hours, entry_time_allowed
from quant.monitor import read_trade_cfg
from quant.trader import pair_history_reason
from tests.test_backtest import _pt
from tests.test_trader import MAGIC, NOW, _FakeMT5, _trade, cfg


@pytest.mark.parametrize("clock,allowed", [
    ("01:14:59", False), ("01:15:00", True), ("14:59:59", True),
    ("15:00:00", False), ("23:59:00", False)])
def test_malaysia_entry_hours_boundaries(clock, allowed):
    hours = read_entry_hours({"entry_hours": {"enabled": True}})
    for date in ("2026-01-15", "2026-10-21"):
        assert entry_time_allowed(pd.Timestamp(f"{date} {clock}", tz="UTC"), hours) is allowed


def test_entry_hours_disabled_wrap_offset_and_naive_time():
    at = pd.Timestamp("2026-10-21 16:00", tz="Etc/GMT-3")  # broker 16:00 = Malaysia 21:00
    assert entry_time_allowed(at, read_entry_hours({"entry_hours": {"enabled": True}}))
    assert entry_time_allowed(at, read_entry_hours({}))
    hours = read_entry_hours({"entry_hours": {"enabled": True, "start": "22:00", "end": "02:00"}})
    assert entry_time_allowed(pd.Timestamp("2026-10-21 15:00", tz="UTC"), hours)
    assert not entry_time_allowed(pd.Timestamp("2026-10-21 18:00", tz="UTC"), hours)
    with pytest.raises(ValueError, match="timezone-aware"):
        entry_time_allowed(datetime(2026, 10, 21), hours)


@pytest.mark.parametrize("over", [{"enabled": "false"}, {"start": "9:15"},
    {"end": "24:00"}, {"start": "23:00"}, {"utc_offset_hours": float("nan")},
    {"utc_offset_hours": True}, {"utc_offset_hours": 24}])
def test_invalid_entry_hours_rejected(over):
    with pytest.raises(ValueError, match="entry_hours"):
        read_entry_hours({"entry_hours": over})


def test_monitor_reads_entry_hours_and_rejects_invalid_settings(tmp_path):
    import yaml
    path = tmp_path / "_base.yaml"
    settings = {"enabled": True, "utc_offset_hours": 8, "start": "09:15", "end": "23:00"}
    path.write_text(yaml.safe_dump({"limits": {"entry_hours": settings}}))
    assert read_trade_cfg(tmp_path)["entry_hours"] == settings
    path.write_text(yaml.safe_dump({"limits": {"entry_hours": {"end": "25:00"}}}))
    with pytest.raises(ValueError, match="entry_hours"):
        read_trade_cfg(tmp_path)


def test_dice_rejects_reference_without_enabled_hours(tmp_path):
    import json
    from quant.dice_probe import validate_reference_setup
    params = {"strategy": {}, "timeframes": {"execution": "H4", "regime": "D1"},
        "jobs": [], "max_cost_ratio": 0.1, "position_checks": "H4"}
    (tmp_path / "params.json").write_text(json.dumps(params))
    setup = {"strategy": {}, "execution": "H4", "regime": "D1", "jobs": [],
        "scope_low": 0, "scope_high": 0, "default_lot": 0.01, "stop_sizing": {},
        "max_day": 0, "max_cost_ratio": 0.1, "position_checks": "H4", "no_trade_ranges": (),
        "max_open": 0, "max_ccy_net": 0, "weekly_r": 0}
    validate_reference_setup(setup, tmp_path)  # older disabled reference remains compatible
    setup["entry_hours"] = read_entry_hours({"entry_hours": {"enabled": True}})
    with pytest.raises(ValueError, match="limits differ"):
        validate_reference_setup(setup, tmp_path)
    params["entry_hours"] = setup["entry_hours"]
    (tmp_path / "params.json").write_text(json.dumps(params))
    validate_reference_setup(setup, tmp_path)


def test_live_outside_hours_stamps_bar_and_never_sends(tmp_path):
    hours = {"enabled": True, "start": "09:15", "end": "22:00"}
    mt5, mem = _FakeMT5(), {}
    result = _trade(mt5, mem, tmp_path / "journal.csv", cfg_=cfg(entry_hours=hours))
    assert result == "skip entry-hours"  # NOW is Malaysia 22:30
    assert mem["bars"]["EURUSD"]
    assert not mt5.sent
    assert _trade(mt5, mem, tmp_path / "journal.csv", cfg_=cfg(entry_hours=hours)) == "seen"


def test_backtest_hours_use_fill_not_signal_and_keep_later_exit():
    from quant.backtest import simulate
    from tests.test_dice_probe import _zero_costs
    bars = pd.DataFrame({"time": pd.to_datetime([
        "2026-10-21 00:00Z", "2026-10-21 04:00Z", "2026-10-21 16:00Z"]),
        "open": [1.1] * 3, "high": [1.1001, 1.1001, 1.12],
        "low": [1.0999, 1.0999, 1.0999], "close": [1.1] * 3})
    candidate = {"t": 0, "direction": "LONG", "atr": 0.001}
    settings = {"stop_atr": 1.5, "tp_mult": 2.5, "use_trail": False, "use_be": False}
    kwargs = dict(p=settings, costs=_zero_costs(), risk_usd=3, max_cost_ratio=0)
    hours = read_entry_hours({"entry_hours": {"enabled": True}})
    trades, _ = simulate(bars, "EURUSD", [candidate], entry_hours=hours, **kwargs)
    assert len(trades) == 1  # signal 08:00 local is outside; fill 12:00 is inside
    assert pd.Timestamp(trades.iloc[0]["exit_time"]).hour == 16  # midnight local exit still runs
    rejected, funnel = simulate(bars, "EURUSD", [{**candidate, "t": 1}], entry_hours=hours, **kwargs)
    assert rejected.empty and funnel["entry_hours"] == 1
    legacy, _ = simulate(bars, "EURUSD", [candidate], **kwargs)
    pd.testing.assert_frame_equal(trades, legacy)


def _series(*rows):
    return pd.concat([_pt("EURUSD", *row) for row in rows], ignore_index=True)


def test_weekly_pair_cap_and_monday_reset():
    trades = {"EURUSD": _series(
        ("2026-10-12 01:00", "2026-10-12 02:00"),
        ("2026-10-13 01:00", "2026-10-13 02:00"),
        ("2026-10-14 01:00", "2026-10-14 02:00"),
        ("2026-10-19 01:00", "2026-10-19 02:00"))}
    kept, drops = portfolio_filter(trades, 0, 0, 0, max_trades_per_pair_per_week=2)
    assert len(kept["EURUSD"]) == 3
    assert [d["reason"] for d in drops] == ["pair_week_cap"]
    assert len(portfolio_filter(trades, 0, 0, 0)[0]["EURUSD"]) == 4


def test_daily_loss_uses_close_day_net_usd_and_resets():
    trades = {"EURUSD": _series(
        ("2026-10-09 01:00", "2026-10-12 02:00"),
        ("2026-10-12 02:00", "2026-10-12 03:00"),
        ("2026-10-13 01:00", "2026-10-13 02:00")),
        "GBPUSD": _pt("GBPUSD", "2026-10-12 02:00", "2026-10-12 03:00")}
    # A tiny gross gain can still lose after fees: judge net USD, not exit type.
    trades["EURUSD"].loc[0, "pnl_usd"] = -0.01
    kept, drops = portfolio_filter(trades, 0, 0, 0, disable_pair_after_daily_loss=True)
    assert len(kept["EURUSD"]) == 2
    assert len(kept["GBPUSD"]) == 1
    assert [d["reason"] for d in drops] == ["pair_daily_loss"]


@pytest.mark.parametrize("pnl", [0.0, 1.0])
def test_scratch_and_win_do_not_disable_pair(pnl):
    trades = {"EURUSD": _series(
        ("2026-10-12 01:00", "2026-10-12 02:00", "LONG", pnl),
        ("2026-10-12 02:00", "2026-10-12 03:00"))}
    kept, drops = portfolio_filter(trades, 0, 0, 0, disable_pair_after_daily_loss=True)
    assert len(kept["EURUSD"]) == 2
    assert not drops


def test_rejected_trade_consumes_no_week_quota_and_creates_no_loss_block():
    trades = {"AUDUSD": _pt("AUDUSD", "2026-10-12 01:00", "2026-10-12 03:00"),
              "EURUSD": _series(
                  ("2026-10-12 02:00", "2026-10-12 04:00", "LONG", -1.0),
                  ("2026-10-12 05:00", "2026-10-12 06:00"))}
    kept, drops = portfolio_filter(
        trades, 1, 0, 0, max_trades_per_pair_per_week=1,
        disable_pair_after_daily_loss=True)
    assert len(kept["EURUSD"]) == 1
    assert kept["EURUSD"].iloc[0]["entry_time"] == "2026-10-12 05:00"
    assert [d["reason"] for d in drops] == ["open_max"]


def test_rejected_pair_does_not_consume_portfolio_daily_quota():
    trades = {"EURUSD": _series(
        ("2026-10-11 01:00", "2026-10-12 01:00", "LONG", -1.0),
        ("2026-10-12 02:00", "2026-10-12 03:00")),
        "GBPUSD": _pt("GBPUSD", "2026-10-12 04:00", "2026-10-12 05:00")}
    kept, drops = portfolio_filter(
        trades, 0, 0, 0, disable_pair_after_daily_loss=True, max_trades_per_day=1)
    assert len(kept["GBPUSD"]) == 1
    assert [d["reason"] for d in drops] == ["pair_daily_loss"]


def test_dice_filter_uses_same_pair_and_daily_admission():
    trades = {"EURUSD": _series(
        ("2026-10-12 01:00", "2026-10-12 02:00"),
        ("2026-10-13 01:00", "2026-10-13 02:00"))}
    setup = {"max_day": 1, "max_open": 0, "max_ccy_net": 0, "weekly_r": 0,
             "max_trades_per_pair_per_week": 1}
    kept, cap_drops, drops = apply_filters(trades, setup)
    assert len(kept["EURUSD"]) == 1
    assert cap_drops == []
    assert drops[0]["reason"] == "pair_week_cap"


def _deal(pid=1, *, entry=0, at=NOW, magic=MAGIC, **over):
    fields = dict(position_id=pid, symbol="EURUSD", magic=magic, entry=entry,
                  time=at.timestamp(), volume=0.01, profit=0.0,
                  commission=0.0, swap=0.0, fee=0.0)
    fields.update(over)
    return SimpleNamespace(**fields)


def test_live_week_cap_counts_distinct_positions_and_ignores_other_magic():
    deals = [_deal(), _deal(), _deal(2), _deal(3, magic=999),
             _deal(4, at=NOW - timedelta(days=7))]
    assert pair_history_reason(None, deals, MAGIC, "EURUSD", NOW, 2, False) == "pair_week_cap"
    assert pair_history_reason(None, deals, MAGIC, "EURUSD", NOW, 3, False) is None
    assert pair_history_reason(None, deals, MAGIC, "EURUSD", NOW + timedelta(days=7),
                               2, False) is None


@pytest.mark.parametrize("entry", [1, 3])
def test_live_loss_includes_old_entry_fees_and_manual_close(entry):
    old_entry = _deal(at=NOW - timedelta(days=400), commission=-0.2)
    close = _deal(entry=entry, magic=0, profit=0.1)
    mt5 = SimpleNamespace(history_deals_get=lambda **kw: [old_entry, close])
    assert pair_history_reason(mt5, [close], MAGIC, "EURUSD", NOW, 2, True) == "pair_daily_loss"
    assert pair_history_reason(mt5, [close], MAGIC, "EURUSD", NOW + timedelta(days=1),
                               2, True) is None


def test_partial_close_waits_for_full_position_and_other_magic_is_ignored():
    opened = _deal(volume=0.02)
    closed = _deal(entry=1, profit=-1)
    mt5 = SimpleNamespace(history_deals_get=lambda **kw: [opened, closed])
    assert pair_history_reason(mt5, [closed], MAGIC, "EURUSD", NOW, 0, True) is None
    opened.magic = 999
    opened.volume = 0.01
    assert pair_history_reason(mt5, [closed], MAGIC, "EURUSD", NOW, 0, True) is None


@pytest.mark.parametrize("history", [None, ()])
def test_missing_position_history_fails_closed(history):
    mt5 = SimpleNamespace(history_deals_get=lambda **kw: history)
    with pytest.raises(ValueError, match="history unavailable"):
        pair_history_reason(mt5, [_deal(entry=1)], MAGIC, "EURUSD", NOW, 0, True)


def test_live_history_failure_is_retryable_and_does_not_send(tmp_path):
    mt5, mem = _FakeMT5(), {}
    msg = _trade(mt5, mem, tmp_path / "j.csv", deals=None,
                 cfg_=cfg(max_trades_per_pair_per_week=2))
    assert msg.startswith("DATA ERROR")
    assert not mem.get("bars")
    assert mt5.sent == []


def test_live_restart_recovers_pair_cap_and_disabled_guard_allows_plan(tmp_path):
    mt5, mem = _FakeMT5(), {}
    deals = [_deal(), _deal(2)]
    msg = _trade(mt5, mem, tmp_path / "j.csv", deals=deals,
                 cfg_=cfg(max_trades_per_pair_per_week=2, max_trades_per_day=0))
    assert msg == "skip pair_week_cap"
    msg = _trade(mt5, {}, tmp_path / "j.csv", deals=deals,
                 cfg_=cfg(max_trades_per_pair_per_week=0, max_trades_per_day=0))
    assert msg.startswith("PLAN")
    assert mt5.sent == []


def test_dry_plans_do_not_consume_weekly_quota(tmp_path):
    mt5, mem = _FakeMT5(), {}
    for bar in (1, 2, 3):
        assert _trade(mt5, mem, tmp_path / "j.csv", bar=bar,
                      cfg_=cfg(max_trades_per_pair_per_week=1)).startswith("PLAN")
    assert mt5.sent == []


def test_failed_send_does_not_consume_quota_or_stamp(tmp_path):
    mt5, mem = _FakeMT5(fail_open=True), {}
    for _ in range(2):
        msg = _trade(mt5, mem, tmp_path / "j.csv", dry=False,
                     cfg_=cfg(max_trades_per_pair_per_week=1))
        assert not msg.startswith("skip")
        assert not mem.get("bars")
    assert len(mt5.sent) == 2  # Fake terminal only: failed attempts leave no deals.


def test_scaling_with_pair_limits_refused_before_any_data_or_simulation(monkeypatch, capsys):
    from quant import backtest

    def forbidden(*args, **kwargs):
        pytest.fail("must reject the combination before running any simulation")

    monkeypatch.setattr(backtest, "run_all", forbidden)
    assert backtest.main(["--scale-lots"]) == 2
    assert "unified sizing/admission pass" in capsys.readouterr().out


@pytest.mark.parametrize("limits", [
    {"max_trades_per_pair_per_week": -1},
    {"max_trades_per_pair_per_week": 2.5},
    {"max_trades_per_pair_per_week": True},
    {"disable_pair_after_daily_loss": "false"},
])
def test_invalid_pair_controls_rejected(limits):
    with pytest.raises(ValueError):
        read_pair_limits(limits)


def test_active_config_and_legacy_defaults():
    settings = read_trade_cfg("configs")
    assert settings["max_trades_per_pair_per_week"] == 2
    assert settings["disable_pair_after_daily_loss"] is True
    assert read_pair_limits({}) == {"max_trades_per_pair_per_week": 0,
                                    "disable_pair_after_daily_loss": False}


def test_utc_week_boundary_is_not_local_monday():
    # Malaysia Monday 01:00 is still Sunday UTC: last week's entries still count.
    local = datetime(2026, 10, 19, 1, tzinfo=timezone(timedelta(hours=8)))
    deals = [_deal(at=datetime(2026, 10, 12, tzinfo=timezone.utc))]
    assert pair_history_reason(None, deals, MAGIC, "EURUSD", local, 1, False) == "pair_week_cap"
