"""Trade record: trades/journal.csv schema plus MT5 comment builder. No MT5 import.

The on-chain MT5 comment holds a short code only (31-char limit); the full
entry reason lives in the journal row and the log so the why is never truncated.
"""
from __future__ import annotations

import csv
from pathlib import Path

COMMENT_MAX = 31  # MT5 order-comment limit

COLUMNS = [
    "time_utc",
    "symbol",
    "direction",
    "entry",
    "sl",
    "tp",
    "lot",
    "h4_bias",
    "h4_ema20",
    "h4_ema50",
    "h4_sep_atr",
    "hr1",
    "trigger",
    "spread_pts",
    "slippage_pips",
    "magic",
    "comment",
    "ticket",
    "dry_run",
    "reason",
    "position",   # broker position id (live entries/adoption); empty otherwise
    "risk_usd",   # 1R money at the initial stop, from the shared sizing math
]


def build_comment(bias: str, trigger: str = "E1", variant: str = "B1") -> str:
    """Short on-chain code, e.g. QT B1-L E1. Always within COMMENT_MAX."""
    side = {"LONG": "L", "SHORT": "S"}.get(str(bias).upper(), "N")
    return f"QT {variant}-{side} {trigger}"[:COMMENT_MAX]


def ensure_header(path: str | Path) -> Path:
    path = Path(path)
    want = ",".join(COLUMNS)
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
        return path
    with open(path, newline="", encoding="utf-8") as fh:
        first = fh.readline().rstrip("\r\n")
    if first != want:  # legacy header: just widen line 1; data rows stay in place
        body = path.read_text(encoding="utf-8").splitlines(keepends=True)
        body[0] = want + "\n"
        path.write_text("".join(body), encoding="utf-8")
    return path


def append_row(path: str | Path, row: dict) -> None:
    clean = {k: row.get(k, "") for k in COLUMNS}
    ensure_header(path)
    with open(Path(path), "a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=COLUMNS).writerow(clean)
