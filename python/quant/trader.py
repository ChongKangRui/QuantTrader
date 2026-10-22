"""Live trading legs for `quant.monitor --trade` (STRATEGY sections 8/14).

All thresholds live in `_base.yaml`; this module is only mechanics:
bar dedupe, position adoption/sync, portfolio caps, entry planning (the SAME
math as the backtest via quant/rules), entry send with broker-side SL/TP,
and trail/BE management. MetaTrader5 is mocked in tests; MT5 integer literals
(16385 H1, 16388 H4, 16408 D1 timeframe, 24 SLTP action, 10009 DONE; values
verified against the installed wheel) keep tests import-free.

Safety: nothing sends unless the caller passes dry=False; `--no-dry-run`
additionally needs exactly one enabled account (enforced in monitor.py).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant import rules
from quant.journal import append_row, build_comment
from quant.limits import md_in_ranges, pair_entry_reason, week_start, read_entry_hours, entry_time_allowed
from quant.live import _find_new_position, build_request, pick_filling, snap_volume
from quant.signals import check_entry

ENTRY_IN = 0        # mt5.DEAL_ENTRY_IN
ENTRY_OUT = 1       # mt5.DEAL_ENTRY_OUT
ENTRY_OUT_BY = 3    # mt5.DEAL_ENTRY_OUT_BY (hedged close-by)
POSITION_BUY = 0    # mt5.POSITION_TYPE_BUY
TIMEFRAME_H1 = 16385   # mt5.TIMEFRAME_H1 literal (tests run without the wheel)
TIMEFRAME_H4 = 16388   # mt5.TIMEFRAME_H4 literal
TIMEFRAME_D1 = 16408   # mt5.TIMEFRAME_D1 literal
ACTION_SLTP = 24       # mt5.TRADE_ACTION_SLTP literal
RETCODE_DONE = 10009   # mt5.TRADE_RETCODE_DONE literal

CTX_KEYS = ("symbol", "direction", "entry", "stop_dist", "risk_usd", "lots",
            "init_sl", "journaled", "open_time")


# ---------------------------------------------------------------- run memory

def load_mem(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {"bars": {}, "open": {}}
    except (FileNotFoundError, ValueError):
        return {"bars": {}, "open": {}}


def save_mem(path: str | Path, mem: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(mem, indent=1), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------- lookups

def our_positions(mt5, magic: int, symbol: str | None = None) -> list:
    """Open positions of our magic — terminal-wide, or filtered to one symbol."""
    try:
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    except Exception:
        return []
    return [p for p in (pos or ()) if int(getattr(p, "magic", -1) or -1) == magic]


def net_ccy(positions: list) -> dict[str, int]:
    """Per-currency net count of our open positions (long EURUSD = +EUR/-USD)."""
    net: dict[str, int] = {}
    for p in positions:
        sym = str(getattr(p, "symbol", ""))
        s = 1 if int(getattr(p, "type", -1)) == POSITION_BUY else -1
        net[sym[:3].upper()] = net.get(sym[:3].upper(), 0) + s
        net[sym[3:].upper()] = net.get(sym[3:].upper(), 0) - s
    return net


def positions_breach(open_positions: list, symbol: str, direction: str,
                     max_total: int, max_ccy: int) -> str | None:
    """Portfolio gate BEFORE admitting a new candidate. Breach name or None."""
    if max_total > 0 and len(open_positions) >= max_total:
        return "cap-total"
    if max_ccy > 0:
        base, quote = symbol[:3].upper(), symbol[3:].upper()
        sgn = 1 if direction.upper() == "LONG" else -1
        net = net_ccy(open_positions)
        if abs(net.get(base, 0) + sgn) > max_ccy or abs(net.get(quote, 0) - sgn) > max_ccy:
            return "cap-ccy"
    return None


def opened_positions_today(deals, magic: int, day_ts: float) -> int:
    """How many of OUR positions opened since `day_ts` (daily entry cap)."""
    pids = set()
    for d in deals:
        m = getattr(d, "magic", None)
        if m is None or int(m) != magic:
            continue
        e = getattr(d, "entry", None)
        if e is None or int(e) != ENTRY_IN:
            continue
        t = getattr(d, "time", None)
        if t is not None and float(t) >= day_ts:
            pids.add(int(getattr(d, "position_id", 0) or 0))
    return len(pids)


def fill_in_window(now_utc: datetime, ranges: list) -> bool:
    """Is a fill today (UTC calendar day) inside a no-trade range?"""
    return bool(ranges) and md_in_ranges(now_utc.strftime("%m-%d"), ranges)


def pair_history_reason(mt5, deals, magic: int, symbol: str, now: datetime,
                        max_week: int, stop_after_loss: bool) -> str | None:
    """Recover pair guards from deals, including entry fees and manual closes.

    Query complete position histories for today's exits: a trade may have
    opened before the rolling account-history window. Partial exits do not
    trigger the daily stop until the position is fully closed.
    """
    if deals is None:
        raise ValueError("deal history unavailable")
    now = now.astimezone(timezone.utc)
    day_ts = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    week_ts = week_start(now).timestamp()
    entries = {int(d.position_id) for d in deals
               if getattr(d, "magic", None) == magic
               and getattr(d, "symbol", "") == symbol
               and getattr(d, "entry", -1) == ENTRY_IN
               and week_ts <= float(d.time) <= now.timestamp()}
    lost_today = False
    if stop_after_loss:
        exits = {int(d.position_id) for d in deals
                 if getattr(d, "symbol", "") == symbol
                 and getattr(d, "entry", -1) in (ENTRY_OUT, ENTRY_OUT_BY)
                 and day_ts <= float(d.time) <= now.timestamp()}
        for pid in exits:
            history = mt5.history_deals_get(position=pid)
            if not history:
                raise ValueError(f"position {pid} history unavailable")
            ins = [d for d in history if getattr(d, "entry", -1) == ENTRY_IN]
            if not ins:
                raise ValueError(f"position {pid} entry history missing")
            if not any(getattr(d, "magic", None) == magic for d in ins):
                continue
            outs = [d for d in history
                    if getattr(d, "entry", -1) in (ENTRY_OUT, ENTRY_OUT_BY)]
            if sum(float(d.volume) for d in outs) + 1e-9 < sum(
                    float(d.volume) for d in ins):
                continue
            net = sum(float(getattr(d, k, 0) or 0)
                      for d in history for k in ("profit", "commission", "swap", "fee"))
            if net < -1e-9:
                lost_today = True
                break
    return pair_entry_reason(len(entries), lost_today, max_week, stop_after_loss)


def cost_bits(symbol: str, info, costs: dict) -> tuple[float, float]:
    """(spread price, slippage price) in the same units as the engine."""
    point = pip_point(symbol) / 10.0
    spread_px = float(getattr(info, "spread", 0) or 0) * point
    slip_px = float(costs.get("slippage_pips", 0.3)) * pip_point(symbol)
    return spread_px, slip_px


def pip_point(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def tick_pair(info) -> tuple[float, float]:
    """(tick_size, tick_value per 1.0 lot) in the engine's convention."""
    fallback = pip_point(str(getattr(info, "symbol", ""))) / 10.0
    size = float(getattr(info, "trade_tick_size", 0) or getattr(info, "point", fallback))
    value = float(getattr(info, "trade_tick_value", 0) or 0.0)
    return size, value


