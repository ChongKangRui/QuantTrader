"""Read-only check of live broker costs via the running MT5 terminal.

No orders, no account changes: symbol_select (adds the symbol to Market
Watch) + symbol_info only. Prints the current spread (points and pips) plus server swaps per 0.01 lot so the cost
model in configs can be calibrated against what the broker actually charges.
Run it whenever; session-dependent spreads are worth sampling at different
hours. Razor accounts bill commission per lot that this tool cannot see.
"""

import argparse


def _row(sym: str, info) -> str:
    """One human line per symbol from an MT5 symbol_info result (or a fallback)."""
    if info is None:
        return f"{sym}: no symbol info (check Market Watch / symbol name)"
    pip = 0.01 if "JPY" in sym else 0.0001
    spread_pips = info.spread * info.point / pip
    # server swaps are per 1.0 lot; the config cost model uses per 0.01 lot
    swap_l, swap_s = info.swap_long / 100.0, info.swap_short / 100.0
    line = (f"{sym}: spread {info.spread} points = {spread_pips:.1f} pips | "
            f"swap L/S {swap_l:+.4f} / {swap_s:+.4f} per 0.01 lot | "
            f"max lots {getattr(info, 'volume_max', '?')}")
    if info.spread == 0:
        # weekend/stale quote: the spread must be sampled in a live session
        line += "  <- 0 spread: market closed or stale, sample in a live session"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Live broker costs (read-only, no orders).")
    ap.add_argument("--config-dir", default="configs")
    args = ap.parse_args(argv)
    from quant.monitor import _load_mt5, load_pairs, read_selection

    mt5 = _load_mt5()
    if mt5 is None:
        print("MT5 not available - run this where the terminal is installed.", flush=True)
        return 1
    if not mt5.initialize():
        print(f"terminal init failed: {mt5.last_error()}", flush=True)
        return 1
    selection = read_selection(args.config_dir)
    try:
        for pr in load_pairs(args.config_dir):
            sym = pr["symbol"]
            if selection is not None and not selection.get(sym, True):
                continue
            if not mt5.symbol_select(sym, True):
                # True: add to Market Watch — False only succeeds for already-listed symbols
                print(f"{sym}: broker refused the symbol", flush=True)
                continue
            print(_row(sym, mt5.symbol_info(sym)), flush=True)
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
