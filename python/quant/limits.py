"""Weekly loss halt (STRATEGY.md 8A, weekly leg only). Read-only logic + JSON memory.

Halt rule: no new entries once this week's realized loss (our magic only,
profit + commission + swap on closed deals) reaches weekly_loss_pct of the
week-start equity snapshot. Open trades keep their SL/TP. The snapshot is taken
on first sight of a new week; a new week clears the halt. Week = UTC Monday
00:00 (v1 simplification; 8A says broker-server week, which needs a broker
GMT-offset setting we do not have yet).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEEKLY_LOSS_PCT_DEFAULT = 15.0


def read_entry_hours(limits: dict) -> dict:
    """Fixed-offset local entry window; absent settings preserve old behavior."""
    raw = limits.get("entry_hours", {})
    if not isinstance(raw, dict):
        raise ValueError("entry_hours must be a mapping")
    enabled = raw.get("enabled", False)
    offset = raw.get("utc_offset_hours", 8)
    if not isinstance(enabled, bool):
        raise ValueError("entry_hours.enabled must be true or false")
    if (isinstance(offset, bool) or not isinstance(offset, (int, float))
            or not math.isfinite(offset) or not -24 < offset < 24):
        raise ValueError("entry_hours.utc_offset_hours must be between -24 and 24")
    result = {"enabled": enabled, "utc_offset_hours": offset}
    for key, default in (("start", "09:15"), ("end", "23:00")):
        value = raw.get(key, default)
        if (not isinstance(value, str) or len(value) != 5 or value[2] != ":"
                or not value[:2].isdigit() or not value[3:].isdigit()
                or not 0 <= int(value[:2]) < 24 or not 0 <= int(value[3:]) < 60):
            raise ValueError(f"entry_hours.{key} must be HH:MM (00:00–23:59)")
        result[key] = value
    if result["start"] == result["end"]:
        raise ValueError("entry_hours start and end must differ; use enabled: false for all day")
    return result


def entry_time_allowed(at: datetime, hours: dict) -> bool:
    """Check fill time, start inclusive/end exclusive; support midnight wrap."""
    if not hours["enabled"]:
        return True
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("entry time must be timezone-aware")
    local = at.astimezone(timezone(timedelta(hours=hours["utc_offset_hours"])))
    clock = local.strftime("%H:%M")
    start, end = hours["start"], hours["end"]
    return start <= clock < end if start < end else clock >= start or clock < end


def read_pair_limits(limits: dict) -> dict:
    """Validate optional pair-entry limits; old configs leave both disabled."""
    cap = limits.get("max_trades_per_pair_per_week", 0)
    stop = limits.get("disable_pair_after_daily_loss", False)
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ValueError("max_trades_per_pair_per_week must be an integer >= 0")
    if not isinstance(stop, bool):
        raise ValueError("disable_pair_after_daily_loss must be true or false")
    return {"max_trades_per_pair_per_week": cap,
            "disable_pair_after_daily_loss": stop}


def pair_entry_reason(entries: int, lost_today: bool, max_week: int,
                      stop_after_loss: bool) -> str | None:
    """Shared live/backtest decision; counters contain only actual entries."""
    if stop_after_loss and lost_today:
        return "pair_daily_loss"
    if max_week > 0 and entries >= max_week:
        return "pair_week_cap"
    return None


def parse_no_trade_ranges(cfg: dict) -> list[tuple[str, str]]:
    """limits.no_trade_ranges -> [('MM-DD', 'MM-DD')]. Inclusive both ends;
    start > end means the range wraps the New Year (12-15 .. 01-01)."""
    out: list[tuple[str, str]] = []
    for item in ((cfg.get("limits") or {}).get("no_trade_ranges") or []):
        if not (isinstance(item, dict) and {"start", "end"} <= set(item)):
            raise ValueError(f"no_trade_ranges entry needs start/end: {item!r}")
        s, e = str(item["start"]).strip(), str(item["end"]).strip()
        for md in (s, e):
            mo, dd = md.split("-") if "-" in md else ("", "")
            if len(md) != 5 or md[2] != "-" or not (mo.isdigit() and dd.isdigit()) \
                    or not (1 <= int(mo) <= 12) or not (1 <= int(dd) <= 31):
                raise ValueError(f"no_trade_ranges: need MM-DD dates, got {md!r}")
        out.append((s, e))
    return out


def md_in_ranges(md: str, ranges) -> bool:
    """Is month-day `md` ('MM-DD') inside any no-trade range?"""
    for s, e in ranges:
        if s <= e:
            if s <= md <= e:
                return True
        elif md >= s or md <= e:  # wrap
            return True
    return False


def week_start(now_utc: datetime) -> datetime:
    monday = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday - timedelta(days=monday.weekday())


def week_key(now_utc: datetime) -> str:
    iso = now_utc.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_realized(deals, monday_ts: float, magic: int) -> float:
    total = 0.0
    for d in deals:
        if getattr(d, "magic", None) != magic:
            continue
        if float(getattr(d, "time", 0) or 0) < monday_ts:
            continue
        total += (float(getattr(d, "profit", 0) or 0)
                  + float(getattr(d, "commission", 0) or 0)
                  + float(getattr(d, "swap", 0) or 0))
    return round(total, 2)


def assess(state: dict, key: str, equity: float, realized: float, pct: float) -> tuple[dict, bool, float]:
    """Pure halt check. Returns (state_to_save, halted, loss_pct)."""
    if state.get("week") != key or float(state.get("start_equity", 0) or 0) <= 0:
        state = {"week": key, "start_equity": round(float(equity), 2), "realized": realized}
    else:
        state = {**state, "realized": realized}
    start = float(state["start_equity"])
    loss_pct = round(-realized / start * 100.0, 2) if start > 0 else 0.0
    return state, loss_pct >= float(pct), loss_pct


def load_state(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_state(path: str | Path, state: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def evaluate(path: str | Path, deals, magic: int, equity: float,
             pct: float, now: datetime | None = None) -> dict:
    """Weekly halt status, persisting the snapshot. Keys: week/halted/loss_pct/start_equity."""
    now = now or datetime.now(timezone.utc)
    monday = week_start(now)
    key = week_key(now)
    state = load_state(path)
    realized = week_realized(deals, monday.timestamp(), magic)
    state, halted, loss_pct = assess(state, key, equity, realized, pct)
    save_state(path, state)
    return {"week": key, "halted": halted, "loss_pct": loss_pct,
            "start_equity": state["start_equity"], "realized": realized}
