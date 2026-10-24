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
BUNDLE_SOURCE = "pepperstone_mt5_verified_bundle"
API_SOURCE = "pepperstone_mt5_api_export"
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
    if tf not in ("H1", "H4", "D1"):
        raise ValueError("MT5 chart intake supports H1/H4/D1 only")
    raw = pd.read_csv(path, sep="\t")
    required = {"<DATE>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>"}
    if tf in ("H1", "H4"):
        required.add("<TIME>")
    if not required.issubset(raw.columns):
        raise ValueError(f"{path.name}: missing MT5 chart columns")
    stamps = raw["<DATE>"].astype(str)
    if "<TIME>" in raw:
        stamps += " " + raw["<TIME>"].astype(str)
    server = pd.to_datetime(stamps, format="%Y.%m.%d %H:%M:%S" if "<TIME>" in raw else "%Y.%m.%d")
    if server.empty or server.isna().any() or server.duplicated().any() or not server.is_monotonic_increasing:
        raise ValueError(f"{path.name}: empty/invalid/duplicate/descending timestamps")
    if (server != server.dt.floor({"H1": "h", "H4": "4h", "D1": "D"}[tf])).any():
        raise ValueError(f"{path.name}: candles do not align to broker {tf} boundaries")
    utc = pepperstone_utc(server)
    converted = raw.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
                                     "<CLOSE>": "close", "<TICKVOL>": "tick_volume"}).copy()
    converted["time"] = [int(t.timestamp()) for t in utc]
    # Preserve actual OHLC; normalize timestamps only, never resample broker candles.
    return validate_broker_rates(converted, path.name), server


def dataset_info(root: str | Path, tape_tf: str = "H4", position_checks: str | None = None) -> dict:
    root = Path(root).resolve()
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    source = manifest.get("source_type")
    if source not in (SOURCE, BUNDLE_SOURCE) or manifest.get("version") != 1:
        raise ValueError("not a supported Pepperstone chart-export manifest")
    bundled = source == BUNDLE_SOURCE
    info = {"directory": str(root), "source_type": source,
             "manifest_sha256": file_digest(path), "warning": WARNING,
             "coverage_warnings": manifest.get("warnings", [])}
    if tape_tf == "H1":
        extension = manifest if bundled else _h1_manifest(root)
        info.update(h1_manifest_sha256=file_digest(path if bundled else root / "manifest_h1.json"),
                     warning=WARNING.replace("H4", "H1"),
                    coverage_warnings=info["coverage_warnings"] + ([] if bundled else extension.get("warnings", [])))
    elif tape_tf == "D1":
        info["warning"] = WARNING.replace("H4", "D1")
    elif tape_tf != "H4":
        raise ValueError("broker tape must be H1, H4 or D1")
    if position_checks is not None:
        resolve_position_checks({"backtest_data": {"position_checks": position_checks}}, tape_tf)
    if position_checks == "H1" and tape_tf != "H1":
        extension = manifest if bundled else _h1_manifest(root)
        info.update(h1_manifest_sha256=file_digest(path if bundled else root / "manifest_h1.json"),
                    position_checks="H1",
                    warning=("Broker H1 position checks: intrabar order unknown; stop wins ties. "
                             "Trailing changes apply after each H1 close. "
                             f"Drawdown marks still use {tape_tf} closes, not intrahour prices."),
                    coverage_warnings=info["coverage_warnings"] + ([] if bundled else extension.get("warnings", [])))
    return info


def resolve_position_checks(base: dict, execution: str) -> str:
    """Keep old datasets' execution-grid checks unless explicitly configured otherwise."""
    checks = str((base.get("backtest_data") or {}).get("position_checks", execution)).upper()
    hours = {"H1": 1, "H4": 4, "D1": 24}
    if checks not in hours or (checks != execution and checks != "H1"):
        raise ValueError("broker position_checks must be H1 or the execution timeframe")
    if hours[checks] > hours[execution]:
        raise ValueError("broker position checks cannot be coarser than execution")
    return checks


def _h1_manifest(root: Path) -> dict:
    manifest = json.loads((root / "manifest_h1.json").read_text(encoding="utf-8"))
    if (manifest.get("version") != 1 or manifest.get("source_type") != SOURCE
            or manifest.get("base_manifest_sha256") != file_digest(root / "manifest.json")):
        raise ValueError("H1 extension does not match the broker H4/D1 dataset")
    return manifest


