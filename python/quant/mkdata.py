"""Build H1 from vendor M1 files, or export actual broker candles with --broker.

M1 format: no header, `YYYY.MM.DD,HH:MM,open,high,low,close,volume`.
Timestamps are used as-is and labeled UTC (source timezone is undocumented;
whole-hour offsets do not change H1 buckets, so H1 rules are unaffected).
Hours aggregate only present minutes: nothing is fabricated, and the coverage
report flags short hours (<60 minutes) instead of filling them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

H1_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "n_minutes"]
M1_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume"]

# Standard MT5 timeframe names; monthly gaps use calendar months, not 30-day bars.
BROKER_TF_MINUTES = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6,
    "M10": 10, "M12": 12, "M15": 15, "M20": 20, "M30": 30,
    "H1": 60, "H2": 120, "H3": 180, "H4": 240, "H6": 360,
    "H8": 480, "H12": 720, "D1": 1440, "W1": 10080, "MN1": None,
}

RESEARCH_SOURCE = "vendor_derived_research"
RESEARCH_WARNING = ("RESEARCH ONLY: vendor timestamps grouped as stored, midnight-based; "
                    "source timezone unverified. Not broker candles or live validation.")


def file_signature(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        # Bounded reads also work for multi-gigabyte local feeds.
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def research_info(root: str | Path) -> dict:
    root = Path(root).resolve()
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("source_type") != RESEARCH_SOURCE or manifest.get("version") != 1:
        raise ValueError("not a supported vendor-derived research manifest")
    return {"directory": str(root), "manifest_sha256": file_digest(path),
            "source_type": RESEARCH_SOURCE, "warning": RESEARCH_WARNING}


def research_chart_path(root: str | Path, symbol: str, tf: str,
                        h1_path: str | Path) -> Path:
    """Explicit opt-in, matching source snapshots, and unchanged derived candles."""
    root = Path(research_info(root)["directory"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["symbols"][symbol]
    if Path(entry["h1"]["path"]).resolve() != Path(h1_path).resolve():
        raise ValueError(f"{symbol}: H1 input does not match research source")
    for key in ("h1", "m1"):
        signature = entry[key]
        if file_signature(Path(signature["path"])) != signature:
            raise ValueError(f"{symbol}: {key} source changed since research build")
    if tf == "H1" and tf not in entry["charts"]:
        return Path(entry["h1"]["path"])
    chart = entry["charts"][tf]
    path = (root / chart["file"]).resolve()
    if not path.is_relative_to(root) or file_digest(path) != chart["sha256"]:
        raise ValueError(f"{symbol}/{tf}: research chart path or checksum mismatch")
    return path


def _research_aggregate(minutes: pd.DataFrame, tf: str) -> pd.DataFrame:
    freq = f"{BROKER_TF_MINUTES[tf]}min"
    grouped = minutes.groupby(minutes["time"].dt.floor(freq), sort=True)
    return grouped.agg(open=("open", "first"), high=("high", "max"),
                       low=("low", "min"), close=("close", "last"),
                       tick_volume=("tick_volume", "sum"),
                       n_minutes=("time", "size")).reset_index()


def build_research_data(src: str | Path, out_dir: str | Path, *,
                         symbol: str | None = None, all_existing: bool = False,
                         timeframes=("H4", "D1"), chunk_rows: int = 100000,
                         overwrite: bool = False) -> dict:
    """Aggregate consolidated vendor M1 directly; never manufacture empty periods."""
    if all_existing == bool(symbol):
        raise ValueError("choose --symbol or --all-existing")
    if chunk_rows <= 0:
        raise ValueError("--chunk-rows must be > 0")
    src, out_dir = Path(src).resolve(), Path(out_dir).resolve()
    if src == out_dir:
        raise ValueError("research output must be separate from the source directory")
    tfs = sorted({_broker_tf(tf) for tf in timeframes})
    if not tfs or any(BROKER_TF_MINUTES[tf] is None for tf in tfs):
        raise ValueError("research aggregation needs fixed-duration timeframes (not MN1)")
    symbols = sorted(p.name[:-7] for p in src.glob("*_M1.csv")) if all_existing else [symbol]
    if not symbols:
        raise ValueError("no consolidated *_M1.csv sources")
    targets = [out_dir / "manifest.json"] + [out_dir / f"{s}_{tf}{suffix}"
        for s in symbols for tf in tfs for suffix in (".csv", ".meta.json")]
    if not overwrite and any(p.exists() for p in targets):
        raise FileExistsError("research output exists; use a fresh folder or explicit --overwrite")
    manifest = {"version": 1, "source_type": RESEARCH_SOURCE,
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "warning": RESEARCH_WARNING, "timeframes": tfs,
                "boundary_rule": "floor source timestamps as stored; 00:00 day origin; left-closed buckets",
                "symbols": {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".research-build-", dir=out_dir) as tmp:
        stage = Path(tmp)
        for sym in symbols:
            _safe_symbol(sym)
            m1_path, h1_path = src / f"{sym}_M1.csv", src / f"{sym}_H1.csv"
            signatures = {"m1": file_signature(m1_path), "h1": file_signature(h1_path)}
            carry = {tf: pd.DataFrame() for tf in tfs}
            stats = {tf: {"bars": 0, "partial_bars": 0, "empty_periods": 0,
                           "first": None, "last": None, "years": {}} for tf in tfs}
            previous, source_first, source_count, source_gaps = None, None, 0, 0

            def emit(tf, rows):
                if rows.empty:
                    return
                bars = _research_aggregate(rows, tf)
                stat = stats[tf]
                times = bars["time"]
                before = times.shift()
                if stat["last"] is not None:
                    before.iloc[0] = pd.Timestamp(stat["last"])
                missing = ((times - before).dt.total_seconds() / (BROKER_TF_MINUTES[tf] * 60) - 1)
                stat["empty_periods"] += int(missing.clip(lower=0).fillna(0).sum())
                stat["first"] = stat["first"] or times.iloc[0].isoformat()
                stat["last"] = times.iloc[-1].isoformat()
                stat["partial_bars"] += int((bars["n_minutes"] < BROKER_TF_MINUTES[tf]).sum())
                for year, group in bars.groupby(times.dt.year):
                    yearly = stat["years"].setdefault(str(year), {"bars": 0, "partial_bars": 0})
                    yearly["bars"] += len(group)
                    yearly["partial_bars"] += int((group["n_minutes"] < BROKER_TF_MINUTES[tf]).sum())
                bars.to_csv(stage / f"{sym}_{tf}.csv", mode="a" if stat["bars"] else "w",
                            header=stat["bars"] == 0, index=False)
                stat["bars"] += len(bars)

            for chunk in pd.read_csv(m1_path, chunksize=chunk_rows):
                if not set(M1_COLUMNS).issubset(chunk.columns):
                    raise ValueError(f"{sym}: missing M1 columns")
                chunk = chunk[M1_COLUMNS].copy()
                chunk["time"] = pd.to_datetime(chunk["time"], utc=True, errors="raise")
                times = chunk["time"]
                if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing \
                        or (previous is not None and times.iloc[0] <= previous):
                    raise ValueError(f"{sym}: duplicate/descending/invalid source timestamps")
                if (times != times.dt.floor("min")).any():
                    raise ValueError(f"{sym}: M1 timestamps must be minute aligned")
                for col in M1_COLUMNS[1:]:
                    chunk[col] = pd.to_numeric(chunk[col], errors="raise")
                    if not chunk[col].map(math.isfinite).all():
                        raise ValueError(f"{sym}: non-finite {col}")
                if (chunk[["open", "high", "low", "close"]] <= 0).any().any() \
                        or (chunk["tick_volume"] < 0).any() \
                        or (chunk["high"] < chunk[["open", "close", "low"]].max(axis=1)).any() \
                        or (chunk["low"] > chunk[["open", "close", "high"]].min(axis=1)).any():
                    raise ValueError(f"{sym}: invalid source prices/volume")
                deltas = times.diff()
                if previous is not None:
                    deltas.iloc[0] = times.iloc[0] - previous
                source_gaps += int((deltas > pd.Timedelta(minutes=1)).sum())
                source_first = source_first or times.iloc[0].isoformat()
                previous = times.iloc[-1]
                source_count += len(chunk)
                for tf in tfs:
                    combined = pd.concat([carry[tf], chunk], ignore_index=True) if len(carry[tf]) else chunk
                    buckets = combined["time"].dt.floor(f"{BROKER_TF_MINUTES[tf]}min")
                    last_mask = buckets == buckets.iloc[-1]
                    emit(tf, combined[~last_mask])
                    carry[tf] = combined[last_mask].copy()
            if not source_count:
                raise ValueError(f"{sym}: empty source")
            for tf in tfs:
                emit(tf, carry[tf])
            if signatures != {"m1": file_signature(m1_path), "h1": file_signature(h1_path)}:
                raise ValueError(f"{sym}: source changed during build")
            charts = {}
            for tf in tfs:
                filename = f"{sym}_{tf}.csv"
                charts[tf] = {"file": filename, "sha256": file_digest(stage / filename)}
                metadata = {"source_type": RESEARCH_SOURCE, "warning": RESEARCH_WARNING,
                            "symbol": sym, "timeframe": tf, "source": signatures,
                            "built_at_utc": manifest["built_at_utc"],
                            "boundary_rule": manifest["boundary_rule"],
                            "source_first": source_first, "source_last": previous.isoformat(),
                            "source_minutes": source_count, "source_gap_count": source_gaps,
                            "coverage_note": "Partial periods retained with n_minutes; empty periods omitted, never filled.",
                            **stats[tf]}
                (stage / f"{sym}_{tf}.meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            manifest["symbols"][sym] = {**signatures, "charts": charts, "coverage": stats}
            print(f"research {sym}: {source_count} source minutes; " + ", ".join(
                f"{tf}={stats[tf]['bars']} bars ({stats[tf]['partial_bars']} partial)" for tf in tfs), flush=True)
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if not overwrite and any(p.exists() for p in targets):
            raise FileExistsError("output appeared during build; refusing overwrite")
        for target in targets:
            (stage / target.name).replace(target)
    return manifest


def _broker_tf(value: str) -> str:
    tf = str(value).upper()
    if tf not in BROKER_TF_MINUTES:
        raise ValueError(f"unsupported broker timeframe: {value}")
    return tf


def _safe_symbol(symbol: str) -> str:
    # Symbols become filenames: allow broker suffixes, never paths or traversal.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", symbol) or ".." in symbol:
        raise ValueError(f"unsafe symbol: {symbol!r}")
    return symbol


def broker_plan(config_dir: str | Path, symbol: str | None, batch: bool,
                warmup_bars: int | None = None) -> dict:
    """Plan chart, stop-check and legacy H1/conversion feeds from shared config."""
    import yaml

    from quant.monitor import flatten_strategy, load_pairs, read_selection
    from quant.rules import USD_CONVERSION_FEEDS

    config_dir = Path(config_dir)
    base = yaml.safe_load((config_dir / "_base.yaml").read_text(encoding="utf-8-sig")) or {}
    tf = base.get("timeframes") or {}
    execution = _broker_tf(tf.get("execution", "H1"))
    regime = _broker_tf(tf.get("regime", "H4"))
    if (base.get("backtest_data") or {}).get("use_broker_csv", False):
        from quant.broker_data import resolve_position_checks
        checks = _broker_tf(resolve_position_checks(base, execution))
    else:
        checks = _broker_tf(tf.get("position_checks", execution))
    if batch == bool(symbol):
        raise ValueError("choose exactly one of --symbol or --batch")
    if batch:
        # Validate selection before reusing the loader, which otherwise tolerates bad YAML.
        selection_path = config_dir / "scan-selection.yml"
        if selection_path.exists():
            selection_cfg = yaml.safe_load(selection_path.read_text(encoding="utf-8-sig")) or {}
            if not isinstance(selection_cfg, dict) or not isinstance(selection_cfg.get("pairs", {}), dict):
                raise ValueError("scan-selection.yml needs a pairs mapping")
            for item in selection_cfg.get("pairs", {}).values():
                if not isinstance(item, dict) or not isinstance(item.get("enabled", True), bool):
                    raise ValueError("scan-selection enabled values must be true or false")
        selection = read_selection(config_dir)
        pairs = load_pairs(config_dir)
        if any(p.get("load_error") for p in pairs):
            raise ValueError("pair config unreadable; fix it before exporting")
        symbols = sorted({_safe_symbol(p["symbol"]) for p in pairs
                          if selection is None or selection.get(p["symbol"], True)})
    else:
        symbols = [_safe_symbol(symbol)]
    if not symbols:
        raise ValueError("no selected symbols")
    strategy = flatten_strategy(base)
    if warmup_bars is None:
        periods = [strategy.get(key, 0) for key in (
            "warmup_bars", "bias_ema_fast_period", "bias_ema_slow_period",
            "entry_ema_fast_period", "entry_ema_slow_period", "bias_atr_period",
            "entry_atr_period", "h4_ema_fast", "h4_ema_slow", "h1_ema_fast",
            "h1_ema_slow", "h4_atr_n", "atr_n")]
        warmup_bars = max([0] + [int(p) for p in periods])
    if warmup_bars < 0:
        raise ValueError("--warmup-bars must be >= 0")
    jobs = {(s, t) for s in symbols for t in (execution, regime, checks, "H1")}
    account_ccy = str((base.get("account") or {}).get("currency", "USD")).upper()
    if account_ccy != "USD":
        raise ValueError("current engine conversion feeds support USD accounts only")
    for s in symbols:
        # Existing engine sizes six-letter FX pairs; do not guess suffix/currency parsing.
        if not re.fullmatch(r"[A-Z]{6}", s):
            raise ValueError(f"{s}: configured symbols must be six-letter FX pairs")
        if not s.startswith("USD") and not s.endswith("USD"):
            feed = USD_CONVERSION_FEEDS.get(s[3:])
            if feed is None:
                raise ValueError(f"{s}: no supported USD conversion feed")
            jobs.add((feed, "H1"))
    clock = (base.get("backtest_data") or {}).get("broker_api_clock", "auto")
    if clock not in ("auto", "utc", "new_york_plus_7"):
        raise ValueError("broker_api_clock must be auto, utc or new_york_plus_7")
    return {"symbols": symbols, "jobs": sorted(jobs), "execution": execution,
            "regime": regime, "position_checks": checks, "warmup_bars": warmup_bars,
            "api_clock": clock}


def _utc_date(value: str) -> datetime:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError("date cannot be empty/NaT")
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).to_pydatetime()


def broker_query_date(value: datetime, clock: str = "utc") -> datetime:
    """Translate actual UTC into the epoch labels used by this broker API."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or clock not in ("utc", "new_york_plus_7"):
        raise ValueError("need an aware date and an explicit supported broker clock")
    if clock == "new_york_plus_7":
        stamp = (stamp.tz_convert("America/New_York").tz_localize(None)
                 + pd.Timedelta(hours=7)).tz_localize("UTC")
    return stamp.tz_convert("UTC").to_pydatetime()


