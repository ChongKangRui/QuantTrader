"""Local-file accounting and mocked broker reconciliation; no live orders."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from quant.account_store import AccountStore, account_directory, write_performance, main


NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def info(**changes):
    return NS(**{**dict(login=7, server="Mock/Broker", trade_mode=0, currency="USD",
                        equity=100, balance=100), **changes})


def deal(ticket, **changes):
    return NS(**{**dict(ticket=ticket, order=ticket + 100, position_id=10,
                        type=0, entry=0, magic=42, symbol="EURUSD", volume=.01,
                        time=int(NOW.timestamp()), profit=0, commission=-.2, swap=0, fee=-.1),
                 **changes})


def test_account_server_and_type_are_isolated(tmp_path):
    identities = [info(), info(login=8), info(server="Other"), info(trade_mode=2)]
    assert len({account_directory(tmp_path, i) for i in identities}) == 4
    assert all(p.parent == tmp_path for p in [account_directory(tmp_path, i) for i in identities])


def test_reconcile_deduplicates_deals_and_retains_older_missing_tickets(tmp_path):
    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [deal(30)], [], NOW)
    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [deal(30), deal(20), deal(40, entry=1, volume=.005)], [], NOW)
    store.reconcile(info(), [deal(40, entry=1, volume=.005)], [], NOW)
    assert set(store.data["deals"]) == {"20", "30", "40"}
    assert len(store.data["snapshots"]) == 1
    assert store.data["deals"]["40"]["volume"] == .005
    assert store.performance()["deal_totals"]["net_realized"] == pytest.approx(-.9)


def test_all_fees_and_manual_trades_are_recorded_but_strategy_totals_separate(tmp_path):
    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [deal(1, profit=10, swap=-1), deal(2, type=7, magic=0, profit=-2,
                          commission=0, fee=0), deal(3, magic=0, profit=3)], [], NOW)
    result = write_performance(store, magic=42)
    assert result["deal_totals"]["net_realized"] == pytest.approx(9.4)
    assert result["strategy_deal_totals"]["net_realized"] == pytest.approx(8.7)
    assert (store.directory / "deals.csv").exists()
    assert "commission" in (store.directory / "performance.html").read_text(encoding="utf-8")
    assert main(["--account-dir", str(store.directory)]) == 0


def test_write_ahead_and_confirmed_deal_survive_restart(tmp_path):
    store = AccountStore(tmp_path, info())
    store.begin("entry:1", {"magic": 42, "symbol": "EURUSD"})
    store = AccountStore(tmp_path, info())
    assert store.unresolved() == ["entry:1"]
    with pytest.raises(ValueError):
        store.begin("entry:1", {})
    store.result("entry:1", NS(retcode=10009, deal=50, order=150))
    store.reconcile(info(), [deal(50)], [], NOW)
    assert store.unresolved() == []
    assert store.data["intents"]["entry:1"]["deals"] == [50]


def test_unknown_send_is_not_mistaken_for_rejection(tmp_path):
    store = AccountStore(tmp_path, info())
    store.begin("unknown", {})
    store.result("unknown", None)
    store.reconcile(info(), [], [], NOW)
    assert store.unresolved() == ["unknown"]
    store.begin("refused", {})
    store.result("refused", NS(retcode=10027))
    store.reconcile(info(), [], [], NOW)
    assert store.data["intents"]["refused"]["status"] == "rejected"


def test_unavailable_history_or_corrupt_file_cannot_erase_history(tmp_path):
    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [deal(1)], [], NOW)
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.reconcile(info(), None, [], NOW)
    with pytest.raises(ValueError):
        store.reconcile(info(login=8), [], [], NOW)
    assert store.path.read_bytes() == before
    store.path.write_text("broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        AccountStore(tmp_path, info())


def test_cash_movements_are_excluded_from_profit(tmp_path):
    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [deal(1, type=2, profit=1000, commission=0, fee=0)], [], NOW)
    assert store.performance()["deal_totals"]["net_realized"] == 0


def test_cost_timed_backtest_equity_books_fees_swap_and_final_exit():
    from quant.backtest import mtm_equity

    times = pd.date_range("2026-01-05", periods=4, freq="h", tz="UTC")
    trades = pd.DataFrame([dict(entry_time=str(times[0]), exit_time=str(times[-1]),
        entry=1, sl=.9, direction="SHORT", risk_usd=10, pnl_usd=-4,
        entry_commission=1, short_spread_usd=.5,
        swap_events=json.dumps([[str(times[1]), -1]]))])
    tape = pd.DataFrame({"time": times[:3], "close": [1, 1, 1]})
    curve = mtm_equity({"EURUSD": trades}, {"EURUSD": tape}, 100, accrue_costs=True)
    assert curve.usd.tolist() == [98.5, 97.5, 97.5, 96]


def test_entry_is_durable_before_send_and_cannot_be_resent_after_restart(tmp_path):
    from quant import trader
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5()
    store = AccountStore(tmp_path, info())
    original = mt5.order_send

    def send(request):
        saved = json.loads(store.path.read_text(encoding="utf-8"))
        assert saved["intents"]["42:EURUSD:123"]["status"] == "pending"
        return original(request)

    mt5.order_send = send
    plan = {"lots": .01, "sl": 1.09, "tp": 1.12, "risk_usd": 1,
            "stop_dist": .01, "tp_dist": .02}
    kwargs = dict(magic=42, dry=False, journal_path=tmp_path / "journal.csv", mem={})
    assert trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
                               account_store=store, **kwargs).startswith("ORDER pos=")
    restarted = AccountStore(tmp_path, info())
    assert "UNCONFIRMED" in trader._send_or_plan(
        mt5, "EURUSD", "EURUSD", "LONG", plan, "124", NOW, account_store=restarted, **kwargs)
    assert len(mt5.sent) == 1
    restarted.reconcile(info(), [deal(55, order=56)], [], NOW)
    assert restarted.unresolved() == []


def test_recording_failure_prevents_send_and_dry_run_is_not_a_fill(tmp_path, monkeypatch):
    from quant import trader
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5()
    store = AccountStore(tmp_path, info())
    plan = {"lots": .01, "sl": 1.09, "tp": 1.12, "risk_usd": 1,
            "stop_dist": .01, "tp_dist": .02}
    monkeypatch.setattr(store, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    result = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
        magic=42, dry=False, journal_path=tmp_path / "journal.csv", mem={}, account_store=store)
    assert "nothing sent" in result and mt5.sent == []
    dry_store = AccountStore(tmp_path, info())
    result = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
        magic=42, dry=True, journal_path=tmp_path / "journal.csv", mem={}, account_store=dry_store)
    assert "dry-run" in result
    assert dry_store.data["intents"] == {} and mt5.sent == []


def test_monitor_history_failure_still_runs_protective_management(tmp_path, monkeypatch):
    from quant import monitor, records, limits
    from quant.performance import PerformanceSettings

    mt5 = NS(initialize=lambda **kw: True, shutdown=lambda: None,
             account_info=info, history_deals_get=lambda *args: None,
             positions_get=lambda: ())
    account = NS(login=7, server="Mock/Broker", password="synthetic", live=False)
    expected = {"login": 7, "server": "Mock/Broker", "live": False}
    config = {"expected_account": expected, "dry": False}
    args = NS(bars=10, magic=42, records_dir=tmp_path, memory_dir=tmp_path,
              record_performance=True, performance_settings=PerformanceSettings())
    monkeypatch.setattr(monitor, "poll", lambda *a, **kw: ([], {}))
    monkeypatch.setattr(records, "sync_closed_positions", lambda *a, **kw: 0)
    monkeypatch.setattr(limits, "evaluate", lambda *a, **kw: {})
    passes = []
    monkeypatch.setattr(monitor, "_trade_pass", lambda *a: passes.append(a[4]["recording_error"]))
    monitor._cycle(mt5, [account], [], args, {}, 10, config)
    assert passes == [True]


@pytest.mark.parametrize("amount", [100, -50])
def test_cashflow_milliseconds_do_not_turn_deposit_or_withdrawal_into_return(tmp_path, amount):
    from quant.performance import PerformanceSettings

    store = AccountStore(tmp_path, info())
    baseline = pd.Timestamp("2026-10-23T12:00:00.500000Z")
    event = baseline + pd.Timedelta(milliseconds=300)
    store.reconcile(info(), [], [], baseline)
    movement = deal(1, type=2, profit=amount, commission=0, fee=0,
                    time=int(event.timestamp()), time_msc=event.value // 1_000_000)
    for day in ("2026-10-26T12:00:00.500000Z", "2026-10-27T12:00:00.500000Z"):
        store.reconcile(info(equity=100 + amount, balance=100 + amount), [movement], [], pd.Timestamp(day))
    result = store.performance(PerformanceSettings(minimum_observations=2))
    assert result["annualized_return"] == pytest.approx(0)
    assert result["max_drawdown_pct"] == pytest.approx(0)
    assert result["sharpe_ratio"] is None
    assert result["deal_totals"]["net_realized"] == 0


@pytest.mark.parametrize("milliseconds", [None, 0])
def test_cashflow_legacy_seconds_fallback(tmp_path, milliseconds):
    from quant.performance import PerformanceSettings

    store = AccountStore(tmp_path, info())
    store.reconcile(info(), [], [], NOW)
    event = pd.Timestamp("2026-10-26T11:00:00Z")
    movement = deal(1, type=2, profit=100, commission=0, fee=0,
                    time=int(event.timestamp()), time_msc=milliseconds)
    for day in ("2026-10-26T12:00:00Z", "2026-10-27T12:00:00Z"):
        store.reconcile(info(equity=200, balance=200), [movement], [], pd.Timestamp(day))
    result = store.performance(PerformanceSettings(minimum_observations=2))
    assert result["annualized_return"] == pytest.approx(0)


@pytest.mark.parametrize("changed", [{"balance": 200, "equity": 200}, {"credit": 50}, {"login": 8}])
def test_snapshot_rejects_account_or_capital_change_during_history_query(tmp_path, changed):
    store = AccountStore(tmp_path, info())
    reads = iter([info(), info(**changed)])
    mt5 = NS(account_info=lambda: next(reads), history_deals_get=lambda *a: (), positions_get=lambda: ())
    with pytest.raises(ValueError, match="changed during snapshot"):
        store.sync_from_broker(mt5)
    assert store.data["snapshots"] == []
    assert not store.path.exists()


def test_snapshot_uses_equity_from_before_history_query(tmp_path):
    store = AccountStore(tmp_path, info())
    reads = iter([info(equity=101), info(equity=102)])
    query_windows = []
    mt5 = NS(account_info=lambda: next(reads), positions_get=lambda: ())
    mt5.history_deals_get = lambda start, end: query_windows.append((start, end)) or ()
    store.sync_from_broker(mt5)
    snapshot = store.data["snapshots"][0]
    assert snapshot["equity"] == 101
    assert query_windows[0][0] < pd.Timestamp(snapshot["time"]) <= query_windows[0][1]


def test_definite_rejections_retry_after_restart_without_losing_audit(tmp_path):
    store = AccountStore(tmp_path, info())
    store.begin("same-bar", {"attempt": 1})
    store.result("same-bar", NS(retcode=10027, deal=0, order=0))
    restarted = AccountStore(tmp_path, info())
    restarted.begin("same-bar", {"attempt": 2})
    assert restarted.unresolved() == ["same-bar"]
    assert restarted.data["intents"]["same-bar"]["attempts"][0]["response"]["retcode"] == 10027
    restarted.result("same-bar", NS(retcode=10009, deal=50, order=150))
    restarted.reconcile(info(), [deal(50)], [], NOW)
    assert restarted.unresolved() == []
    with pytest.raises(ValueError):
        restarted.begin("same-bar", {"attempt": 3})


@pytest.mark.parametrize("response", [None, NS(retcode=10012), NS(retcode=10010), NS(retcode=10008)])
def test_uncertain_or_partial_response_never_authorizes_retry(tmp_path, response):
    store = AccountStore(tmp_path, info())
    store.begin("same-bar", {})
    store.result("same-bar", response)
    restarted = AccountStore(tmp_path, info())
    with pytest.raises(ValueError):
        restarted.begin("same-bar", {})
    assert restarted.unresolved() == ["same-bar"]


@pytest.mark.parametrize("failure", ["no tick", "account mismatch", "entry preparation failed"])
def test_local_refusal_is_retryable_but_not_an_unknown_send(tmp_path, monkeypatch, failure):
    from quant import trader
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5()
    store = AccountStore(tmp_path, info())
    if failure in ("no tick", "entry preparation failed"):
        original_tick = mt5.symbol_info_tick
        def unavailable_tick(symbol):
            if failure == "entry preparation failed":
                raise RuntimeError("mock quote failure")
            return None
        monkeypatch.setattr(mt5, "symbol_info_tick", unavailable_tick)
    else:
        checks = iter([True, False])
        monkeypatch.setattr(trader, "account_matches", lambda *a: next(checks))
    plan = {"lots": .01, "sl": 1.09, "tp": 1.12, "risk_usd": 1,
            "stop_dist": .01, "tp_dist": .02}
    memory = {"crossovers": {"EURUSD": {"used": 0}}}
    kwargs = dict(magic=42, dry=False, journal_path=tmp_path / "journal.csv", mem=memory,
                  crossover=True, memory_path=tmp_path / "memory.json")
    result = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
                                 account_store=store, **kwargs)
    assert failure in result and "nothing sent" in result
    assert mt5.sent == [] and store.unresolved() == []
    assert store.data["intents"]["42:EURUSD:123"]["status"] == "not_sent"
    assert "pending_bar" not in trader.load_mem(kwargs["memory_path"])["crossovers"]["EURUSD"]
    if failure in ("no tick", "entry preparation failed"):
        monkeypatch.setattr(mt5, "symbol_info_tick", original_tick)
    else:
        monkeypatch.setattr(trader, "account_matches", lambda *a: True)
    restarted = AccountStore(tmp_path, info())
    result = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
                                 account_store=restarted, **kwargs)
    assert result.startswith("ORDER pos=") and len(mt5.sent) == 1
    assert restarted.data["intents"]["42:EURUSD:123"]["attempts"][0]["status"] == "not_sent"


def test_trader_retries_definite_rejection_on_same_bar(tmp_path):
    from quant import trader
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5(fail_open=True)
    store = AccountStore(tmp_path, info())
    plan = {"lots": .01, "sl": 1.09, "tp": 1.12, "risk_usd": 1,
            "stop_dist": .01, "tp_dist": .02}
    kwargs = dict(magic=42, dry=False, journal_path=tmp_path / "journal.csv", mem={})
    assert trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
        account_store=store, **kwargs).startswith("ORDER FAILED")
    mt5.fail_open = False
    restarted = AccountStore(tmp_path, info())
    assert trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
        account_store=restarted, **kwargs).startswith("ORDER pos=")
    assert len(mt5.sent) == 2


def test_transport_exception_remains_uncertain_and_cannot_retry(tmp_path, monkeypatch):
    from quant import trader
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5()
    store = AccountStore(tmp_path, info())
    plan = {"lots": .01, "sl": 1.09, "tp": 1.12, "risk_usd": 1,
            "stop_dist": .01, "tp_dist": .02}

    def unknown_send(request):
        raise RuntimeError("mock lost connection after send")

    monkeypatch.setattr(mt5, "order_send", unknown_send)
    kwargs = dict(magic=42, dry=False, journal_path=tmp_path / "journal.csv", mem={})
    with pytest.raises(RuntimeError, match="lost connection"):
        trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
                            account_store=store, **kwargs)
    restarted = AccountStore(tmp_path, info())
    assert restarted.unresolved() == ["42:EURUSD:123"]
    message = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
                                  account_store=restarted, **kwargs)
    assert "ORDER UNCONFIRMED" in message and "nothing sent" in message