# --------------------------------------------------------------- trade notes

def note(journal_path, *, symbol: str, ticket: int, volume: float, direction: str,
         trigger: str, reason: str, entry: str = "", sl: float = 0.0, tp: float = 0.0,
         dry: bool = False, magic: int = "", risk_usd: float = 0.0) -> None:
    """One journal row (plan / entry / adopt / close / trail bookkeeping)."""
    append_row(journal_path, {
        "symbol": symbol, "direction": direction, "trigger": trigger,
        "entry": entry, "sl": sl, "tp": tp, "lot": volume,
        "magic": magic, "comment": build_comment(direction, trigger.upper()),
        "ticket": "", "dry_run": dry, "position": ticket,
        "risk_usd": round(risk_usd, 2), "reason": reason,
        "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")})


def journal_by_position(journal_path) -> dict[int, dict]:
    """{position id: latest journal row} for rows that carry a position id."""
    path = Path(journal_path)
    out: dict[int, dict] = {}
    if not path.exists():
        return out
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get("position") or "").strip()
                if raw.isdigit():
                    out[int(raw)] = {k: (v or "") for k, v in row.items()}
    except Exception:
        return out
    return out


# ------------------------------------------------------------------ adoption

def adopt_ctx(positions: list, journal_rows: dict[int, dict], info) -> dict[int, dict]:
    """Rebuild trade context for restart-safe management.

    Initial stop distance / 1R come from the position's journal row when one
    exists (written at entry time); without a row (an orphan under our magic)
    the stop distance derives from the CURRENT sl — exact only until a trail
    has moved it, which the adopt journal row then says loudly.
    """
    tick_size, tick_value = tick_pair(info)
    ctx: dict[int, dict] = {}
    for pos in positions:
        ticket = int(pos.ticket)
        row = journal_rows.get(ticket) or {}
        entry = float(row.get("entry") or getattr(pos, "price_open", 0) or 0)
        sl_now = float(getattr(pos, "sl", 0) or 0)
        init_sl = float(row.get("sl") or 0)
        long = int(pos.type) == POSITION_BUY
        stop_dist = abs(entry - init_sl) if init_sl else abs(entry - sl_now)
        risk = float(row.get("risk_usd") or 0) or rules.risk_usd(
            stop_dist, tick_size, tick_value, float(pos.volume or 0.01))
        ctx[ticket] = {"symbol": str(info.symbol),
                       "direction": "BUY" if long else "SELL",
                       "entry": entry, "stop_dist": stop_dist, "risk_usd": risk,
                       "lots": float(pos.volume or 0.01), "best": entry,
                       "init_sl": init_sl or (entry - stop_dist if long
                                              else entry + stop_dist),
                       "journaled": bool(row),
                       "open_time": int(getattr(pos, "time", 0) or 0)}
    return ctx


