"""H4 bias console panel. Read-only, sends no orders.

Repaint rule: the screen only redraws when a new H1 bar closes. All bars are
closed bars fetched via copy_rates_from_pos(..., start_pos=1); the H4 bias uses
the last fully completed H4 bar. Empty state: NONE DETECTED when no pair holds
UP/DOWN H4 bias. ENTRY column shows GO or the first failing section-5 rule.
Each cycle also syncs closed positions and the weekly loss halt per account.
"""
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant.bias import SEP_MIN_DEFAULT, h4_bias
from quant.signals import check_entry

JOURNAL_DEFAULT = "trades/journal.csv"
RECORDS_DEFAULT = "trades"
MEMORY_DEFAULT = "memory"
H4_BARS = 350  # spec warmup_bars (300) plus margin
H1_BARS = 400
POLL_INTERVAL = 60.0
SKIP_FILES = {"_base", "scan-selection"}  # never pair files (matched by stem)
SKIP_SUFFIX = "_untrade"  # parked pairs, e.g. NZDUSD_untrade.yml
DISP = {"LONG": "UP", "SHORT": "DOWN", "NEUTRAL": "FLAT"}
MY_TZ = timezone(timedelta(hours=8))  # Malaysia is fixed UTC+8, no DST, no tz database needed


@dataclass
class PairRow:
    """One panel line. ok=False means the pair could not be read (see note)."""

    symbol: str
    ok: bool
    bias: str = "FLAT"  # UP | DOWN | FLAT
    has_position: bool = False
    note: str = ""
    entry: str = "-"  # GO | first failing section-5 rule | - when FLAT


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def local_now() -> str:
    return datetime.now(MY_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _read_yaml_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):  # tolerate editors that save non-UTF-8
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _as_bool(v, default: bool = True) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def read_selection(config_dir: str | Path) -> dict[str, bool] | None:
    """{SYMBOL: enabled} from scan-selection.yml, or None when the file is absent.

    Absent file (tests, scratch dirs) means every pair is enabled.
    """
    import yaml

    path = Path(config_dir) / "scan-selection.yml"
    if not path.exists():
        return None
    try:
        cfg = yaml.safe_load(_read_yaml_text(path)) or {}
    except Exception:
        return None
    out = {}
    for sym, entry in ((cfg.get("pairs") or {}).items()):
        out[str(sym).strip()] = bool((entry or {}).get("enabled", True))
    return out


def read_limits(config_dir: str | Path) -> float:
    """Weekly halt threshold from _base.yaml limits. Default 15.0."""
    import yaml

    try:
        cfg = yaml.safe_load(_read_yaml_text(Path(config_dir) / "_base.yaml")) or {}
        return float((cfg.get("limits") or {}).get("weekly_loss_pct", 15.0))
    except Exception:
        return 15.0


def flatten_strategy(cfg: dict) -> dict:
    """The `strategy` block as one flat dict.

    _base.yaml groups keys under bias / entry / risk sections; older files and
    tests keep them flat. Both layouts merge into the same keys.
    """
    flat: dict = {}
    for key, val in ((cfg or {}).get("strategy") or {}).items():
        if isinstance(val, dict):
            flat.update(val)
        else:
            flat[key] = val
    return flat


