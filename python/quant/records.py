"""Closed-position records: trades/demo.csv + trades/real.csv. Read-only MT5 history.

One row per closed position (an OUT deal exists). Watermark = max ticket already
in the file, so restarts never duplicate. Only our magic number is recorded;
manual trades are ignored. Entry condition joins trades/journal.csv on ticket.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

MY_TZ = timezone(timedelta(hours=8))  # Malaysia, fixed UTC+8, no DST

COLUMNS = [
    "local_time", "broker_open", "broker_close", "symbol", "side", "volume",
    "entry_price", "close_price", "profit", "commission", "swap",
    "magic", "ticket", "entry_condition", "account",
]

DEAL_BUY, DEAL_SELL = 0, 1
ENTRY_IN, ENTRY_OUT = 0, 1
LOOKBACK_DAYS = 365


def ensure_record_header(path: str | Path) -> Path:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
    return path


def _fmt_utc(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_local(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, tz=MY_TZ).strftime("%Y-%m-%d %H:%M:%S")


def load_conditions(journal_path: str | Path) -> dict[str, str]:
    """Map journal ticket -> entry reason. Missing file means no conditions yet."""
    out: dict[str, str] = {}
    try:
        with open(journal_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                t = str(row.get("ticket", "") or "").strip()
                if t:
                    out[t] = row.get("reason", "") or row.get("comment", "")
    except FileNotFoundError:
        pass
    return out


def read_watermark(path: str | Path) -> int:
    try:
        with open(path, encoding="utf-8") as fh:
            tickets = (row.get("ticket", 0) for row in csv.DictReader(fh))
            return max((int(float(t or 0)) for t in tickets), default=0)
    except (FileNotFoundError, TypeError, ValueError):
        return 0


def _vwap(deals) -> float:
    vol = sum(float(getattr(d, "volume", 0) or 0) for d in deals)
    if vol <= 0:
        return 0.0
    return sum(float(getattr(d, "price", 0) or 0) * float(getattr(d, "volume", 0) or 0)
               for d in deals) / vol


def position_row(position_id, deals, entry_condition: str, account: str) -> dict | None:
    """One record row, or None when the position is still open (no OUT deal)."""
    ins = [d for d in deals if getattr(d, "entry", -1) == ENTRY_IN]
    outs = [d for d in deals if getattr(d, "entry", -1) == ENTRY_OUT]
    if not outs:
        return None
    out_vol = sum(float(getattr(d, "volume", 0) or 0) for d in outs)
    close_ts = max(int(getattr(d, "time", 0) or 0) for d in outs)
    out_ticket = max(int(getattr(d, "ticket", 0) or 0) for d in outs)
    if ins:
        side = "BUY" if getattr(ins[0], "type", DEAL_BUY) == DEAL_BUY else "SELL"
        entry_price: float | str = round(_vwap(ins), 5)
        open_ts = min(int(getattr(d, "time", 0) or 0) for d in ins)
        in_ticket = min(int(getattr(d, "ticket", 0) or 0) for d in ins)
    else:
        # Entry fell outside the query window: derive side from the exit deal.
        side = "SELL" if getattr(outs[0], "type", DEAL_BUY) == DEAL_BUY else "BUY"
        entry_price = ""
        open_ts = min(int(getattr(d, "time", 0) or 0) for d in outs)
        in_ticket = out_ticket
    return {
        "local_time": _fmt_local(close_ts),
        "broker_open": _fmt_utc(open_ts),
        "broker_close": _fmt_utc(close_ts),
        "symbol": getattr(outs[0], "symbol", ""),
        "side": side,
        "volume": round(out_vol, 2),
        "entry_price": entry_price,
        "close_price": round(_vwap(outs), 5),
        "profit": round(sum(float(getattr(d, "profit", 0) or 0) for d in outs), 2),
        # commission is billed on IN and OUT deals alike, so sum the whole group
        "commission": round(sum(float(getattr(d, "commission", 0) or 0) for d in deals), 2),
        "swap": round(sum(float(getattr(d, "swap", 0) or 0) for d in deals), 2),
        "magic": getattr(outs[0], "magic", ""),
        "ticket": out_ticket,
        "entry_condition": entry_condition,
        "account": account,
    }


def sync_closed_positions(mt5, path: str | Path, magic: int, conditions: dict[str, str],
                          account: str, lookback_days: int = LOOKBACK_DAYS,
                          deals=None) -> int:
    """Append newly closed positions of our magic. Returns rows appended.

    Grouping uses the FULL history, not the watermark-filtered deals: a position
    opened before the last watermark still belongs to the group its OUT deal
    closes now (its entry deal would otherwise be lost below the watermark).
    A position is fresh iff its OUT ticket is above the watermark.
    """
    path = Path(path)
    seen = read_watermark(path)
    if deals is None:
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=lookback_days), now) or ()
    groups: dict = {}
    for d in deals:  # full history, then per-position groups
        if getattr(d, "magic", None) != magic:
            continue
        groups.setdefault(getattr(d, "position_id", 0), []).append(d)
    rows = []
    for pid, ds in groups.items():
        outs = [d for d in ds if getattr(d, "entry", -1) == ENTRY_OUT]
        if not outs:
            continue
        out_ticket = max(int(getattr(d, "ticket", 0) or 0) for d in outs)
        if out_ticket <= seen:  # closed before the last sync: already recorded
            continue
        in_ticket = min((int(getattr(d, "ticket", 0) or 0) for d in ds
                         if getattr(d, "entry", -1) == ENTRY_IN), default=0)
        cond = conditions.get(str(in_ticket)) or conditions.get(str(out_ticket)) or ""
        row = position_row(pid, ds, cond, account)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: int(r["ticket"]))
    if rows:
        ensure_record_header(path)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writerows(rows)
    return len(rows)
