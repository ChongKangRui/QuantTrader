"""Single-shot executor. Round-trip plumbing test only; no strategy entries yet.

Default is dry-run: prints both requests, appends one journal row with
dry_run=true, sends nothing. Real orders need --no-dry-run plus exactly one
enabled account (so demo and real can never fire together). --roundtrip opens
volume at market and closes it immediately: seconds of exposure, proving the
full order path (open fill, close fill, journal, records sync).
"""
from __future__ import annotations

import argparse
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from quant.journal import append_row, build_comment
from quant.monitor import resolve_symbol

JOURNAL_DEFAULT = "trades/journal.csv"
MAGIC_DEFAULT = 100001
DEVIATION_POINTS = 20


def snap_volume(want: float, vmin: float, vmax: float, step: float) -> float:
    """Round down to the broker step, clamped to [vmin, vmax]."""
    # Remove float noise at exact broker steps (0.03 // 0.01 can be 2).
    steps = math.floor(round(want / step, 9)) if step > 0 else 0
    lot = round(steps * step, 8)
    return max(vmin, min(vmax, lot))


def pick_filling(mt5, filling_mode: int) -> int | None:
    if filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    if filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    return None


def build_request(mt5, *, symbol: str, side: str, volume: float, price: float,
                  magic: int, filling: int, comment: str,
                  position_id: int | None = None) -> dict:
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": 0.0,
        "tp": 0.0,
        "deviation": DEVIATION_POINTS,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
        **({"position_id": position_id} if position_id is not None else {}),
    }


def _journal_base(symbol: str, side: str, lot: float, magic: int, comment: str,
                  dry_run: bool) -> dict:
    return {"symbol": symbol, "direction": "LONG" if side == "BUY" else "SHORT",
            "lot": lot, "magic": magic, "comment": comment, "dry_run": dry_run}


def _find_new_position(mt5, broker: str, before: set, magic: int):
    """First position that appeared since `before` with our magic, else None."""
    found = [p for p in (mt5.positions_get(symbol=broker) or ())
             if p.ticket not in before and int(getattr(p, "magic", -1)) == magic]
    return found[0] if found else None


def _market_close(mt5, *, broker: str, pos_ticket: int, lot: float, magic: int,
                  filling: int, digits: int, comment: str, side: str):
    """Opposite market order with position_id. Returns (ok, fill_price, result)."""
    tick = mt5.symbol_info_tick(broker)
    if tick is None:
        return False, 0.0, None
    px = round(float(tick.ask if side == "BUY" else tick.bid), digits)
    res = mt5.order_send(build_request(mt5, symbol=broker, side=side, volume=lot,
                                       price=px, magic=magic, filling=filling,
                                       comment=comment, position_id=pos_ticket))
    ok = res is not None and int(getattr(res, "retcode", -1)) == mt5.TRADE_RETCODE_DONE
    fill = round(float(getattr(res, "price", px)), digits) if ok else px
    return ok, fill, res


