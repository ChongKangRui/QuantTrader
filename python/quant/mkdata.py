"""Build data/<SYM>_H1.csv from DAT_MT_<SYM>_M1_*.csv (HistData-style M1).

M1 format: no header, `YYYY.MM.DD,HH:MM,open,high,low,close,volume`.
Timestamps are used as-is and labeled UTC (source timezone is undocumented;
whole-hour offsets do not change H1 buckets, so H1 rules are unaffected).
Hours aggregate only present minutes: nothing is fabricated, and the coverage
report flags short hours (<60 minutes) instead of filling them.
"""
from __future__ import annotations

import argparse
from datetime import timezone
from pathlib import Path

import pandas as pd

H1_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "n_minutes"]


def load_m1(src_dir: str | Path, symbol: str) -> pd.DataFrame:
    """Concatenate yearly M1 files for one symbol, sorted, deduped."""
    files = sorted(Path(src_dir).glob(f"DAT_MT_{symbol}_M1_*.csv"))
    if not files:
        raise FileNotFoundError(f"no M1 files for {symbol} in {src_dir}")
    frames = []
    for f in files:
        df = pd.read_csv(f, header=None,
                         names=["date", "clock", "open", "high", "low", "close", "tick_volume"])
        df["time"] = pd.to_datetime(df["date"] + " " + df["clock"],
                                     format="%Y.%m.%d %H:%M", utc=True)
        frames.append(df[["time", "open", "high", "low", "close", "tick_volume"]])
    m1 = pd.concat(frames, ignore_index=True).drop_duplicates(subset="time")
    return m1.sort_values("time").reset_index(drop=True)


def to_h1(m1: pd.DataFrame) -> pd.DataFrame:
    """Floor minutes to the hour. open=first, high=max, low=min, close=last."""
    m1 = m1.copy()
    m1["bar"] = m1["time"].dt.floor("h")
    g = m1.groupby("bar")
    h1 = pd.DataFrame({
        "time": g["time"].apply(lambda s: s.iloc[0]).values,
        "open": g["open"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
        "tick_volume": g["tick_volume"].sum().values,
        "n_minutes": g.size().values,
    })
    h1["time"] = pd.to_datetime(h1["time"], utc=True)
    return h1.sort_values("time").reset_index(drop=True)


def coverage(m1: pd.DataFrame, h1: pd.DataFrame) -> pd.DataFrame:
    """Per-year present minutes, formed hours, and short-hour share."""
    m1 = m1.copy()
    m1["year"] = m1["time"].dt.year
    h1c = h1.copy()
    h1c["year"] = h1c["time"].dt.year
    rows = []
    for year, grp in m1.groupby("year"):
        hrs = h1c[h1c["year"] == year]
        rows.append({"year": int(year), "minutes": len(grp), "hours": len(hrs),
                     "short_hours": int((hrs["n_minutes"] < 60).sum()),
                     "first": str(grp["time"].iloc[0]), "last": str(grp["time"].iloc[-1])})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build H1 CSV from M1 files.")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--src", default="data")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    src = Path(args.src) / args.symbol if (Path(args.src) / args.symbol).is_dir() else Path(args.src)
    try:
        m1 = load_m1(src, args.symbol)
    except FileNotFoundError as exc:
        print(f"SKIP {args.symbol} - {exc}", flush=True)
        return 2
    h1 = to_h1(m1)
    out = Path(args.out or f"data/{args.symbol}_H1.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    h1.to_csv(out, index=False)
    print(f"wrote {out}: {len(h1)} H1 bars from {len(m1)} M1 minutes", flush=True)
    print(coverage(m1, h1).to_string(index=False), flush=True)
    short = int((h1["n_minutes"] < 60).sum())
    print(f"short hours (<60 min): {short} ({short / max(len(h1), 1):.1%})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
