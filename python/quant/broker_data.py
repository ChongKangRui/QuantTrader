"""Read-only MT5 chart CSV intake and shared offline broker-dataset contract."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant.mkdata import file_digest, file_signature, validate_broker_rates

SOURCE = "pepperstone_mt5_chart_export"
TIMEZONE_SOURCE = "https://pepperstone.com/en/about-us/trading-hours"
WARNING = ("Broker H4-only exit checks: intrabar order unknown; stop wins when both "
           "stop and target are touched. Coarse exits book at bar close; trailing is approximate. "
           "Drawdown marks use H4 closes, not minute/hourly prices.")


def pepperstone_utc(server_times: pd.Series) -> pd.Series:
    """Pepperstone midnight = 17:00 New York, including US (not EU) DST."""
    if server_times.dt.tz is not None:
        raise ValueError("MT5 chart timestamps must be naive broker-server time")
    # Server clock is New York + 7 hours: UTC+2 in US winter, UTC+3 in US summer.
    return (server_times - pd.Timedelta(hours=7)).dt.tz_localize(
        "America/New_York", ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")


def read_mt5_csv(path: Path, tf: str) -> tuple[pd.DataFrame, pd.Series]:
    if tf not in ("H4", "D1"):
        raise ValueError("MT5 chart intake currently supports H4/D1 only")
    raw = pd.read_csv(path, sep="\t")
    required = {"<DATE>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>"}
    if tf == "H4":
        required.add("<TIME>")
    if not required.issubset(raw.columns):
        raise ValueError(f"{path.name}: missing MT5 chart columns")
    stamps = raw["<DATE>"].astype(str)
    if "<TIME>" in raw:
        stamps += " " + raw["<TIME>"].astype(str)
    server = pd.to_datetime(stamps, format="%Y.%m.%d %H:%M:%S" if "<TIME>" in raw else "%Y.%m.%d")
    if server.empty or server.isna().any() or server.duplicated().any() or not server.is_monotonic_increasing:
        raise ValueError(f"{path.name}: empty/invalid/duplicate/descending timestamps")
    if (server != server.dt.floor("4h" if tf == "H4" else "D")).any():
        raise ValueError(f"{path.name}: candles do not align to broker {tf} boundaries")
    utc = pepperstone_utc(server)
    converted = raw.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
                                     "<CLOSE>": "close", "<TICKVOL>": "tick_volume"}).copy()
    converted["time"] = [int(t.timestamp()) for t in utc]
    # Preserve actual OHLC; normalize timestamps only, never resample broker candles.
    return validate_broker_rates(converted, path.name), server


def dataset_info(root: str | Path) -> dict:
    root = Path(root).resolve()
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("source_type") != SOURCE or manifest.get("version") != 1:
        raise ValueError("not a supported Pepperstone chart-export manifest")
    return {"directory": str(root), "source_type": SOURCE,
            "manifest_sha256": file_digest(path), "warning": WARNING,
            "coverage_warnings": manifest.get("warnings", [])}


def chart_path(root: str | Path, symbol: str, tf: str) -> Path:
    root = Path(dataset_info(root)["directory"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    chart = manifest["symbols"][symbol][tf]
    path = (root / chart["file"]).resolve()
    if not path.is_relative_to(root) or file_digest(path) != chart["sha256"]:
        raise ValueError(f"{symbol}/{tf}: broker chart path/checksum mismatch")
    return path


def closed_converter(root: str | Path, symbol: str) -> pd.Series:
    frame = pd.read_csv(chart_path(root, symbol, "H4"))
    times = pd.to_datetime(frame["time"], utc=True)
    # A candle's CLOSE is usable only once a following broker candle has opened.
    return pd.Series(frame["close"].iloc[:-1].to_numpy(), index=times.iloc[1:])


def resolve_broker_dir(base: dict, research_dir=None, override=None) -> str | None:
    cfg = base.get("backtest_data") or {}
    enabled = cfg.get("use_broker_csv", False)
    if not isinstance(enabled, bool):
        raise ValueError("backtest_data.use_broker_csv must be true or false")
    if research_dir:
        if override:
            raise ValueError("choose broker data or research data, not both")
        return None  # Explicit research opt-in overrides the offline default.
    if not enabled and not override:
        return None
    if cfg.get("broker_server_clock", "new_york_plus_7") != "new_york_plus_7":
        raise ValueError("unsupported broker server clock; this dataset uses Pepperstone US DST")
    if str(cfg.get("position_checks", "H4")).upper() != "H4":
        raise ValueError("broker CSV mode currently requires explicit H4 position checks")
    return str(Path(override or cfg.get("broker_csv_dir", "data/pepperstone")).resolve())


def import_exports(src: str | Path, dest: str | Path, symbols: list[str]) -> dict:
    """Validate every selected pair before archiving original bytes and normalizing."""
    src, dest = Path(src).resolve(), Path(dest).resolve()
    if dest.exists():
        raise FileExistsError("broker dataset already exists; refusing to overwrite")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("need a nonempty, unique selected symbol list")
    inputs, frames, clocks, signatures = {}, {}, {}, {}
    for symbol in symbols:
        # Export names determine symbol paths: do not permit paths or inferred suffixes.
        if not re.fullmatch(r"[A-Z]{6}", symbol):
            raise ValueError(f"unsupported FX symbol: {symbol}")
        for tf, name in (("H4", "H4"), ("D1", "Daily")):
            paths = sorted(src.glob(f"{symbol}_{name}_*_PEPPERSTONE.csv"))
            if len(paths) != 1:
                raise ValueError(f"{symbol}/{tf}: expected one tagged export, found {len(paths)}")
            path = paths[0]
            inputs[symbol, tf] = path
            signatures[symbol, tf] = file_signature(path)
            frames[symbol, tf], clocks[symbol, tf] = read_mt5_csv(path, tf)
    manifest = {"version": 1, "source_type": SOURCE,
                "imported_at_utc": datetime.now(timezone.utc).isoformat(),
                "timezone_rule": "server = America/New_York + 7h; US DST; normalized to UTC",
                "timezone_reference": TIMEZONE_SOURCE,
                "export_date": "not supplied; filenames describe candle range, not export date",
                "warnings": [], "symbols": {}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".pepperstone-import-", dir=dest.parent) as tmp:
        stage = Path(tmp) / "dataset"
        (stage / "raw").mkdir(parents=True)
        for symbol in symbols:
            h4 = frames[symbol, "H4"].copy()
            h4["day"] = clocks[symbol, "H4"].dt.normalize()
            daily = frames[symbol, "D1"].copy()
            daily["day"] = clocks[symbol, "D1"].dt.normalize()
            cols = ["open", "high", "low", "close"]
            # Consistency audit only: never replace Daily exports with aggregated H4.
            aggregate = h4.groupby("day").agg(open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"))
            expected = daily.set_index("day")[cols]
            common = aggregate.index.intersection(expected.index)
            if len(common) != len(expected) or len(common) != len(aggregate):
                raise ValueError(f"{symbol}: H4/D1 server-day coverage differs")
            mismatch = ((aggregate.loc[common] - expected.loc[common]).abs() > 1e-8).any(axis=1)
            counts = h4.groupby("day").size()
            for day in common[mismatch]:
                if day != common[-1] or counts.loc[day] >= 6:
                    raise ValueError(f"{symbol}: unexpected H4/D1 OHLC mismatch on {day.date()}")
                manifest["warnings"].append(f"{symbol}: final server day {day.date()} has "
                    f"{counts.loc[day]} H4 candles; Daily includes later prices. No gap filled or dates trimmed.")
            manifest["symbols"][symbol] = {}
            for tf in ("H4", "D1"):
                path = inputs[symbol, tf]
                frame, server = frames[symbol, tf], clocks[symbol, tf]
                filename = f"{symbol}_{tf}.csv"
                frame.to_csv(stage / filename, index=False)
                shutil.copy2(path, stage / "raw" / path.name)
                original_hash = file_digest(path)
                if file_digest(stage / "raw" / path.name) != original_hash:
                    raise ValueError(f"{path.name}: archive copy failed checksum")
                record = {"file": filename, "sha256": file_digest(stage / filename),
                    "raw_file": f"raw/{path.name}", "raw_sha256": original_hash,
                    "bars": len(frame), "first_server_open": server.iloc[0].isoformat(),
                    "last_server_open": server.iloc[-1].isoformat(),
                    "first_utc_open": frame["time"].iloc[0].isoformat(),
                    "last_utc_open": frame["time"].iloc[-1].isoformat()}
                manifest["symbols"][symbol][tf] = record
                (stage / f"{symbol}_{tf}.meta.json").write_text(json.dumps({
                    "source_type": SOURCE, "symbol": symbol, "timeframe": tf,
                    "timezone_rule": manifest["timezone_rule"], **record}, indent=2), encoding="utf-8")
        for key, path in inputs.items():
            if file_signature(path) != signatures[key]:
                raise ValueError(f"{path.name}: input changed during import")
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if dest.exists():
            raise FileExistsError("destination appeared during import; refusing overwrite")
        stage.replace(dest)
    # Move only exact verified export files: their preserved copies are already published.
    for (symbol, tf), path in inputs.items():
        record = manifest["symbols"][symbol][tf]
        if file_signature(path) != signatures[symbol, tf] or file_digest(path) != record["raw_sha256"]:
            raise ValueError(f"{path.name}: changed after import; kept original in place")
        path.unlink()
    return manifest
