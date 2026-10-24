"""Launcher account isolation; synthetic credentials/fake MT5, never read .env."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant import monitor, trader


@pytest.fixture
def account_config(monkeypatch):
    import dotenv

    # Suppress credential-file loading even while testing the config module itself.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    spec = importlib.util.spec_from_file_location(
        "isolated_account_config", Path("python/quant/config.py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "USE_DEMO", True)
    monkeypatch.setattr(module, "USE_REAL", True)
    calls = []
    monkeypatch.setattr(module, "_load", lambda prefix, live: calls.append(prefix) or module.Account(
        login=2 if live else 1, password="synthetic", server="Test", live=live))
    return module, calls


@pytest.mark.parametrize("selection,prefix", [("demo", "MT5_DEMO_"), ("real", "MT5_REAL_")])
def test_selection_loads_only_requested_enabled_credentials(account_config, selection, prefix):
    config, calls = account_config
    accounts = config.get_accounts(selection)
    assert calls == [prefix] and len(accounts) == 1
    assert accounts[0].live == (selection == "real")
    assert config.USE_DEMO and config.USE_REAL


@pytest.mark.parametrize("selection,flag", [("demo", "USE_DEMO"), ("real", "USE_REAL")])
def test_selection_never_enables_disabled_account(account_config, monkeypatch, selection, flag):
    config, calls = account_config
    monkeypatch.setattr(config, flag, False)
    with pytest.raises(RuntimeError, match=flag):
        config.get_accounts(selection)
    assert calls == [] and getattr(config, flag) is False


def test_unselected_account_api_keeps_existing_behavior(account_config):
    config, calls = account_config
    assert len(config.get_accounts()) == 2
    assert calls == ["MT5_DEMO_", "MT5_REAL_"]
    with pytest.raises(ValueError):
        config.get_accounts("both")


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("fault", [None, "login", "server", "trade_mode", "missing", "exception"])
def test_account_guard_checks_actual_login_server_and_broker_type(live, fault):
    info = SimpleNamespace(login=7, server="Test", trade_mode=2 if live else 0)
    expected = {"login": 7, "server": "Test", "live": live}
    if fault in ("login", "server", "trade_mode"):
        setattr(info, fault, {"login": 8, "server": "Other", "trade_mode": 1}[fault])
    def account_info():
        if fault == "exception":
            raise OSError("unavailable")
        return None if fault == "missing" else info
    assert trader.account_matches(SimpleNamespace(account_info=account_info), expected) == (fault is None)


def test_wrong_account_blocks_entry_and_modification_without_consuming_bar(tmp_path):
    from tests.test_trader import _FakeMT5, _pos, NOW

    mt5 = _FakeMT5()
    mt5.account_info = lambda: SimpleNamespace(login=8, server="Test", trade_mode=0)
    expected = {"login": 7, "server": "Test", "live": False}
    plan = {"lots": 0.01, "sl": 1.09, "tp": 1.12}
    assert not trader.send_entry(mt5, "EURUSD", "LONG", plan, 100001, 2, expected)[0]
    assert not trader.modify_sl(mt5, _pos(), 1.105, expected)[0]
    mem = {}
    message = trader._send_or_plan(mt5, "EURUSD", "EURUSD", "LONG", plan, "123", NOW,
        magic=100001, dry=False, journal_path=tmp_path / "journal.csv", mem=mem,
        expected_account=expected)
    assert "account mismatch" in message and mem == {}
    message = trader.trade_on_bar(mt5, "EURUSD", "EURUSD", "LONG", 123, NOW,
        magic=100001, dry=False, params={}, journal_path=tmp_path / "journal.csv",
        mem=mem, cfg={"expected_account": expected}, deals=[], ranges=[])
    assert "account mismatch" in message and mem == {}
    assert mt5.sent == [] and mt5.modifications == []


def test_account_change_during_request_build_is_rechecked():
    from tests.test_trader import _FakeMT5

    mt5 = _FakeMT5()
    current = {"login": 7}
    mt5.account_info = lambda: SimpleNamespace(login=current["login"], server="Test", trade_mode=0)
    tick = mt5.symbol_info_tick
    def switched(symbol):
        current["login"] = 8
        return tick(symbol)
    mt5.symbol_info_tick = switched
    expected = {"login": 7, "server": "Test", "live": False}
    assert trader.account_matches(mt5, expected)
    assert not trader.send_entry(mt5, "EURUSD", "LONG", {"lots": 0.01, "sl": 1.09, "tp": 1.12},
                                 100001, 2, expected)[0]
    assert mt5.sent == []


@pytest.mark.parametrize("live", [False, True])
def test_matching_account_permits_mock_entry_and_stop_change(live):
    from tests.test_trader import _FakeMT5, _pos

    mt5 = _FakeMT5()
    mt5.account_info = lambda: SimpleNamespace(login=7, server="Test", trade_mode=2 if live else 0)
    expected = {"login": 7, "server": "Test", "live": live}
    assert trader.send_entry(mt5, "EURUSD", "LONG", {"lots": 0.01, "sl": 1.09, "tp": 1.12},
                             100001, 2, expected)[0]
    assert trader.modify_sl(mt5, _pos(), 1.105, expected)[0]
    assert len(mt5.sent) == 1 and len(mt5.modifications) == 1


def test_workspace_lock_refuses_second_process_and_releases(tmp_path):
    path = tmp_path / "monitor.lock"
    with monitor._terminal_lock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with monitor._terminal_lock(path):
                pytest.fail("second supervisor acquired the same lock")
    with monitor._terminal_lock(path):
        pass


@pytest.mark.parametrize("selection", ["demo", "real"])
@pytest.mark.parametrize("dry", [False, True])
def test_cli_selects_one_account_and_preserves_dry_run_override(tmp_path, monkeypatch, selection, dry):
    calls, captured = [], []
    account = SimpleNamespace(login=7, password="synthetic", server="Test", live=selection == "real")
    monkeypatch.setitem(sys.modules, "quant.config", SimpleNamespace(
        get_accounts=lambda selected=None: calls.append(selected) or [account]))
    (tmp_path / "_base.yaml").write_text("live: {dry_run_default: true}\n", encoding="utf-8")
    (tmp_path / "EURUSD.yaml").write_text("symbol: EURUSD\n", encoding="utf-8")
    original_lock = monitor._terminal_lock
    monkeypatch.setattr(monitor, "_terminal_lock", lambda path: original_lock(tmp_path / "monitor.lock"))
    monkeypatch.setattr(monitor, "_load_mt5", lambda: object())
    def cycle(mt5, accounts, pairs, args, conditions, loss_pct, tcfg=None):
        captured.append(tcfg)
        assert accounts == [account]
        return [], {}, {}
    monkeypatch.setattr(monitor, "_cycle", cycle)
    argv = ["--trade", "--account", selection, "--once", "--config-dir", str(tmp_path),
            "--journal", str(tmp_path / "journal.csv"), "--memory-dir", str(tmp_path),
            "--no-dry-run"]
    if dry:
        argv.append("--dry-run")
    assert monitor.main(argv) == 0
    assert calls == [selection] and captured[0]["dry"] is dry
    assert captured[0]["expected_account"] == {"login": 7, "server": "Test", "live": selection == "real"}
    assert captured[0]["base"]["expected_account"] == captured[0]["expected_account"]


def test_wrong_account_cycle_shuts_down_without_polling_or_trading(tmp_path, monkeypatch):
    calls = []
    mt5 = SimpleNamespace(initialize=lambda **kwargs: True, shutdown=lambda: calls.append("shutdown"),
        account_info=lambda: SimpleNamespace(login=7, server="Test", trade_mode=2))
    account = SimpleNamespace(login=7, password="synthetic", server="Test", live=False)
    monkeypatch.setattr(monitor, "poll", lambda *args, **kwargs: pytest.fail("wrong account polled"))
    monkeypatch.setattr(monitor, "_trade_pass", lambda *args, **kwargs: pytest.fail("wrong account traded"))
    assert monitor._cycle(mt5, [account], [], SimpleNamespace(), {}, 15,
        {"expected_account": {"login": 7, "server": "Test", "live": False}}) == ([], {}, {})
    assert calls == ["shutdown"]


def test_batch_files_are_distinct_and_fix_account_after_forwarded_args():
    assert not Path("start-trader.bat").exists()
    for selection in ("demo", "real"):
        text = Path(f"start-trader-{selection}.bat").read_text(encoding="utf-8")
        command = next(line for line in text.splitlines() if line.startswith("uv run"))
        assert "--trade --no-dry-run %* --account " + selection in command
        assert f"--journal trades/{selection}_journal.csv" in command
        assert "set USE_REAL" not in text and "set USE_DEMO" not in text