def load_pairs(config_dir: str | Path) -> list[dict]:
    """Read per-pair yamls. Strategy comes solely from _base.yaml's `strategy`.

    A pair-level `strategy` key is ignored by design (single source of truth).
    """
    import yaml

    config_dir = Path(config_dir)
    base_strat: dict = {}
    try:
        base_cfg = yaml.safe_load(_read_yaml_text(config_dir / "_base.yaml")) or {}
        base_strat = flatten_strategy(base_cfg)
    except Exception:
        pass
    pairs: list[dict] = []
    for path in sorted(config_dir.glob("*.yaml")) + sorted(config_dir.glob("*.yml")):
        if (path.stem in SKIP_FILES or path.stem.startswith("_")
                or path.stem.endswith(SKIP_SUFFIX)):
            continue
        try:
            cfg = yaml.safe_load(_read_yaml_text(path)) or {}
            symbol = str(cfg.get("symbol") or path.stem).strip()
            strat = dict(base_strat)  # base only; pair-level strategy is ignored
            try:
                sep = float(strat.get("sep_atr", SEP_MIN_DEFAULT))
            except (TypeError, ValueError):
                sep = SEP_MIN_DEFAULT
            hr1 = str(strat.get("hr1", "a")).lower()
            if hr1 not in ("a", "b", "c"):
                hr1 = "a"
            pairs.append({"name": path.stem, "symbol": symbol, "sep": sep, "hr1": hr1,
                          "params": strat,
                          "use_atr_sep": _as_bool(strat.get("use_atr_sep", True)),
                          "costs": dict((cfg.get("costs") or {}))})
        except Exception as exc:
            pairs.append({"name": path.stem, "symbol": path.stem,
                          "sep": SEP_MIN_DEFAULT, "hr1": "a", "use_atr_sep": True,
                          "params": {},
                          "costs": {},
                          "load_error": f"{path.name}: {exc}"})
    return pairs


def _load_mt5():
    # Import-guarded: tests and CI import this module without a terminal.
    try:
        import MetaTrader5 as mt5  # type: ignore[import]
    except ImportError:
        return None
    return mt5


def resolve_symbol(mt5, symbol: str) -> str | None:
    if mt5.symbol_info(symbol) is not None:
        return symbol
    for suffix in ("m", ".", "_m", "m.", "pro", ".pro"):
        if mt5.symbol_info(symbol + suffix) is not None:
            return symbol + suffix
    return None


def has_open_position(mt5, broker_symbol: str) -> bool:
    try:
        positions = mt5.positions_get(symbol=broker_symbol)
    except Exception:
        return False
    return bool(positions)


def _utc(ts: int) -> str:
    # Epoch seconds are absolute, so UTC conversion needs no broker-tz guess.
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def poll(mt5, pairs: list[dict], h4_bars: int = H4_BARS,
         h1_bars: int = H1_BARS) -> tuple[list[PairRow], dict]:
    """Fetch closed bars per pair. Returns (rows, {symbol: last_closed_H1_time})."""
    rows: list[PairRow] = []
    times: dict[str, int] = {}
    for p in pairs:
        symbol = p["symbol"]
        if p.get("load_error"):
            rows.append(PairRow(symbol=symbol, ok=False, note=p["load_error"]))
            continue
        try:
            broker = resolve_symbol(mt5, symbol)
            if broker is None:
                rows.append(PairRow(symbol=symbol, ok=False, note="symbol not found"))
                continue
            mt5.symbol_select(broker, True)
            h1 = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 1, h1_bars)
            h4 = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H4, 1, h4_bars)
            if h1 is None or len(h1) == 0 or h4 is None or len(h4) == 0:
                rows.append(PairRow(symbol=symbol, ok=False, note="no closed-bar data"))
                continue
            h1df = pd.DataFrame(h1)
            h4df = pd.DataFrame(h4)
            times[symbol] = int(h1df["time"].iloc[-1])
            params = p.get("params") or {}
            warmup = int(params.get("warmup_bars", 300))
            b = h4_bias(h4df, p.get("sep", SEP_MIN_DEFAULT), p.get("hr1", "a"),
                        p.get("use_atr_sep", True), min_bars=warmup)
            bias = DISP[b.direction]
            entry = "-"
            if bias in ("UP", "DOWN"):
                res = check_entry(h1df, "LONG" if bias == "UP" else "SHORT", params)
                entry = "GO" if res["signal"] else (res["fail"] or "?")
            rows.append(PairRow(symbol=symbol, ok=True, bias=bias,
                                has_position=has_open_position(mt5, broker),
                                entry=entry))
        except Exception as exc:  # keep the panel alive when one pair fails
            rows.append(PairRow(symbol=symbol, ok=False, note=f"error: {exc}"))
    return rows, times