def sync_book(mt5, magic: int, symbol: str, info, params: dict,
              journal_rows: dict[int, dict], mem: dict, journal_path) -> dict:
    """Refresh the one-symbol position book; journal the edges exactly once.

    - new ticket WITH a journal row  -> joins the book silently (the earlier
      run wrote the entry row; we continue managing it).
    - new ticket WITHOUT any journal row -> orphan: adopt with one loud row.
    - book ticket gone from the terminal -> broker closed it: one "close" row,
      then it leaves the book (records sync records the full detail later).
    """
    live_ctx = adopt_ctx(our_positions(mt5, magic, symbol), journal_rows, info)
    book = {k: v for k, v in (mem.get("open") or {}).items() if v.get("symbol") == symbol}
    for ticket_str, ghost in list(book.items()):  # tracked but gone
        if int(ticket_str) not in live_ctx:
            note(journal_path, symbol=symbol, ticket=int(ticket_str),
                 volume=float(ghost.get("lots", 0.01)), direction=ghost.get("direction", ""),
                 trigger="close",
                 reason=f"pos {ticket_str} no longer in the terminal (broker closed it)")
            del book[ticket_str]
    for ticket, c in live_ctx.items():
        key = str(ticket)
        if book.get(key):  # refresh broker-side numbers, keep our best-price trail
            book[key].update({k: c[k] for k in CTX_KEYS})
            continue
        book[key] = dict(c)
        if not c["journaled"] and ticket not in journal_rows:
            note(journal_path, symbol=symbol, ticket=ticket, volume=c["lots"],
                 direction=c["direction"], trigger="adopt", entry=f'{c["entry"]:.5g}',
                 risk_usd=c["risk_usd"],
                 reason=f"adopted pos {ticket} with NO prior journal row - context "
                        f"derived from current SL (loses trail history)")
    others = {k: v for k, v in (mem.get("open") or {}).items()
              if v.get("symbol") != symbol}  # keep other symbols' books intact
    mem["open"] = {**others, **book}
    return mem


