"""Smoke test: connect to each enabled MT5 account, print status, exit. Sends no orders.

Usage: uv run python -m quant.smoke
Requires: MT5 terminal running + logged in, .env with demo/real creds.
"""
from __future__ import annotations

import sys

import MetaTrader5 as mt5

from quant.config import USE_DEMO, USE_REAL, Account, get_accounts

CHECK_SYMBOLS = ("EURUSD", "USDJPY")  # suffix differs by broker; smoke resolves it


def resolve(symbol: str) -> str | None:
    info = mt5.symbol_info(symbol)
    if info is not None:
        return symbol
    for suffix in ("m", ".", "_m", "m.", "pro", ".pro"):
        cand = symbol + suffix
        if mt5.symbol_info(cand) is not None:
            return cand
    return None


def check_one(acct: Account) -> int:
    tag = "REAL" if acct.live else "DEMO"
    print(f"[{tag}] server={acct.server} login={acct.login}")
    if acct.live and not USE_REAL:  # pragma: no cover - defensive
        print(f"[{tag}] refusing real account without USE_REAL=true")
        return 2
    try:
        if not mt5.initialize(login=acct.login, password=acct.password, server=acct.server):
            print(f"[{tag}] initialize failed: {mt5.last_error()}")
            return 1
        info = mt5.account_info()
        if info is None:
            print(f"[{tag}] account_info failed: {mt5.last_error()}")
            return 1
        print(f"[{tag}] connected: balance={info.balance} equity={info.equity} "
              f"currency={info.currency} margin_mode={info.margin_mode} trade_allowed={info.trade_allowed}")
        for sym in CHECK_SYMBOLS:
            real = resolve(sym)
            if real is None:
                print(f"[{tag}] {sym}: NOT FOUND on this broker")
                continue
            mt5.symbol_select(real, True)
            h1 = mt5.copy_rates_from_pos(real, mt5.TIMEFRAME_H1, 1, 1)
            h4 = mt5.copy_rates_from_pos(real, mt5.TIMEFRAME_H4, 1, 1)
            print(f"[{tag}] {sym} -> {real}: H1_closed={len(h1) if h1 is not None else 0} "
                  f"H4_closed={len(h4) if h4 is not None else 0}")
        return 0
    finally:
        mt5.shutdown()
        print(f"[{tag}] shutdown done")


def main() -> int:
    print(f"USE_DEMO={USE_DEMO} USE_REAL={USE_REAL}")
    results = [check_one(a) for a in get_accounts()]
    print("SMOKE OK (no orders sent)" if all(r == 0 for r in results) else "SMOKE FAILED")
    return 0 if all(r == 0 for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