def render_panel(rows: list[PairRow], local_time: str, broker_time: str,
                 account: str, mode: str = "B1", weeks: dict | None = None,
                 loss_pct: float = 15.0) -> str:
    lines = [
        f"QuantTrader H4 bias panel (H4 {mode}, bias only)",
        f"local time : {local_time} (Malaysia, UTC+8)",
        f"broker time: {broker_time} (last H1 close, UTC)",
        f"account={account}  rule=repaint-on-new-H1-close-only",
    ]
    for tag, info in (weeks or {}).items():
        lines.append(f"week {tag}: {info['loss_pct']:+.2f}% (halt at -{loss_pct:g}%)")
    for tag, info in (weeks or {}).items():
        if info["halted"]:
            lines.append(f"HALTED ({tag}): weekly loss {info['loss_pct']:.2f}% >= {loss_pct:g}% "
                         f"- no new entries until next week")
    lines += [
        "",
        f"{'SYMBOL':<7} {'BIAS':<7} ENTRY",
        "",
    ]
    for r in rows:
        if not r.ok:
            lines.append(f"{r.symbol:<7} ERROR   ({r.note})")
            continue
        star = "*" if r.has_position else " "
        lines.append(f"{r.symbol:<7} {r.bias}{star:<2} {r.entry}")
    lines.append("")
    signal = [r.symbol for r in rows if r.ok and r.bias in ("UP", "DOWN")]
    flat = [r for r in rows if r.ok]
    if signal:
        lines.append(f"BIAS: {', '.join(signal)} hold H4 bias - ENTRY shows GO or the first failing rule.")
    else:
        lines.append(f"NONE DETECTED - all {len(flat)} pair(s) FLAT. No setup.")
    bad = [r.symbol for r in rows if not r.ok]
    if bad:
        lines.append(f"DATA ERROR - unreadable: {', '.join(bad)}.")
    if any(r.has_position for r in rows if r.ok):
        lines.append("* = open position")
    return "\n".join(lines) + "\n"


def should_rewrite(first: bool, last: dict | None, current: dict) -> bool:
    return first or last != current


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _mode(pairs: list[dict]) -> str:
    return "MA-only" if pairs and all(not p.get("use_atr_sep", True) for p in pairs) else "B1"


def _merge_stars(base: list[PairRow], more: list[PairRow]) -> list[PairRow]:
    """Star a symbol if either account holds a position. Error rows pass through."""
    stars = {r.symbol for r in more if r.ok and r.has_position}
    out = []
    for r in base:
        if r.ok and r.symbol in stars and not r.has_position:
            r = PairRow(r.symbol, True, r.bias, True, r.note, r.entry)
        out.append(r)
    return out