# -------------------------------------------------------------- entry decide

def plan_entry(direction: str, fill: float, atr: float, symbol: str, info,
               params: dict, costs: dict, scope_low: float, scope_high: float,
               max_cost_ratio: float, risk_target: float = 0.0,
               stop_sizing: dict | None = None, default_lot: float | None = None
               ) -> tuple[dict | None, str]:
    """Shared-math entry plan. Returns (plan|None, gate-fail reason).

    Longs buy the ask, shorts sell the bid; stop/tp attach broker-side so they
    outlive restarts. All thresholds via params/costs/scope args (=_base.yaml).
    risk_target > 0 = scaled sizing aim (balance_risk_pct x live balance,
    rules.scaled_lots); 0 = the fixed scope-floor path, identical to the
    backtest engine.
    stop_sizing (risk.stop_sizing) swaps the sizing branch: the lot is FIXED
    and the stop is widened until that lot risks scope_low, refused when the
    widening needs more than max_stop_atr x ATR. Same math as the engine
    (rules.size_stop_to_scope). Optional lot fallback uses the original stop.
    """
    long = direction == "LONG"
    stop_dist = float(params.get("stop_atr", 1.5)) * float(atr)
    spread_px, slip_px = cost_bits(symbol, info, costs)
    size, value = tick_pair(info)
    ss = stop_sizing or {}
    widen = bool(ss.get("widen_stop_to_scope"))
    lots = 0.0
    lot_fallback = False
    if widen:
        if risk_target > 0:
            return None, "config"  # percent sizing and a fixed lot cannot mix
        fixed_lot = float(default_lot if default_lot is not None else ss.get("fixed_lot", 0.01))
        if fixed_lot < 0.01:
            return None, "lot"  # below the broker minimum lot
        stop_dist, lots, why, lot_fallback = rules.size_stop_to_scope(
            stop_dist, float(atr), size, value, scope_low, scope_high, fixed_lot,
            float(ss.get("max_stop_atr") or 0.0),
            bool(ss.get("increase_lots_if_widening_fails")))
        if why is not None:
            return None, why
        # the broker refuses a stop closer than trade_stops_level: catch it here
        min_dist = float(getattr(info, "trade_stops_level", 0) or 0) * (pip_point(symbol) / 10.0)
        if stop_dist < min_dist:
            return None, "stops-level"
    if not rules.cost_ok(stop_dist, spread_px, slip_px, max_cost_ratio):
        return None, "cost"
    if not widen:
        step = rules.step_risk(stop_dist, size, value)
        if risk_target > 0:
            lots, risk, why = rules.scaled_lots(
                step, risk_target, scope_low, scope_high,
                default_lot if default_lot is not None else 0.01)
            if why is not None:
                return None, "scope"  # fence refused the scaled aim (high/low/empty)
        else:
            lots, risk, why = rules.scope_lots(
                step, scope_low, scope_high, default_lot=default_lot)
            if why is not None:
                return None, why
    else:
        risk = rules.risk_usd(stop_dist, size, value, lots)
    tp_dist = rules.target_dist(stop_dist, float(params.get("tp_mult", 3.0)))
    digits = int(getattr(info, "digits", 5))
    sl = fill - stop_dist if long else fill + stop_dist
    tp = fill + tp_dist if long else fill - tp_dist
    lots = snap_volume(lots, float(info.volume_min), float(info.volume_max),
                       float(info.volume_step))
    if widen or default_lot is not None:
        # the broker may force a bigger minimum lot: re-check the risk band
        risk = rules.risk_usd(stop_dist, size, value, lots)
        if default_lot is not None and lots + 1e-9 < default_lot:
            return None, "scope"
        if scope_high > 0 and risk > scope_high + 1e-9:
            return None, "scope"
        if scope_low > 0 and risk + 1e-9 < scope_low:
            return None, "scope"
    return {"lots": lots, "risk_usd": round(risk, 2), "stop_dist": stop_dist,
            "tp_dist": tp_dist, "sl": round(sl, digits), "tp": round(tp, digits),
            "lot_fallback": lot_fallback}, ""