def chart_path(root: str | Path, symbol: str, tf: str) -> Path:
    root = Path(dataset_info(root)["directory"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if tf == "H1" and manifest["source_type"] == SOURCE:
        manifest = _h1_manifest(root)
    chart = manifest["symbols"][symbol][tf]
    path = (root / chart["file"]).resolve()
    if not path.is_relative_to(root) or file_digest(path) != chart["sha256"]:
        raise ValueError(f"{symbol}/{tf}: broker chart path/checksum mismatch")
    return path


def closed_converter(root: str | Path, symbol: str, tf: str = "H4") -> pd.Series:
    frame = pd.read_csv(chart_path(root, symbol, tf))
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
    if str(cfg.get("position_checks", "H4")).upper() not in ("H1", "H4", "D1"):
        raise ValueError("broker CSV mode requires H1, H4 or D1 position checks (no vendor M1)")
    return str(Path(override or cfg.get("broker_csv_dir", "data/pepperstone")).resolve())


def _safe_chart(root: Path, filename: str, digest: str) -> Path:
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or file_digest(path) != digest:
        raise ValueError(f"{filename}: broker source path/checksum mismatch")
    return path


def _bundle_inputs(root: Path) -> tuple[dict, dict, list[str]]:
    """Accept verified chart imports or the normalized API collection contract only."""
    charts, warnings = {}, []
    if (root / "manifest.json").exists():
        info = dataset_info(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        warnings.extend(manifest.get("warnings", []))
        for symbol, items in manifest["symbols"].items():
            for tf in items:
                charts[symbol, tf] = chart_path(root, symbol, tf)
        if manifest["source_type"] == SOURCE and (root / "manifest_h1.json").exists():
            extension = _h1_manifest(root)
            info["h1_manifest_sha256"] = file_digest(root / "manifest_h1.json")
            warnings.extend(extension.get("warnings", []))
            for symbol in extension["symbols"]:
                charts[symbol, "H1"] = chart_path(root, symbol, "H1")
        return charts, info, warnings
    spec_path = root / "collection_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if (spec.get("version") != 1 or spec.get("source_type") != API_SOURCE
            or spec.get("status") not in ("quality_checks_passed_with_session_warnings", "quality_checks_passed")
            or spec.get("broker_server") != "Pepperstone-Demo"):
        raise ValueError(f"{root}: expected a verified normalized Pepperstone API collection")
    audit = spec.get("quality_audit") or {}
    audit_path = _safe_chart(root, audit["file"], audit["sha256"])
    quality = json.loads(audit_path.read_text(encoding="utf-8"))
    if quality.get("issues"):
        raise ValueError(f"{root}: unresolved source quality issues")
    warnings.extend(quality.get("warnings", []))
    for name, record in spec["files"].items():
        match = re.fullmatch(r"([A-Z]{6})_(H1|H4|D1)\.csv", name)
        if not match:
            continue
        path = _safe_chart(root, name, record["sha256"])
        meta_name = path.with_suffix(".meta.json").name
        meta_path = _safe_chart(root, meta_name, spec["files"][meta_name]["sha256"])
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        symbol, tf = match.groups()
        if (meta.get("symbol") != symbol or meta.get("timeframe") != tf
                or not str(meta.get("timestamp_timezone", "")).startswith("UTC")
                or meta.get("source_type") != API_SOURCE
                or meta.get("broker_server") != spec["broker_server"]):
            raise ValueError(f"{name}: source/timezone metadata mismatch")
        if meta.get("sha256", record["sha256"]) != record["sha256"]:
            raise ValueError(f"{name}: metadata price checksum mismatch")
        charts[symbol, tf] = path
    if not charts:
        raise ValueError(f"{root}: no verified broker charts")
    return charts, {"directory": str(root), "source_type": API_SOURCE,
                    "collection_spec_sha256": file_digest(spec_path)}, warnings


def bundle_sources(sources: list[str | Path], dest: str | Path) -> dict:
    """Offline union of real broker candles; never fabricate a missing period."""
    dest = Path(dest).resolve()
    if dest.exists():
        raise FileExistsError("broker bundle already exists; choose a fresh destination")
    if not sources or len({str(Path(s).resolve()) for s in sources}) != len(sources):
        raise ValueError("need nonempty, unique broker source directories")
    inputs, identities, warnings = {}, [], []
    for source in sources:
        root = Path(source).resolve()
        charts, identity, notes = _bundle_inputs(root)
        identities.append(identity)
        warnings.extend(notes)
        for key, path in charts.items():
            symbol, tf = key
            if not re.fullmatch(r"[A-Z]{6}", symbol) or tf not in ("H1", "H4", "D1"):
                raise ValueError("bundle supports six-letter FX symbols on H1/H4/D1")
            inputs.setdefault(key, []).append((path, file_digest(path)))
    manifest = {"version": 1, "source_type": BUNDLE_SOURCE,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "timezone_rule": "verified source UTC; broker boundaries preserved; no resampling",
        "sources": identities, "warnings": list(dict.fromkeys(warnings)), "symbols": {}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".broker-bundle-", dir=dest.parent) as tmp:
        stage = Path(tmp) / "dataset"
        stage.mkdir()
        for (symbol, tf), records in sorted(inputs.items()):
            frames = []
            for path, digest in records:
                raw = pd.read_csv(path)
                stamps = pd.to_datetime(raw["time"], utc=True, errors="raise")
                raw["time"] = stamps.dt.as_unit("s").astype("int64")
                frames.append(validate_broker_rates(raw, str(path)))
            merged = pd.concat(frames, ignore_index=True)
            # An identical overlap is provenance, not a gap to fill or a price to average.
            duplicate = merged[merged["time"].duplicated(keep=False)]
            if len(duplicate) and (duplicate.groupby("time")[
                    ["open", "high", "low", "close", "tick_volume"]].nunique(dropna=False) > 1).any().any():
                raise ValueError(f"{symbol}/{tf}: conflicting overlapping broker candles")
            overlap = int(merged["time"].duplicated().sum())
            merged = merged.drop_duplicates("time").sort_values("time").reset_index(drop=True)
            name = f"{symbol}_{tf}.csv"
            merged.to_csv(stage / name, index=False)
            record = {"file": name, "sha256": file_digest(stage / name), "bars": len(merged),
                "first_utc_open": merged["time"].iloc[0].isoformat(),
                "last_utc_open": merged["time"].iloc[-1].isoformat(),
                "identical_overlap_bars": overlap,
                "source_files": [{"path": str(p), "sha256": d} for p, d in records]}
            manifest["symbols"].setdefault(symbol, {})[tf] = record
            (stage / f"{symbol}_{tf}.meta.json").write_text(json.dumps({
                "source_type": BUNDLE_SOURCE, "symbol": symbol, "timeframe": tf,
                "timestamp_timezone": "UTC", **record}, indent=2), encoding="utf-8")
        for records in inputs.values():
            for path, digest in records:
                if file_digest(path) != digest:
                    raise ValueError(f"{path}: source changed while bundling")
        for source, identity in zip(sources, identities):
            if _bundle_inputs(Path(source).resolve())[1] != identity:
                raise ValueError("broker source identity changed while bundling")
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if dest.exists():
            raise FileExistsError("destination appeared while bundling")
        stage.replace(dest)
    return manifest


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


def import_h1_exports(src: str | Path, dest: str | Path, symbols: list[str]) -> dict:
    """Add H1 without changing the original H4/D1 manifest or saved run identities."""
    src, dest = Path(src).resolve(), Path(dest).resolve()
    identity = dataset_info(dest)
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("need a nonempty, unique selected symbol list")
    if (dest / "manifest_h1.json").exists():
        raise FileExistsError("H1 extension already exists; refusing overwrite")
    inputs, frames, clocks, signatures = {}, {}, {}, {}
    warnings = []
    for symbol in symbols:
        if not re.fullmatch(r"[A-Z]{6}", symbol):
            raise ValueError(f"unsupported FX symbol: {symbol}")
        paths = sorted(src.glob(f"{symbol}_H1_*_PEPPERSTONE.csv"))
        if len(paths) != 1:
            raise ValueError(f"{symbol}/H1: expected one tagged export, found {len(paths)}")
        path = paths[0]
        inputs[symbol], signatures[symbol] = path, file_signature(path)
        frame, server = read_mt5_csv(path, "H1")
        h4 = pd.read_csv(chart_path(dest, symbol, "H4"))
        # Audit broker H1 against the actual H4 exports; do not use aggregates as prices.
        audit = frame.assign(bucket=server.dt.floor("4h")).groupby("bucket").agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), bars=("close", "size"))
        bucket_times = pepperstone_utc(pd.Series(audit.index)).to_numpy()
        audit.index = pd.DatetimeIndex(bucket_times)
        expected = h4.set_index(pd.to_datetime(h4["time"], utc=True))
        common = expected.index.intersection(audit.index)
        cols = ["open", "high", "low", "close"]
        if (len(common) != len(expected)
                or ((audit.loc[common, cols] - expected.loc[common, cols]).abs() > 1e-8).any().any()):
            raise ValueError(f"{symbol}: H1 does not fully match the broker H4 candles")
        partial = int((audit["bars"] < 4).sum())
        if partial:
            warnings.append(f"{symbol}: {partial} H4 periods contain fewer than four H1 candles "
                            "(short sessions or missing hours). OHLC matches H4; no hours filled.")
        frames[symbol], clocks[symbol] = frame, server
    manifest = {"version": 1, "source_type": SOURCE,
                "base_manifest_sha256": identity["manifest_sha256"],
                "imported_at_utc": datetime.now(timezone.utc).isoformat(),
                "timezone_rule": "server = America/New_York + 7h; US DST; normalized to UTC",
                "export_date": "not supplied; filenames describe candle range, not export date",
                "warnings": warnings, "symbols": {}}
    with tempfile.TemporaryDirectory(prefix=".pepperstone-h1-", dir=dest.parent) as tmp:
        stage = Path(tmp)
        (stage / "raw").mkdir()
        for symbol, path in inputs.items():
            frame, server = frames[symbol], clocks[symbol]
            filename = f"{symbol}_H1.csv"
            frame.to_csv(stage / filename, index=False)
            shutil.copy2(path, stage / "raw" / path.name)
            record = {"file": filename, "sha256": file_digest(stage / filename),
                      "raw_file": f"raw/{path.name}", "raw_sha256": file_digest(path),
                      "bars": len(frame), "first_server_open": server.iloc[0].isoformat(),
                      "last_server_open": server.iloc[-1].isoformat(),
                      "first_utc_open": frame["time"].iloc[0].isoformat(),
                      "last_utc_open": frame["time"].iloc[-1].isoformat()}
            if file_digest(stage / "raw" / path.name) != record["raw_sha256"]:
                raise ValueError(f"{path.name}: archive checksum mismatch")
            manifest["symbols"][symbol] = {"H1": record}
            (stage / f"{symbol}_H1.meta.json").write_text(json.dumps({
                "source_type": SOURCE, "symbol": symbol, "timeframe": "H1",
                "timezone_rule": manifest["timezone_rule"], **record}, indent=2), encoding="utf-8")
        (stage / "manifest_h1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if dataset_info(dest) != identity:
            raise ValueError("broker base dataset changed during H1 import")
        for symbol, path in inputs.items():
            if file_signature(path) != signatures[symbol]:
                raise ValueError(f"{path.name}: input changed during import")
        files = [p for p in stage.rglob("*") if p.is_file()]
        if any((dest / p.relative_to(stage)).exists() for p in files):
            raise FileExistsError("H1 destination file already exists; refusing overwrite")
        published = []
        try:
            # Publish the manifest last; a failed publication removes only our new files.
            for path in sorted(files, key=lambda p: p.name == "manifest_h1.json"):
                target = dest / path.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output, path.open("rb") as source:
                    published.append(target)
                    shutil.copyfileobj(source, output)
        except Exception:
            for path in reversed(published):
                path.unlink()
            raise
    for symbol, path in inputs.items():
        record = manifest["symbols"][symbol]["H1"]
        if file_signature(path) != signatures[symbol] or file_digest(path) != record["raw_sha256"]:
            raise ValueError(f"{path.name}: changed after import; kept original in place")
        path.unlink()
    return manifest