def roundtrip(mt5, *, symbol: str, side: str, volume: float, magic: int,
              dry_run: bool, journal_path: str | Path, account_store=None) -> int:
    """Open then close. 0 ok, 1 open failed, 2 needs closing, 3 closed/log incomplete."""
    broker = resolve_symbol(mt5, symbol)
    if broker is None:
        print(f"DATA ERROR - symbol not found: {symbol}", flush=True)
        return 1
    mt5.symbol_select(broker, True)
    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    if info is None or tick is None:
        print(f"DATA ERROR - no market data for {broker}", flush=True)
        return 1
    filling = pick_filling(mt5, int(getattr(info, "filling_mode", 0) or 0))
    if filling is None:
        print(f"DATA ERROR - unsupported filling mode on {broker}", flush=True)
        return 1
    lot = snap_volume(max(volume, 0.01),
                      float(info.volume_min), float(info.volume_max), float(info.volume_step))
    if lot <= 0:
        print(f"DATA ERROR - volume snaps to zero on {broker}", flush=True)
        return 1
    digits = int(getattr(info, "digits", 5))
    open_side = side.upper()
    close_side = "SELL" if open_side == "BUY" else "BUY"
    comment = build_comment("LONG" if open_side == "BUY" else "SHORT", "roundtrip", "RT")

    if dry_run:
        open_px = round(float(tick.ask if open_side == "BUY" else tick.bid), digits)
        print(f"DRY-RUN open {open_side} {lot:g} {broker} @ ~{open_px} "
              f"(filling={'IOC' if filling == mt5.ORDER_FILLING_IOC else 'FOK'})", flush=True)
        print(f"DRY-RUN close {close_side} {lot:g} {broker} immediately after fill", flush=True)
        row = _journal_base(broker, open_side, lot, magic, comment, True)
        row.update({"reason": "roundtrip planned (dry-run, nothing sent)",
                    "trigger": "roundtrip",
                    "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")})
        append_row(journal_path, row)
        print("DRY-RUN ok: nothing sent", flush=True)
        return 0

    before = {p.ticket for p in (mt5.positions_get(symbol=broker) or ())}
    open_px = round(float(tick.ask if open_side == "BUY" else tick.bid), digits)
    request = build_request(mt5, symbol=broker, side=open_side, volume=lot,
                            price=open_px, magic=magic, filling=filling, comment=comment)
    if account_store is not None:
        from quant.account_store import recorded_open
        result = recorded_open(mt5, account_store, request)
    else:
        result = mt5.order_send(request)
    if result is None or int(getattr(result, "retcode", -1)) != mt5.TRADE_RETCODE_DONE:
        print(f"OPEN FAILED: {result} last_error={mt5.last_error()}", flush=True)
        return 1
    time.sleep(0.5)
    pos = _find_new_position(mt5, broker, before, magic)
    if pos is None:
        print("OPEN filled but position not found; check the terminal manually", flush=True)
        return 2
    row = _journal_base(broker, open_side, lot, magic, comment, False)
    row.update({"entry": getattr(result, "price", open_px), "ticket": getattr(result, "deal", ""),
                "reason": f"roundtrip-open pos={pos.ticket}", "trigger": "roundtrip"})
    recording_failed = False
    try:
        append_row(journal_path, row)
    except Exception as exc:
        # A filled position must still be closed when journaling fails.
        recording_failed = True
        print(f"RECORDING ALERT - open journal failed: {exc}; attempting close", flush=True)

    ok, close_px, result2 = _market_close(mt5, broker=broker, pos_ticket=pos.ticket, lot=lot,
                                         magic=magic, filling=filling, digits=digits,
                                         comment=comment, side=close_side)
    if not ok:
        print(f"CLOSE FAILED on pos={pos.ticket}: {result2} last_error={mt5.last_error()} "
              f"- close it manually in the terminal NOW", flush=True)
        return 2
    row = _journal_base(broker, close_side, lot, magic, comment, False)
    row.update({"entry": getattr(result2, "price", close_px), "ticket": getattr(result2, "deal", ""),
                "reason": f"roundtrip-close pos={pos.ticket}", "trigger": "roundtrip"})
    try:
        append_row(journal_path, row)
    except Exception as exc:
        recording_failed = True
        print(f"RECORDING ALERT - close journal failed: {exc}; broker sync required", flush=True)
    if recording_failed:
        print(f"ROUNDTRIP closed pos={pos.ticket}; RECORDING INCOMPLETE - verify broker history", flush=True)
        return 3
    print(f"ROUNDTRIP ok: opened and closed pos={pos.ticket} {lot:g} {broker}", flush=True)
    return 0