def send_entry(mt5, broker: str, direction: str, plan: dict, magic: int,
               filling: int) -> tuple[bool, object, float]:
    """Market entry with attached SL/TP. Returns (ok, result, fill_price)."""
    digits = int(getattr(mt5.symbol_info(broker), "digits", 5))
    tick = mt5.symbol_info_tick(broker)
    if tick is None:
        return False, None, 0.0
    long = direction == "LONG"
    fill = round(float(tick.ask if long else tick.bid), digits)
    req = build_request(mt5, symbol=broker, side="BUY" if long else "SELL",
                        volume=plan["lots"], price=fill, magic=magic,
                        filling=filling, comment=build_comment(direction, "E1"))
    req["sl"], req["tp"] = plan["sl"], plan["tp"]
    res = mt5.order_send(req)
    ok = res is not None and int(getattr(res, "retcode", -1)) == RETCODE_DONE
    if ok and getattr(res, "price", None):
        fill = round(float(res.price), digits)
    return ok, res, fill


def _gate_check(mt5, broker: str, direction: str, params: dict,
                exec_tf: str = "TIMEFRAME_H1") -> tuple[bool, str, float]:
    """E1 gate on closed execution-timeframe bars (fresh fetch; only when the
    bias points somewhere). exec_tf is the mt5 ATTRIBUTE NAME the panel
    resolved from timeframes.execution; getattr keeps mock mt5s working."""
    tf = getattr(mt5, exec_tf, TIMEFRAME_H1)
    rows = mt5.copy_rates_from_pos(broker, tf, 1, 400)
    if rows is None or len(rows) < 3:
        return False, "warmup", 0.0
    h1 = pd.DataFrame(rows)
    h1["time"] = pd.to_datetime(h1["time"], unit="s", utc=True)
    res = check_entry(h1, direction, params)
    return bool(res["signal"]), (res["fail"] or "?"), float(res["atr"] or 0.0)


