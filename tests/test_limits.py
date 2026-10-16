"""Limits tests. No terminal."""
from datetime import datetime, timezone
from types import SimpleNamespace

from quant.limits import assess, evaluate, load_state, save_state, week_key, week_realized, week_start


def _deal(profit, commission=0.0, swap=0.0, magic=100001, time=1_700_000_000):
    return SimpleNamespace(profit=profit, commission=commission, swap=swap,
                           magic=magic, time=time)


def test_week_key_monday_boundaries():
    mon = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)  # a Monday
    assert week_start(mon) == mon
    assert week_key(mon) == week_key(mon.replace(hour=23))
    assert week_start(mon.replace(hour=23)) == mon
    assert week_key(datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)) != week_key(mon)


def test_week_realized_sums_own_magic_in_week_only():
    monday = week_start(datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)).timestamp()
    deals = [_deal(-5.0, time=monday + 100),
             _deal(-2.0, commission=-0.5, swap=-0.5, time=monday + 200),
             _deal(-100.0, time=monday - 100),  # last week: excluded
             _deal(-100.0, magic=999, time=monday + 300)]  # other magic: excluded
    assert week_realized(deals, monday, 100001) == -8.0


def test_assess_trips_at_threshold_and_snapshots_equity():
    state, halted, pct = assess({}, "2026-W42", 100.0, -15.0, 15.0)
    assert (halted, pct) == (True, 15.0)
    assert state == {"week": "2026-W42", "start_equity": 100.0, "realized": -15.0}
    state, halted, pct = assess({}, "2026-W42", 100.0, -14.99, 15.0)
    assert halted is False and pct == 14.99


def test_assess_new_week_resets_and_zero_equity_never_halts():
    state, halted, _ = assess({"week": "2026-W41", "start_equity": 90.0, "realized": -20.0},
                              "2026-W42", 85.0, 0.0, 15.0)
    assert halted is False and state["start_equity"] == 85.0
    _, halted, pct = assess({}, "2026-W42", 0.0, -50.0, 15.0)
    assert halted is False and pct == 0.0


def test_state_roundtrip_and_evaluate_persists(tmp_path):
    p = tmp_path / "memory" / "weekly_demo.json"
    assert load_state(p) == {}
    save_state(p, {"week": "2026-W42", "start_equity": 100.0, "realized": 0.0})
    assert load_state(p)["week"] == "2026-W42"
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    monday = week_start(now).timestamp()
    info = evaluate(p, [_deal(-16.0, time=monday + 60)], 100001, 100.0, 15.0, now)
    assert info["halted"] is True and info["loss_pct"] == 16.0
    assert load_state(p)["realized"] == -16.0