def _touch_winner(mt5, pos_ticket: int, entry_side: str, entry_px: float) -> str:
    """Which bracket leg closed the position: TP / SL / unknown (price-inferred)."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    now = _dt.now(_tz.utc)
    try:
        deals = mt5.history_deals_get(now - _td(days=2), now) or ()
    except Exception:
        return "unknown"
    outs = [d for d in deals
            if int(getattr(d, "position_id", -1) or -1) == pos_ticket
            and int(getattr(d, "entry", -1) or -1) == 1]
    if not outs:
        return "unknown"
    vol = sum(float(getattr(d, "volume", 0) or 0) for d in outs)
    close_px = (sum(float(getattr(d, "price", 0) or 0) * float(getattr(d, "volume", 0) or 0)
                    for d in outs) / vol) if vol > 0 else entry_px
    if entry_side == "BUY":
        return "TP" if close_px >= entry_px else "SL"
    return "TP" if close_px <= entry_px else "SL"


def touch_close(mt5, *, symbol: str, side: str, volume: float, magic: int,
                dry_run: bool, journal_path: str | Path, distance_points: int,
                timeout: float, poll_secs: float, account_store=None) -> int:
    """Open with close SL+TP attached; broker closes on first touch.

    0 closed (by touch or timeout fallback), 1 open failed, 2 needs manual close.
    """
    broker = resolve_symbol(mt5, symbol)
    if broker is None:
        print(f"DATA ERROR - symbol not found: {symbol}", flush=True)
        return 1
    mt5.symbol_select(broker, True)
    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    if info is None or tick is None:
        print(f"DATA ERROR - no market data for {broker}", flush=True)
        return 1
    filling = pick_filling(mt5, int(getattr(info, "filling_mode", 0) or 0))
    if filling is None:
        print(f"DATA ERROR - unsupported filling mode on {broker}", flush=True)
        return 1
    lot = snap_volume(max(volume, 0.01),
                      float(info.volume_min), float(info.volume_max), float(info.volume_step))
    if lot <= 0:
        print(f"DATA ERROR - volume snaps to zero on {broker}", flush=True)
        return 1
    digits = int(getattr(info, "digits", 5))
    point = float(getattr(info, "point", 0) or 0) or 10.0 ** -digits
    stops = int(getattr(info, "trade_stops_level", 0) or 0)
    dist = max(int(distance_points), stops + 1)  # broker minimum wins
    clamp = "" if dist == int(distance_points) else f" (clamped to stops_level {stops}+1)"
    open_side = side.upper()
    ref = round(float(tick.ask if open_side == "BUY" else tick.bid), digits)
    if open_side == "BUY":
        sl, tp = round(ref - dist * point, digits), round(ref + dist * point, digits)
    else:
        sl, tp = round(ref + dist * point, digits), round(ref - dist * point, digits)
    close_side = "SELL" if open_side == "BUY" else "BUY"
    comment = build_comment("LONG" if open_side == "BUY" else "SHORT", "touch-close", "RT")

    if dry_run:
        print(f"DRY-RUN open {open_side} {lot:g} {broker} @ ~{ref} "
              f"sl={sl} tp={tp}{clamp}", flush=True)
        print("DRY-RUN then waits for a broker SL/TP touch (nothing sent)", flush=True)
        row = _journal_base(broker, open_side, lot, magic, comment, True)
        row.update({"reason": f"touch-close planned sl={sl} tp={tp} (dry-run, nothing sent)",
                    "trigger": "touch-close", "sl": sl, "tp": tp,
                    "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")})
        append_row(journal_path, row)
        print("DRY-RUN ok: nothing sent", flush=True)
        return 0

    before = {p.ticket for p in (mt5.positions_get(symbol=broker) or ())}
    req = build_request(mt5, symbol=broker, side=open_side, volume=lot,
                        price=ref, magic=magic, filling=filling, comment=comment)
    req["sl"], req["tp"] = sl, tp
    if account_store is not None:
        from quant.account_store import recorded_open
        result = recorded_open(mt5, account_store, req)
    else:
        result = mt5.order_send(req)
    if result is None or int(getattr(result, "retcode", -1)) != mt5.TRADE_RETCODE_DONE:
        print(f"OPEN FAILED: {result} last_error={mt5.last_error()}{clamp}", flush=True)
        return 1
    time.sleep(0.5)
    pos = _find_new_position(mt5, broker, before, magic)
    if pos is None:
        print("OPEN filled but position not found; check the terminal manually", flush=True)
        return 2
    entry_px = round(float(getattr(result, "price", ref)), digits)
    row = _journal_base(broker, open_side, lot, magic, comment, False)
    row.update({"entry": entry_px, "ticket": getattr(result, "deal", ""), "sl": sl, "tp": tp,
                "reason": f"touch-close-open pos={pos.ticket}", "trigger": "touch-close"})
    append_row(journal_path, row)
    print(f"OPEN ok pos={pos.ticket}: waiting for SL/TP touch (timeout {timeout:g}s){clamp}",
          flush=True)

    deadline = time.time() + max(timeout, 0)
    while time.time() < deadline:
        time.sleep(max(poll_secs, 0.1))
        alive = {p.ticket for p in (mt5.positions_get(symbol=broker) or ())}
        if pos.ticket not in alive:
            winner = _touch_winner(mt5, pos.ticket, open_side, entry_px)
            row = _journal_base(broker, close_side, lot, magic, comment, False)
            row.update({"entry": "", "ticket": "",
                        "reason": f"touch-close broker-closed {winner} pos={pos.ticket}",
                        "trigger": "touch-close"})
            append_row(journal_path, row)
            print(f"TOUCH-CLOSE ok: broker closed pos={pos.ticket} via {winner}", flush=True)
            return 0
    ok, close_px, result2 = _market_close(mt5, broker=broker, pos_ticket=pos.ticket, lot=lot,
                                         magic=magic, filling=filling, digits=digits,
                                         comment=comment, side=close_side)
    row = _journal_base(broker, close_side, lot, magic, comment, False)
    row.update({"entry": close_px, "ticket": getattr(result2, "deal", "") if result2 else "",
                "reason": f"touch-close TIMEOUT market-closed pos={pos.ticket}",
                "trigger": "touch-close"})
    append_row(journal_path, row)
    if not ok:
        print(f"CLOSE FAILED on pos={pos.ticket}: {result2} last_error={mt5.last_error()} "
              f"- close it manually in the terminal NOW", flush=True)
        return 2
    print(f"TOUCH-CLOSE timeout: no touch in {timeout:g}s, market-closed pos={pos.ticket}",
          flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Single-shot executor (round-trip test).")
    ap.add_argument("--config", required=True, help="pair yaml, e.g. configs/EURUSD.yaml")
    ap.add_argument("--roundtrip", action="store_true",
                    help="open volume at market and close it immediately")
    ap.add_argument("--touch-close", action="store_true",
                    help="open with close SL+TP attached; broker closes on first touch")
    ap.add_argument("--distance-points", type=int, default=10,
                    help="SL/TP distance in points for --touch-close")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="max seconds to wait for a touch before market-closing")
    ap.add_argument("--poll", type=float, default=2.0,
                    help="seconds between open-position checks")
    ap.add_argument("--side", choices=("buy", "sell"), default="buy")
    ap.add_argument("--volume", type=float, default=0.01)
    ap.add_argument("--magic", type=int, default=MAGIC_DEFAULT)
    ap.add_argument("--journal", default=JOURNAL_DEFAULT)
    ap.add_argument("--records-dir", default="trades")
    ap.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args(argv)

    if not args.roundtrip and not args.touch_close:
        print("No action: pass --roundtrip (open+close now) or --touch-close (SL/TP touch test).",
              flush=True)
        return 2

    import yaml

    try:
        cfg = yaml.safe_load(open(args.config, encoding="utf-8")) or {}
        symbol = str(cfg.get("symbol") or Path(args.config).stem).strip()
    except Exception as exc:
        print(f"DATA ERROR - bad config {args.config}: {exc}", flush=True)
        return 1

    from quant.config import get_account
    from quant.monitor import _load_mt5

    try:
        acct = get_account()  # exactly one account: demo and real never fire together
    except Exception as exc:
        print(f"DATA ERROR - account config: {exc}", flush=True)
        return 2
    tag = "REAL" if acct.live else "DEMO"
    if not args.dry_run:
        print(f"REAL ORDERS on {tag} {symbol} {args.side} {args.volume:g} "
              f"(roundtrip, closes immediately)", flush=True)
    mt5 = _load_mt5()
    if mt5 is None:
        print("DATA ERROR - MetaTrader5 unavailable (needs Windows + open terminal)", flush=True)
        return 2
    from contextlib import ExitStack

    resources = ExitStack()
    try:
        if not args.dry_run:
            from quant.monitor import _terminal_lock
            resources.enter_context(_terminal_lock(Path(__file__).resolve().parents[2] / "memory" / "monitor.lock"))
        if not mt5.initialize(login=acct.login, password=acct.password, server=acct.server):
            print(f"DATA ERROR - initialize failed: {mt5.last_error()}", flush=True)
            return 1
        try:
            common = dict(symbol=symbol, side=args.side.upper(), volume=args.volume,
                          magic=args.magic, dry_run=args.dry_run, journal_path=args.journal)
            store = None
            if not args.dry_run:
                from quant.account_store import AccountStore, write_performance

                info = mt5.account_info()
                if (info is None or int(info.login) != acct.login or str(info.server) != acct.server
                        or int(info.trade_mode) != (2 if acct.live else 0)):
                    print("DATA ERROR - account identity mismatch; nothing sent", flush=True)
                    return 2
                store = AccountStore(Path(args.records_dir) / "accounts", info)
                common["account_store"] = store
            if store is not None:
                store.sync_from_broker(mt5)
            try:
                if args.touch_close:
                    return touch_close(mt5, distance_points=args.distance_points,
                                       timeout=args.timeout, poll_secs=args.poll, **common)
                return roundtrip(mt5, **common)
            finally:
                if store is not None:
                    try:
                        store.sync_from_broker(mt5)
                        write_performance(store, magic=args.magic)
                    except Exception as exc:
                        print(f"RECORDING ALERT - broker sync failed: {exc}; CHECK TERMINAL", flush=True)
        finally:
            mt5.shutdown()
    except KeyboardInterrupt:
        print("Interrupted: check the terminal for any open position of our magic and close it "
              "manually if the close leg never printed ok.", flush=True)
        return 130
    finally:
        resources.close()


if __name__ == "__main__":
    raise SystemExit(main())