def trade_on_bar(mt5, broker: str, symbol: str, direction: str, bar_secs: int,
                 now: datetime, *, magic: int, dry: bool, params: dict,
                 journal_path, mem: dict, cfg: dict, deals, ranges: list) -> str:
    """Full decision for one closed execution-timeframe bar. Returns a short tag to print.

    params = the pair's flat strategy (stop_atr, tp_mult, trail_r...). cfg:
    max_total_positions, max_ccy_net, max_trades_per_day, scope_low,
    scope_high, max_cost_ratio, costs (base+pair merged), halted.
    Every bar is evaluated at most once (mem stamp) — this IS the restart
    guard against double orders. Skipped bars stamp too, so a guard does not
    re-fire every cycle. DATA ERROR leaves the bar unstamped for a retry.
    """
    if (mem.get("bars") or {}).get(symbol) == str(bar_secs):
        return "seen"
    now = now.astimezone(timezone.utc)
    # History failures must not stamp the bar: retry without permitting an order.
    max_week = int(cfg.get("max_trades_per_pair_per_week", 0) or 0)
    stop_after_loss = bool(cfg.get("disable_pair_after_daily_loss", False))
    pair_reason = None
    if max_week > 0 or stop_after_loss:
        try:
            pair_reason = pair_history_reason(
                mt5, deals, magic, broker, now, max_week, stop_after_loss)
        except Exception as exc:
            return f"DATA ERROR - pair limits: {exc}"
    if deals is None:
        return "DATA ERROR - deal history unavailable"
    info = mt5.symbol_info(broker)
    if info is None:
        return "DATA ERROR - no symbol info"
    reason = ""
    sig_atr = 0.0
    open_all = our_positions(mt5, magic)
    if [p for p in open_all if str(getattr(p, "symbol", "")) == broker]:
        reason = "pair-open"
    elif cfg.get("halted"):
        reason = "weekly-halt"
    elif pair_reason:
        reason = pair_reason
    # sequential guards (NOT an elif chain): a non-triggered cap must still
    # let the next gate run — this bug once skipped the E1 gate entirely.
    fill_day_ts = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if not reason and int(cfg.get("max_trades_per_day", 0) or 0) > 0:
        if opened_positions_today(deals, magic, fill_day_ts) >= int(
                cfg["max_trades_per_day"]):
            reason = "cap-day"
        elif opened_positions_today(
                [d for d in deals if str(getattr(d, "symbol", "")) == broker],
                magic, fill_day_ts) >= 1:
            reason = "cap-day-pair"  # structural: 1 entry/pair/day like the engine
    if not reason and fill_in_window(now, ranges):
        reason = "window"
    if not reason and not entry_time_allowed(now, read_entry_hours(cfg)):
        reason = "entry-hours"
    if not reason:
        breach = positions_breach(open_all, symbol, direction,
                                  int(cfg.get("max_total_positions", 0) or 0),
                                  int(cfg.get("max_ccy_net", 0) or 0))
        if breach:
            reason = breach
        else:
            ok, fail, sig_atr = _gate_check(
                mt5, broker, direction, params,
                exec_tf=str(cfg.get("exec_tf") or "TIMEFRAME_H1"))
            if not ok:
                reason = f"gate {fail}"
    if not reason:
        long = direction == "LONG"
        tick = mt5.symbol_info_tick(broker)
        if tick is None:
            return "DATA ERROR - no tick"  # unstamped: retried next cycle
        risk_target = 0.0
        if bool(cfg.get("scale_lot_with_balance") or False):
            # compounding aim: balance_risk_pct % of the live account balance
            pct = float(cfg.get("balance_risk_pct") or 0.0)
            acc = mt5.account_info()
            equity = float(getattr(acc, "equity", 0) or 0) if acc is not None else 0.0
            if not (pct > 0 and equity > 0):
                return (f"DATA ERROR - scaled sizing unusable: equity={equity} "
                        f"pct={pct}")  # unstamped: retried next cycle
            risk_target = round(pct / 100.0 * equity, 2)
        plan, why = plan_entry(direction, float(tick.ask if long else tick.bid),
                               sig_atr, symbol, info, params, cfg.get("costs") or {},
                               float(cfg.get("scope_low", 0.0) or 0.0),
                               float(cfg.get("scope_high", 0.0) or 0.0),
                               float(cfg.get("max_cost_ratio", 0) or 0),
                               risk_target=risk_target,
                               stop_sizing=cfg.get("stop_sizing") or None,
                               default_lot=cfg.get("default_lot"))
        if plan is None:
            reason = why or "plan"
        else:
            return _send_or_plan(mt5, broker, symbol, direction, plan, str(bar_secs),
                                 now, magic=magic, dry=dry, journal_path=journal_path,
                                 mem=mem,
                                 before={int(p.ticket) for p in open_all})
    (mem.setdefault("bars", {}))[symbol] = str(bar_secs)
    return f"skip {reason}"