def _cycle(mt5, accounts, pairs, args, conditions: dict[str, str],
           loss_pct: float) -> tuple[list[PairRow], dict, dict]:
    """One pass over every enabled account: bias poll, records sync, weekly halt.

    The terminal holds one MT5 session, so accounts log in sequentially.
    History calls only; this function never sends orders. Returns
    (rows, {symbol: H1 time}, {account_tag: week_info}).
    """
    from quant import limits as lim
    from quant import records as rec

    merged: list[PairRow] | None = None
    times: dict[str, int] = {}
    weeks: dict[str, dict] = {}
    for acct in accounts:
        atag = "REAL" if acct.live else "DEMO"
        try:
            if not mt5.initialize(login=acct.login, password=acct.password, server=acct.server):
                print(f"DATA ERROR - {atag} initialize failed: {mt5.last_error()}", flush=True)
                continue
            try:
                rows, times = poll(mt5, pairs, args.bars)
                now = datetime.now(timezone.utc)
                deals = mt5.history_deals_get(now - timedelta(days=365), now) or ()
                try:
                    n = rec.sync_closed_positions(
                        mt5, Path(args.records_dir) / f"{atag.lower()}.csv",
                        magic=args.magic, conditions=conditions, account=atag, deals=deals)
                    if n:
                        print(f"records: +{n} closed position(s) -> {atag.lower()}.csv", flush=True)
                except Exception as exc:
                    print(f"records sync skipped ({atag}): {exc}", flush=True)
                try:
                    info_acc = mt5.account_info()
                    equity = float(getattr(info_acc, "equity", 0) or 0)
                except Exception:
                    equity = 0.0
                try:
                    weeks[atag] = lim.evaluate(
                        Path(args.memory_dir) / f"weekly_{atag.lower()}.json",
                        deals, args.magic, equity, loss_pct, now)
                except Exception as exc:
                    print(f"weekly halt check skipped ({atag}): {exc}", flush=True)
                merged = rows if merged is None else _merge_stars(merged, rows)
            finally:
                mt5.shutdown()
        except Exception as exc:
            print(f"DATA ERROR - {atag}: {exc}", flush=True)
    return merged or [], times, weeks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="H4 bias console panel (read-only, sends no orders).")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--journal", default=JOURNAL_DEFAULT)
    ap.add_argument("--records-dir", default=RECORDS_DEFAULT)
    ap.add_argument("--memory-dir", default=MEMORY_DEFAULT)
    ap.add_argument("--magic", type=int, default=100001)
    ap.add_argument("--bars", type=int, default=H4_BARS)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=POLL_INTERVAL)
    args = ap.parse_args(argv)

    from quant.config import get_accounts

    try:
        pairs = load_pairs(args.config_dir)
    except Exception as exc:
        print(f"DATA ERROR - no pair configs in {args.config_dir}: {exc}", flush=True)
        return 1
    selection = read_selection(args.config_dir)
    if selection is not None:
        dropped = [p["symbol"] for p in pairs if not selection.get(p["symbol"], True)]
        pairs = [p for p in pairs if selection.get(p["symbol"], True)]
        for sym in dropped:
            print(f"SKIP {sym} - disabled in scan-selection.yml", flush=True)
    if not pairs:
        print(f"DATA ERROR - no pair configs found in {args.config_dir}", flush=True)
        return 1
    loss_pct = read_limits(args.config_dir)

    from quant.journal import ensure_header

    try:
        ensure_header(args.journal)  # trade record exists from the first run; rows come with fills
    except Exception:
        pass

    mt5 = _load_mt5()
    if mt5 is None:
        print(render_panel(
            [PairRow(symbol=p["symbol"], ok=False,
                     note="MetaTrader5 unavailable (needs Windows + open terminal)") for p in pairs],
            local_now(), "-", "UNKNOWN", _mode(pairs)), flush=True)
        return 2

    try:
        accounts = get_accounts()  # every enabled account, each cycle; raises if none
    except Exception as exc:
        print(f"DATA ERROR - account config: {exc}", flush=True)
        return 2
    tag = "+".join("REAL" if a.live else "DEMO" for a in accounts)

    from quant import records as rec

    try:
        if args.once:
            rows, times, weeks = _cycle(mt5, accounts, pairs, args,
                                        rec.load_conditions(args.journal), loss_pct)
            broker = _utc(max(times.values())) if times else "-"
            print(render_panel(rows, local_now(), broker, tag, _mode(pairs),
                               weeks, loss_pct), flush=True)
            return 0
        last: dict | None = None
        first = True
        while True:
            rows, times, weeks = _cycle(mt5, accounts, pairs, args,
                                          rec.load_conditions(args.journal), loss_pct)
            if rows and should_rewrite(first, last, times):
                _clear()
                broker = _utc(max(times.values())) if times else "-"
                print(render_panel(rows, local_now(), broker, tag, _mode(pairs),
                                   weeks, loss_pct), flush=True)
                last = dict(times)
                first = False
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
