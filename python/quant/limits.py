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
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEEKLY_LOSS_PCT_DEFAULT = 15.0


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