def _send_or_plan(mt5, broker: str, symbol: str, direction: str, plan: dict,
                  stamp: str, now: datetime, *, magic: int, dry: bool,
                  journal_path, mem: dict, before: set = ()) -> str:
    long = direction == "LONG"
    dir_lbl = "LONG" if long else "SHORT"
    if dry:
        (mem.setdefault("bars", {}))[symbol] = stamp
        note(journal_path, symbol=symbol, ticket=0, volume=plan["lots"],
             direction=dir_lbl, trigger="E1", entry="", sl=plan["sl"],
             tp=plan["tp"], dry=True, magic=magic, risk_usd=plan["risk_usd"],
             reason=f"dry-run plan: stop {plan['stop_dist']:.5f} tp {plan['tp_dist']:.5f} "
                    f"1R {plan['risk_usd']}$ lots {plan['lots']} (nothing sent)")
        return f"PLAN lots={plan['lots']} 1R={plan['risk_usd']}$ (dry-run)"
    info = mt5.symbol_info(broker)
    filling = pick_filling(mt5, int(getattr(info, "filling_mode", 0) or 0))
    if filling is None:
        # deterministic per-symbol problem: stamp so the bar isn't retried forever
        (mem.setdefault("bars", {}))[symbol] = stamp
        return "DATA ERROR - unsupported filling mode (bar skipped)"
    ok, res, fill = send_entry(mt5, broker, direction, plan, magic, filling)
    if not ok:
        return f"ORDER FAILED rc={getattr(res, 'retcode', 'None')}"  # bar unstamped: retry
    pos = _find_new_position(mt5, broker, set(before or ()), magic)
    if pos is None:
        # order may still have filled; stamp to prevent a second send
        (mem.setdefault("bars", {}))[symbol] = stamp
        return f"ORDER SENT but position not found (deal {getattr(res, 'deal', '')}) - CHECK TERMINAL"
    (mem.setdefault("bars", {}))[symbol] = stamp
    note(journal_path, symbol=symbol, ticket=int(pos.ticket), volume=plan["lots"],
         direction=dir_lbl, trigger="E1", entry=str(fill), sl=plan["sl"],
         tp=plan["tp"], dry=False, magic=magic, risk_usd=plan["risk_usd"],
         reason=f"sent pos={int(pos.ticket)} deal={getattr(res, 'deal', '')}")
    book = mem.setdefault("open", {})
    book[str(int(pos.ticket))] = {
        "symbol": symbol, "direction": "BUY" if long else "SELL", "entry": fill,
        "stop_dist": plan["stop_dist"], "risk_usd": plan["risk_usd"],
        "lots": plan["lots"], "best": fill, "init_sl": plan["sl"],
        "journaled": True, "open_time": int(now.timestamp())}
    return f"ORDER pos={int(pos.ticket)} lots={plan['lots']} fill={fill}"