def validate_broker_rates(rates, label: str, clock: str = "utc") -> pd.DataFrame:
    """Reject bad candles/order instead of sorting, deduplicating or filling gaps."""
    if rates is None:
        raise ValueError(f"{label}: broker returned no data (check terminal history limits)")
    df = pd.DataFrame(rates)
    if df.empty:
        return pd.DataFrame(columns=M1_COLUMNS)
    if not set(M1_COLUMNS).issubset(df.columns):
        raise ValueError(f"{label}: missing OHLC/time/volume columns")
    df = df[M1_COLUMNS].copy()
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True, errors="raise")
    if clock == "new_york_plus_7":
        from quant.broker_data import pepperstone_utc
        df["time"] = pepperstone_utc(df["time"].dt.tz_localize(None))
    elif clock != "utc":
        raise ValueError("unsupported broker API clock")
    if df["time"].isna().any() or df["time"].duplicated().any() \
            or not df["time"].is_monotonic_increasing:
        raise ValueError(f"{label}: invalid, duplicate or descending timestamps")
    for col in M1_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not df[col].map(math.isfinite).all():
            raise ValueError(f"{label}: non-finite {col}")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() \
            or (df["tick_volume"] < 0).any() \
            or (df["high"] < df[["open", "low", "close"]].max(axis=1)).any() \
            or (df["low"] > df[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError(f"{label}: invalid prices or volume")
    return df


def _expected_next(ts: pd.Timestamp, tf: str) -> pd.Timestamp:
    if tf == "MN1":
        return ts + pd.DateOffset(months=1)
    return ts + pd.Timedelta(minutes=BROKER_TF_MINUTES[tf])


def _stream_broker_csv(mt5, symbol: str, tf: str, start: datetime, end: datetime,
                       last_closed: pd.Timestamp, path: Path, chunk_days: int,
                       clock: str = "utc") -> dict:
    """Stream bounded chunks to staging; weekend/session gaps are reported, never filled."""
    cursor, count, gap_count, first, previous = start, 0, 0, None, None
    gaps = []
    empty_chunks = []
    while cursor < end:
        stop = min(cursor + timedelta(days=chunk_days), end)
        raw = mt5.copy_rates_range(symbol, getattr(mt5, f"TIMEFRAME_{tf}"),
                                   broker_query_date(cursor, clock),
                                   broker_query_date(stop - timedelta(microseconds=1), clock))
        df = validate_broker_rates(raw, f"{symbol}/{tf} {cursor.isoformat()}", clock)
        if len(df):
            if (df["time"] < pd.Timestamp(cursor)).any() or (df["time"] >= pd.Timestamp(stop)).any():
                raise ValueError(f"{symbol}/{tf}: broker returned bars outside requested chunk")
            df = df[df["time"] <= last_closed]
        if df.empty:
            empty_chunks.append({"start": cursor.isoformat(), "end_exclusive": stop.isoformat()})
        else:
            if previous is not None and df["time"].iloc[0] <= previous:
                raise ValueError(f"{symbol}/{tf}: duplicate/descending timestamps across chunks")
            before = df["time"].shift()
            if previous is not None:
                before.iloc[0] = previous
            if tf == "MN1":
                expected = pd.to_datetime(
                    before.map(lambda t: t + pd.DateOffset(months=1)), utc=True)
            else:
                expected = before + pd.Timedelta(minutes=BROKER_TF_MINUTES[tf])
            gap_mask = df["time"] > expected
            gap_count += int(gap_mask.sum())
            # Bound sidecar size for multi-year M1 exports; retain the total count.
            for idx in df.index[gap_mask][:max(0, 100 - len(gaps))]:
                gaps.append({"after": before.loc[idx].isoformat(),
                             "next": df.loc[idx, "time"].isoformat()})
            first = first if first is not None else df["time"].iloc[0]
            previous = df["time"].iloc[-1]
            df.to_csv(path, mode="a" if count else "w", header=count == 0, index=False)
            count += len(df)
        cursor = stop
    if not count:
        raise ValueError(f"{symbol}/{tf}: no closed bars in requested range")
    return {"bars": count, "first_open_utc": first.isoformat(),
            "last_open_utc": previous.isoformat(), "gap_count": gap_count,
            "gap_samples": gaps, "empty_chunks": empty_chunks,
            "leading_seconds": (first - pd.Timestamp(start)).total_seconds(),
            "trailing_seconds": max(0.0, (pd.Timestamp(end) - _expected_next(previous, tf)).total_seconds()),
            "gap_note": "Includes weekends, holidays, broker sessions and possible missing data; not filled."}


def export_broker(mt5, plan: dict, start: datetime, end: datetime, out_dir: str | Path,
                  *, chunk_days: int = 31, overwrite: bool = False) -> list[Path]:
    """Read-only current terminal; stage all files before publishing any CSVs."""
    from quant.monitor import resolve_symbol

    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("need UTC-aware start < end (end is exclusive)")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if chunk_days <= 0:
        raise ValueError("--chunk-days must be > 0")
    exported_at = datetime.now(timezone.utc)
    if end > exported_at:
        raise ValueError("--end cannot be in the future")
    out_dir = Path(out_dir)
    targets = [out_dir / f"{s}_{t}{ext}" for s, t in plan["jobs"]
               for ext in (".csv", ".meta.json")]
    if not overwrite and any(p.exists() for p in targets):
        raise FileExistsError("export would overwrite existing files; choose another --out-dir "
                              "or explicitly use --overwrite")
    try:
        if not mt5.initialize():
            raise ValueError("MT5 initialize failed; open and log in to the intended terminal")
        account = mt5.account_info()
        if account is None:
            raise ValueError("MT5 account info unavailable")
        clock = plan.get("api_clock", "auto")
        if clock == "auto":
            # Verified Pepperstone responses encode server wall clock, not UTC.
            clock = "new_york_plus_7" if "pepperstone" in str(account.server).lower() else "utc"
        if clock not in ("utc", "new_york_plus_7"):
            raise ValueError("unsupported broker API clock")
        resolved, closed = {}, {}
        for symbol, tf in plan["jobs"]:
            _safe_symbol(symbol)
            _broker_tf(tf)
            if not hasattr(mt5, f"TIMEFRAME_{tf}"):
                raise ValueError(f"installed MT5 does not support {tf}")
            if symbol not in resolved:
                broker_symbol = resolve_symbol(mt5, symbol)
                if broker_symbol is None or not mt5.symbol_select(broker_symbol, True):
                    raise ValueError(f"{symbol}: broker symbol unavailable")
                resolved[symbol] = broker_symbol
            last = validate_broker_rates(mt5.copy_rates_from_pos(
                resolved[symbol], getattr(mt5, f"TIMEFRAME_{tf}"), 1, 1), f"{symbol}/{tf} closed", clock)
            if len(last) != 1:
                raise ValueError(f"{symbol}/{tf}: cannot establish last closed candle")
            closed[symbol, tf] = last["time"].iloc[0]
        padded_start = start
        if plan["warmup_bars"]:
            for symbol in plan["symbols"]:
                for tf in sorted({plan["execution"], plan["regime"]}):
                    prefix = validate_broker_rates(mt5.copy_rates_from(
                        resolved[symbol], getattr(mt5, f"TIMEFRAME_{tf}"),
                        broker_query_date(start - timedelta(seconds=1), clock),
                        plan["warmup_bars"] + 1), f"{symbol}/{tf} warmup", clock)
                    # The next broker open proves closure: the last row may be
                    # a candle still forming at the requested historical start.
                    prefix = prefix.iloc[:-1]
                    if len(prefix) < plan["warmup_bars"] or (prefix["time"] >= pd.Timestamp(start)).any() \
                            or (prefix["time"] > closed[symbol, tf]).any():
                        raise ValueError(f"{symbol}/{tf}: insufficient closed warmup bars; "
                                         "load more history in MT5 or choose a later start")
                    padded_start = min(padded_start, prefix["time"].iloc[0].to_pydatetime())
        for symbol, tf in plan["jobs"]:
            anchor = validate_broker_rates(mt5.copy_rates_from(
                resolved[symbol], getattr(mt5, f"TIMEFRAME_{tf}"), broker_query_date(padded_start, clock), 1),
                f"{symbol}/{tf} coverage anchor", clock)
            if anchor.empty or anchor["time"].iloc[-1] > pd.Timestamp(padded_start):
                raise ValueError(f"{symbol}/{tf}: history does not cover the warmup start; "
                                 "load more broker history or choose a later start")
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        with tempfile.TemporaryDirectory(prefix=".broker-export-", dir=out_dir) as tmp:
            stage = Path(tmp)
            for symbol, tf in plan["jobs"]:
                filename = f"{symbol}_{tf}.csv"
                coverage_info = _stream_broker_csv(
                    mt5, resolved[symbol], tf, padded_start, end, closed[symbol, tf],
                    stage / filename, chunk_days, clock)
                metadata = {
                    "source": "MetaTrader5 broker candles (no resampling)",
                    "broker_server": str(getattr(account, "server", "")),
                    "exported_at_utc": exported_at.isoformat(),
                    "timestamp_timezone": "UTC (broker API clock normalized; candle boundaries preserved)",
                    "broker_api_clock": clock,
                    "api_query_start_label": broker_query_date(padded_start, clock).isoformat(),
                    "api_query_end_exclusive_label": broker_query_date(end, clock).isoformat(),
                    "symbol": symbol, "broker_symbol": resolved[symbol], "timeframe": tf,
                    "requested_start_utc": start.isoformat(), "requested_end_exclusive_utc": end.isoformat(),
                    "export_start_with_warmup_utc": padded_start.isoformat(),
                    "warmup_bars": plan["warmup_bars"],
                    "last_closed_open_utc": closed[symbol, tf].isoformat(),
                    "strategy_timeframes": {k: plan[k] for k in ("execution", "regime", "position_checks")},
                    **coverage_info}
                (stage / f"{symbol}_{tf}.meta.json").write_text(
                    json.dumps(metadata, indent=2), encoding="utf-8")
                print(f"staged {filename}: {coverage_info['bars']} bars, "
                      f"{coverage_info['first_open_utc']} -> {coverage_info['last_open_utc']}; "
                      f"gaps={coverage_info['gap_count']}, empty chunks={len(coverage_info['empty_chunks'])}; "
                      f"leading/trailing seconds={coverage_info['leading_seconds']}/"
                      f"{coverage_info['trailing_seconds']}", flush=True)
            # No validated file is published if another feed fails during collection.
            if not overwrite and any(p.exists() for p in targets):
                raise FileExistsError("output appeared during export; refusing overwrite")
            for target in targets:
                (stage / target.name).replace(target)
                written.append(target)
        return written
    finally:
        # Even a failed initialization can leave bridge resources to release.
        mt5.shutdown()


def write_m1(m1: pd.DataFrame, path: str | Path) -> Path:
    """Consolidated minute CSV for tick-based position checks (backtest reads it)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    m1 = m1[(M1_COLUMNS)]
    m1.to_csv(path, index=False)
    return path


def _read_m1_file(path: Path) -> pd.DataFrame:
    """Read one M1 file: plain CSV or a zip holding the CSV (HistData layout)."""
    if path.suffix.lower() == ".zip":
        import zipfile

        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"{path}: no CSV inside zip")
            with zf.open(sorted(members)[0]) as fh:
                df = pd.read_csv(fh, header=None,
                                 names=["date", "clock", "open", "high", "low", "close", "tick_volume"])
    else:
        df = pd.read_csv(path, header=None,
                         names=["date", "clock", "open", "high", "low", "close", "tick_volume"])
    df["time"] = pd.to_datetime(df["date"] + " " + df["clock"],
                                 format="%Y.%m.%d %H:%M", utc=True)
    return df[["time", "open", "high", "low", "close", "tick_volume"]]


def load_m1(src_dir: str | Path, symbol: str) -> pd.DataFrame:
    """Concatenate yearly M1 files (CSV or zip) for one symbol, sorted, deduped."""
    files = sorted(Path(src_dir).glob(f"DAT_MT_{symbol}_M1_*.csv"))
    files += sorted(Path(src_dir).glob(f"HISTDATA_COM_MT_{symbol}_M1*.zip"))
    if not files:
        raise FileNotFoundError(f"no M1 files for {symbol} in {src_dir}")
    frames = [_read_m1_file(f) for f in files]
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
    ap = argparse.ArgumentParser(description="Build vendor H1, or export broker history with --broker (no orders).")
    ap.add_argument("--symbol")
    ap.add_argument("--src", default="data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--m1-csv", action="store_true",
                     help="also write data/<SYM>_M1.csv (minute feed for position checks)")
    ap.add_argument("--broker", action="store_true", help="export actual candles from the logged-in MT5 terminal")
    ap.add_argument("--broker-clock", choices=("auto", "utc", "new_york_plus_7"), default=None,
                    help="API timestamp clock; auto normalizes verified Pepperstone server labels")
    ap.add_argument("--bundle-broker", nargs="+", metavar="SOURCE_DIR",
                    help="offline: combine verified broker sources, refusing conflicting overlaps")
    ap.add_argument("--batch", action="store_true", help="export selected config pairs")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--start", help="UTC start, with indicator warmup exported before it")
    ap.add_argument("--end", help="exclusive UTC end, not in the future")
    ap.add_argument("--out-dir", default="data", help="broker export folder; existing files are refused by default")
    ap.add_argument("--warmup-bars", type=int, default=None, help="override config-derived warmup; 0 disables")
    ap.add_argument("--chunk-days", type=int, default=31, help="bounded broker query size")
    ap.add_argument("--overwrite", action="store_true", help="explicitly replace existing broker output files")
    ap.add_argument("--plan", action="store_true", help="show broker export plan without connecting or writing")
    ap.add_argument("--research", action="store_true", help="derive explicitly labelled research charts from existing M1 CSVs")
    ap.add_argument("--all-existing", action="store_true", help="include every existing *_M1.csv, including parked pairs")
    ap.add_argument("--research-timeframes", nargs="+", default=["H4", "D1"])
    ap.add_argument("--chunk-rows", type=int, default=100000)
    ap.add_argument("--import-pepperstone", action="store_true",
                     help="archive tagged MT5 chart exports and normalize their server clock to UTC")
    ap.add_argument("--add-h1", action="store_true",
                    help="with --import-pepperstone, add H1 exports to an existing H4/D1 dataset")
    args = ap.parse_args(argv)
    if args.bundle_broker:
        if any((args.broker, args.research, args.import_pepperstone, args.add_h1,
                args.batch, args.symbol, args.out, args.m1_csv, args.overwrite,
                args.plan, args.start, args.end, args.all_existing, args.broker_clock)):
            ap.error("--bundle-broker uses only source directories and a fresh --out-dir")
        try:
            from quant.broker_data import bundle_sources
            manifest = bundle_sources(args.bundle_broker, args.out_dir)
            print(f"Bundled {len(manifest['symbols'])} broker symbols; no strategy simulation", flush=True)
            return 0
        except (ValueError, OSError, KeyError) as exc:
            print(f"BROKER BUNDLE ERROR - {exc}", flush=True)
            return 2
    if args.broker_clock and not args.broker:
        ap.error("--broker-clock requires --broker")
    if args.add_h1 and not args.import_pepperstone:
        ap.error("--add-h1 requires --import-pepperstone")
    if args.import_pepperstone:
        if args.broker or args.research or args.all_existing or args.out or args.m1_csv or args.overwrite or args.plan:
            ap.error("MT5 CSV import uses --batch/--symbol, --src and --out-dir (existing only with --add-h1)")
        if args.batch == bool(args.symbol):
            ap.error("choose --batch or --symbol for MT5 CSV import")
        try:
            from quant.broker_data import import_exports, import_h1_exports
            from quant.monitor import load_pairs, read_selection
            selection = read_selection(args.config_dir)
            symbols = [args.symbol] if args.symbol else [p["symbol"] for p in load_pairs(args.config_dir)
                if not p.get("load_error") and (selection is None or selection.get(p["symbol"], True))]
            importer = import_h1_exports if args.add_h1 else import_exports
            manifest = importer(args.src, args.out_dir, symbols)
            print(f"Imported {len(manifest['symbols'])} pairs; originals archived under {args.out_dir}/raw", flush=True)
            for warning in manifest["warnings"]:
                print(f"COVERAGE WARNING: {warning}", flush=True)
            return 0
        except (ValueError, OSError, KeyError) as exc:
            print(f"MT5 CSV IMPORT ERROR - {exc}", flush=True)
            return 2
    if args.research:
        if args.broker or args.batch or args.out or args.m1_csv or args.start or args.end or args.plan:
            ap.error("research mode uses --src, --out-dir and --symbol/--all-existing, not broker/vendor options")
        try:
            manifest = build_research_data(args.src, args.out_dir, symbol=args.symbol,
                all_existing=args.all_existing, timeframes=args.research_timeframes,
                chunk_rows=args.chunk_rows, overwrite=args.overwrite)
            print(f"{RESEARCH_WARNING}\nBuilt {len(manifest['symbols'])} research pairs in {args.out_dir}", flush=True)
            return 0
        except (ValueError, TypeError, OSError, KeyError) as exc:
            print(f"RESEARCH BUILD ERROR - {exc}", flush=True)
            return 2
    if args.all_existing:
        ap.error("--all-existing requires --research")
    if args.broker:
        if args.out or args.m1_csv:
            ap.error("--out / --m1-csv are vendor-only; broker mode follows config and --out-dir")
        if not args.start or not args.end:
            ap.error("--broker requires --start and --end (exclusive)")
        try:
            start, end = _utc_date(args.start), _utc_date(args.end)
            if start >= end or args.chunk_days <= 0:
                raise ValueError("need start < end and --chunk-days > 0")
            plan = broker_plan(args.config_dir, args.symbol, args.batch, args.warmup_bars)
            if args.broker_clock:
                plan["api_clock"] = args.broker_clock
            print(json.dumps({**plan, "start_utc": start.isoformat(),
                              "end_exclusive_utc": end.isoformat(), "out_dir": args.out_dir}, indent=2))
            if args.plan:
                return 0
            try:
                import MetaTrader5 as mt5
            except ImportError:
                raise ValueError("MetaTrader5 is unavailable; export needs Windows and the MT5 terminal") from None
            written = export_broker(mt5, plan, start, end, args.out_dir,
                                     chunk_days=args.chunk_days, overwrite=args.overwrite)
            print(f"exported {len(written) // 2} broker feeds + metadata (no orders)", flush=True)
            return 0
        except (ValueError, TypeError, OSError, KeyError) as exc:
            print(f"EXPORT ERROR - {exc}", flush=True)
            return 2
    if not args.symbol:
        ap.error("vendor mode requires --symbol")
    if args.batch or args.start or args.end or args.plan or args.overwrite or args.warmup_bars is not None:
        ap.error("broker options require --broker")
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
    if args.m1_csv:
        m1out = write_m1(m1, Path(args.out).with_name(Path(args.out).stem.replace("_H1", "_M1"))
                         if args.out else f"data/{args.symbol}_M1.csv")
        print(f"wrote {m1out} ({len(m1)} M1 minutes)", flush=True)
    print(coverage(m1, h1).to_string(index=False), flush=True)
    short = int((h1["n_minutes"] < 60).sum())
    print(f"short hours (<60 min): {short} ({short / max(len(h1), 1):.1%})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