def manage_book(mt5, broker: str, symbol: str, params: dict, magic: int, dry: bool,
                journal_path, mem: dict, journal_rows: dict) -> list[str]:
    """One management pass: refresh the book, then trail/BE armed stops.

    Stop math is the shared rules math; a move is sent only when it improves
    the broker's current SL by more than a sub-tick nudge.
    """
    msgs: list[str] = []
    info = mt5.symbol_info(broker)
    if info is None:
        return ["DATA ERROR - no symbol info (manage)"]
    tick = mt5.symbol_info_tick(broker)
    if tick is None:
        return ["DATA ERROR - no tick (manage)"]
    mem = sync_book(mt5, magic, symbol, info, params, journal_rows, mem, journal_path)
    digits = int(getattr(info, "digits", 5))
    for ticket_str, ctx in (mem.get("open") or {}).items():
        if ctx.get("symbol") != symbol:
            continue
        pos = next((p for p in our_positions(mt5, magic, broker)
                    if int(p.ticket) == int(ticket_str)), None)
        if pos is None:  # closed mid-pass; the next sync journals it
            continue
        cur_sl = float(getattr(pos, "sl", 0) or 0)
        new_sl, best, _act = trail_decision(ctx, float(tick.bid), params, cur_sl)
        ctx["best"] = best
        if new_sl is None:
            continue
        label = "be" if bool(params.get("use_be", False)) else "trail"
        new_sl = round(new_sl, digits)
        if dry:
            msgs.append(f"TRAIL(plan) pos={ticket_str}: SL {cur_sl:.5f} -> {new_sl:.5f}")
            continue
        ok, res = modify_sl(mt5, pos, new_sl)
        if ok:
            note(journal_path, symbol=symbol, ticket=int(ticket_str),
                 volume=ctx.get("lots", 0.01), direction=ctx["direction"],
                 trigger=label, entry="", sl=new_sl, dry=False, magic=magic,
                 risk_usd=ctx.get("risk_usd", 0.0),
                 reason=f"SL moved {cur_sl:.5f} -> {new_sl:.5f} (pos {ticket_str})")
            msgs.append(f"TRAIL pos={ticket_str} SL -> {new_sl:.5f}")
        else:
            msgs.append(f"TRAIL FAILED pos={ticket_str} (rc={getattr(res, 'retcode', 'None')})")
    return msgs


def trail_decision(ctx: dict, bid: float, params: dict, cur_sl: float
                   ) -> tuple[float | None, float, bool]:
    """(new_sl_or_None, updated_best, activated) from the shared math.

    Engine mirror: the trigger (be_trigger_r when use_be else trail_r) arms
    the stop; the trail keeps trail_r x risk behind the best bid-side price
    and never suggests a level still on the losing side. A sub-nudge move is
    reported as None so the broker call stays cheap.
    """
    long = ctx["direction"] == "BUY"
    entry, stop = float(ctx["entry"]), float(ctx["stop_dist"])
    best = max(float(ctx["best"] or entry), bid) if long else min(
        float(ctx["best"] or entry), bid)
    use_be = bool(params.get("use_be", False))
    use_trail = bool(params.get("use_trail", True))
    act_r = float(params.get("be_trigger_r", 1.0)) if use_be else float(
        params.get("trail_r", 1.0))
    act = rules.activated(entry, stop, best, long, act_r)
    if not act or not (use_be or use_trail):
        return None, best, act
    eff = rules.combine_stop(float(ctx["init_sl"] or (entry - stop if long
                                                      else entry + stop)),
                             entry, stop, best, long, use_be,
                             float(params.get("be_buffer", 0)), use_trail,
                             float(params.get("trail_r", 1.0)))
    nudge = stop / 100000.0 if stop else 0.0
    improved = (eff > cur_sl + nudge) if long else (eff < cur_sl - nudge)
    if cur_sl == 0:
        improved = True  # naked stop: get one attached immediately
    return (eff, best, act) if improved else (None, best, act)


def modify_sl(mt5, pos, new_sl: float) -> tuple[bool, object]:
    """Broker-side SL move (tp kept as-is). Returns (ok, result)."""
    req = {"action": ACTION_SLTP, "position": int(pos.ticket),
           "symbol": str(pos.symbol), "sl": round(float(new_sl), 8),
           "tp": float(getattr(pos, "tp", 0.0) or 0.0)}
    res = mt5.order_send(req)
    ok = res is not None and int(getattr(res, "retcode", -1)) == RETCODE_DONE
    return ok, res


__all__ = [
    "load_mem", "save_mem", "our_positions", "net_ccy", "positions_breach",
    "opened_positions_today", "fill_in_window", "cost_bits", "pip_point",
    "tick_pair", "note", "journal_by_position", "adopt_ctx", "sync_book",
    "plan_entry", "send_entry", "trade_on_bar", "_send_or_plan", "manage_book",
    "trail_decision", "modify_sl", "ENTRY_IN", "POSITION_BUY",
]
