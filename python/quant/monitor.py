"""Regime-bias console + optional trading supervisor.

Default (no --trade): read-only, sends no orders.
`--trade` adds a trading loop on top of the panel: entries on closed
`timeframes.execution` bars, position adoption, portfolio caps, weekly halt,
trail/BE. Dry-run is the default state of that loop (plans + journal rows,
nothing sent); real orders require `--no-dry-run` AND exactly one enabled
account AND only the user launches it.

Repaint rule: the screen only redraws when a new execution-timeframe bar
closes. All bars are closed bars fetched via copy_rates_from_pos(...,
start_pos=1); the bias uses the last fully completed `timeframes.regime` bar
(allowed pairs: H1->H4, H4->D1, H1->D1, or the same timeframe). Empty state: NONE DETECTED when no pair
holds UP/DOWN bias. ENTRY column shows GO or the first failing section-5
rule. Each cycle also syncs closed positions and the weekly loss halt per
account.
"""
from __future__ import annotations

import argparse
import os
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant.bias import SEP_MIN_DEFAULT, bias_periods, h4_bias
from quant.rules import read_sizing, stop_sizing_conflict
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


def base_config_path(config_dir: str | Path, base_config: str | Path | None = None) -> Path:
    """An explicitly selected preset never replaces the active base file."""
    return Path(base_config) if base_config is not None else Path(config_dir) / "_base.yaml"


def read_limits(config_dir: str | Path, base_config: str | Path | None = None) -> float:
    """Weekly halt threshold from _base.yaml limits. Default 15.0."""
    import yaml

    try:
        cfg = yaml.safe_load(_read_yaml_text(base_config_path(config_dir, base_config))) or {}
        return float((cfg.get("limits") or {}).get("weekly_loss_pct", 15.0))
    except Exception:
        if base_config is not None:
            raise
        return 15.0


# timeframes.execution / timeframes.regime -> bar hours; locked combos only
TF_HOURS = {"H1": 1, "H4": 4, "D1": 24}
# Allowed execution -> bias hours; reversed chart roles remain unsupported.
TF_COMBOS = ((1, 4), (4, 24), (1, 24), (1, 1), (4, 4), (24, 24))


def read_timeframes(config_dir: str | Path, base_config: str | Path | None = None) -> tuple[str, str]:
    """(execution, regime) names from _base.yaml timeframes. Defaults H1/H4.

    Raises ValueError on an unknown or un-locked combo so every entry point
    (backtest, panel, trader) fails loud instead of silently resampling.
    """
    import yaml

    try:
        cfg = yaml.safe_load(_read_yaml_text(base_config_path(config_dir, base_config))) or {}
    except Exception:
        if base_config is not None:
            raise
        cfg = {}
    tf = dict(cfg.get("timeframes") or {})
    exec_tf = str(tf.get("execution") or "H1").upper()
    reg_tf = str(tf.get("regime") or "H4").upper()
    eh, rh = TF_HOURS.get(exec_tf), TF_HOURS.get(reg_tf)
    if eh is None or rh is None:
        raise ValueError(f"timeframes: unknown TF in execution={exec_tf} "
                         f"regime={reg_tf} (known: {sorted(TF_HOURS)})")
    if (eh, rh) not in TF_COMBOS:
        raise ValueError(f"timeframes: unsupported combo {exec_tf}->{reg_tf} "
                         f"(allowed: H1->H4, H4->D1, H1->D1, H1->H1, H4->H4 or D1->D1)")
    from quant.signals import validate_crossover
    validate_crossover(flatten_strategy(cfg))
    return exec_tf, reg_tf


def read_trade_cfg(config_dir: str | Path, base_config: str | Path | None = None) -> dict:
    """`--trade` knobs: the SAME _base.yaml keys the backtest engine reads.

    paths: live.magic/dry_run_default, risk.max_total_positions/max_ccy_net,
    risk.sizing_scope_usd.low/high, risk.stop_sizing, limits.max_trades_per_day/
    max_cost_ratio, limits.no_trade_ranges, costs (per-pair overrides merge on
    top later). Missing file/keys fall back to the engine's defaults; 0 = off.
    """
    import yaml

    from quant.limits import parse_no_trade_ranges, read_pair_limits, read_entry_hours

    try:
        cfg = yaml.safe_load(
            _read_yaml_text(base_config_path(config_dir, base_config))) or {}
    except Exception:
        if base_config is not None:
            raise
        cfg = {}
    risk = dict(cfg.get("risk") or {})
    lim = dict(cfg.get("limits") or {})
    scope = dict(risk.get("sizing_scope_usd") or {})
    live = dict(cfg.get("live") or {})
    default_lot, stop_sizing = read_sizing(risk)
    try:
        ranges = tuple(parse_no_trade_ranges(cfg))
    except ValueError:
        ranges = ()
    return {
        "magic": int(live.get("magic", 100001) or 100001),
        "dry_run_default": bool(live.get("dry_run_default", True)),
        "max_total_positions": int(risk.get("max_total_positions", 0) or 0),
        "max_ccy_net": int(risk.get("max_ccy_net", 0) or 0),
        "scale_lot_with_balance": _as_bool(risk.get("scale_lot_with_balance"), False),
        "balance_risk_pct": float(risk.get("balance_risk_pct", 3.0) or 0.0),
        "max_trades_per_day": int(lim.get("max_trades_per_day", 0) or 0),
        **read_pair_limits(lim),
        "entry_hours": read_entry_hours(lim),
        "max_cost_ratio": float(lim.get("max_cost_ratio", 0.10) or 0.0),
        "scope_low": float(scope.get("low", 0.0) or 0.0),
        "scope_high": float(scope.get("high", 0.0) or 0.0),
        "stop_sizing": stop_sizing,
        "default_lot": default_lot,
        "costs": dict(cfg.get("costs") or {}),
        "ranges": ranges,
    }


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


def load_pairs(config_dir: str | Path, base_config: str | Path | None = None) -> list[dict]:
    """Read per-pair yamls. Strategy comes solely from _base.yaml's `strategy`.

    A pair-level `strategy` key is ignored by design (single source of truth).
    """
    import yaml

    config_dir = Path(config_dir)
    base_strat: dict = {}
    try:
        base_cfg = yaml.safe_load(_read_yaml_text(base_config_path(config_dir, base_config))) or {}
        base_strat = flatten_strategy(base_cfg)
    except Exception:
        if base_config is not None:
            raise
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
         h1_bars: int = H1_BARS, exec_tf: str = "TIMEFRAME_H1",
         reg_tf: str = "TIMEFRAME_H4") -> tuple[list[PairRow], dict]:
    """Fetch closed bars per pair. Returns (rows, {symbol: last_closed_exec_time}).

    exec_tf/reg_tf are mt5 module ATTRIBUTE NAMES (resolved via getattr so
    mock mt5 doubles keep their own fake constants).
    """
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
            params = p.get("params") or {}
            crossover = bool(params.get("use_crossover_memory", False))
            history = int(params.get("crossover_history_bars", 6000)) if crossover else 0
            h1 = mt5.copy_rates_from_pos(broker, getattr(mt5, exec_tf), 1, max(h1_bars, history))
            h4 = mt5.copy_rates_from_pos(broker, getattr(mt5, reg_tf), 1, max(h4_bars, history))
            if h1 is None or len(h1) == 0 or h4 is None or len(h4) == 0:
                rows.append(PairRow(symbol=symbol, ok=False, note="no closed-bar data"))
                continue
            h1df = pd.DataFrame(h1)
            h4df = pd.DataFrame(h4)
            times[symbol] = int(h1df["time"].iloc[-1])
            warmup = int(params.get("warmup_bars", 300))
            # bias periods come from the same flat params the backtest uses;
            # defaults mirror the locked B1 constants, never re-tuned here
            bias_fast, bias_slow, bias_atr = bias_periods(params)
            b = h4_bias(h4df, p.get("sep", SEP_MIN_DEFAULT), p.get("hr1", "a"),
                         p.get("use_atr_sep", True), min_bars=warmup,
                         ema_fast=bias_fast, ema_slow=bias_slow, atr_n=bias_atr)
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
                 loss_pct: float = 15.0, banner: str | None = None,
                 regime: str = "H4", exec_tf: str = "H1") -> str:
    lines = [
        f"QuantTrader {regime} bias panel ({regime} {mode}, bias only)",
        f"local time : {local_time} (Malaysia, UTC+8)",
        f"broker time: {broker_time} (last {exec_tf} close, UTC)",
        f"account={account}  rule=repaint-on-new-{exec_tf}-close-only",
    ]
    if banner:
        lines.append(banner)
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


def _trade_pass(mt5, pairs, rows, times, tcfg: dict, atag: str, week: dict,
                deals, now: datetime) -> None:
    """The `--trade` beat inside one account's initialized session.

    Two jobs per pass, in order: manage what we already hold (sync ghosts,
    trail/BE), then attempt entries on new closed H1 bars for pairs with an
    UP/DOWN bias. Everything mutable lives in the trader's mem file; prints
    go to the console exactly once per finished event.
    """
    from quant import trader as tr

    if not tr.account_matches(mt5, tcfg["expected_account"]):
        print("DATA ERROR - trading account changed; refusing entries and modifications.", flush=True)
        return
    journal_path = tcfg["journal"]
    mem_path = tcfg["mem_path"]
    mem = tr.load_mem(mem_path)
    journal_rows = tr.journal_by_position(journal_path)
    row_by_sym = {r.symbol: r for r in rows if r.ok}
    booked = {(v or {}).get("symbol") for v in (mem.get("open") or {}).values()}
    for p in pairs:
        if p.get("load_error"):
            continue
        sym = p["symbol"]
        row = row_by_sym.get(sym)
        if sym in booked or (row is not None and row.has_position):
            # trailing/ghost sync runs every pass, poll error or not
            management = tr.manage_book(mt5, sym, sym, p["params"], tcfg["magic"],
                                     tcfg["dry"], journal_path, mem, journal_rows,
                                      expected_account=tcfg["expected_account"],
                                      **({"exec_tf": tcfg["base"].get("exec_tf", "H4"), "memory_path": mem_path}
                                         if p["params"].get("use_crossover_exit", False) else {}))
            for m in management:
                print(f"trade {sym}: {m}", flush=True)
            if any(m.startswith("EXIT") for m in management):
                tr.save_mem(mem_path, mem)
                continue  # Never turn a close into an immediate reverse order in the same pass.
        crossover = bool(p["params"].get("use_crossover_memory", False))
        if row is None or (row.bias not in ("UP", "DOWN") and not crossover):
            continue
        cfg = dict(tcfg["base"])
        cfg["account_store"] = tcfg.get("account_store")
        cfg["recording_error"] = tcfg.get("recording_error")
        cfg["costs"] = {**tcfg["base_costs"], **p["costs"]}
        cfg["halted"] = bool((week or {}).get("halted"))
        direction = dir_of(row.bias) if row.bias in ("UP", "DOWN") else "NEUTRAL"
        msg = tr.trade_on_bar(mt5, sym, sym, direction=direction,
                              bar_secs=int(times.get(sym) or 0), now=now,
                              magic=tcfg["magic"], dry=tcfg["dry"],
                              params=p["params"], journal_path=journal_path,
                              mem=mem, cfg=cfg, deals=deals, ranges=tcfg["ranges"])
        if msg and msg != "seen":
            print(f"trade {sym}: {msg}", flush=True)
        if crossover:
            state = (mem.get("crossovers") or {}).get(sym) or {}
            latest = (state.get("indicators") or {}).get("latest") or {}
            if latest:
                cycle = latest.get("crossover_time") or "not found"
                status = msg if msg and msg != "seen" else "remembered"
                row.entry = (f"{status} | cross {cycle} | "
                             f"{state.get('used', 0)}/{p['params'].get('crossover_max_entries', 2)} used")
        # Persist each decision before another pair can use the remaining weekly quota.
        tr.save_mem(mem_path, mem)
    tr.save_mem(mem_path, mem)


def dir_of(bias: str) -> str:
    return "LONG" if bias == "UP" else "SHORT"


def _cycle(mt5, accounts, pairs, args, conditions: dict[str, str],
           loss_pct: float, tcfg: dict | None = None
           ) -> tuple[list[PairRow], dict, dict]:
    """One pass over every enabled account: bias poll, records sync, weekly halt.

    The terminal holds one MT5 session, so accounts log in sequentially.
    Read-only unless tcfg enables the trading pass. Returns
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
                if tcfg:
                    from quant.trader import account_matches
                    if not account_matches(mt5, tcfg["expected_account"]):
                        print(f"DATA ERROR - {atag} login/server/account type mismatch; refusing to trade.", flush=True)
                        continue
                rows, times = poll(mt5, pairs, args.bars,
                                   exec_tf=getattr(args, "exec_tf", "TIMEFRAME_H1"),
                                   reg_tf=getattr(args, "reg_tf", "TIMEFRAME_H4"))
                now = datetime.now(timezone.utc)
                try:
                    deals = mt5.history_deals_get(now - timedelta(days=365), now)
                except Exception as exc:
                    deals = None
                    print(f"DATA ERROR - {atag} deal history: {exc}", flush=True)
                try:
                    n = rec.sync_closed_positions(
                        mt5, Path(args.records_dir) / f"{atag.lower()}.csv",
                        magic=args.magic, conditions=conditions, account=atag, deals=deals or ())
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
                        Path(args.memory_dir) / f"weekly_{atag.lower()}{'_' + str(args.magic) if getattr(args, 'base_config', None) else ''}.json",
                        deals or (), args.magic, equity, loss_pct, now)
                except Exception as exc:
                    print(f"weekly halt check skipped ({atag}): {exc}", flush=True)
                # Preserve raw broker deals, including fees and partial fills, per account.
                store = None
                if getattr(args, "record_performance", False) or (tcfg and not tcfg["dry"]):
                    try:
                        from quant.account_store import AccountStore, write_performance
                        info = mt5.account_info()
                        if (info is None or int(info.login) != int(acct.login)
                                or str(info.server) != acct.server
                                or int(info.trade_mode) != (2 if acct.live else 0)):
                            raise ValueError("Recording account identity mismatch")
                        store = AccountStore(Path(args.records_dir) / "accounts", info)
                        store.sync_from_broker(mt5)
                        write_performance(store, args.performance_settings, args.magic)
                        if tcfg:
                            tcfg["account_store"] = store
                            tcfg["recording_error"] = bool(store.unresolved())
                        if store.unresolved():
                            print(f"RECORDING ALERT - {atag}: unresolved orders; new entries blocked", flush=True)
                    except Exception as exc:
                        if tcfg:
                            tcfg["account_store"] = None
                            tcfg["recording_error"] = True
                        print(f"RECORDING ERROR - {atag}: {exc}; new entries blocked", flush=True)
                if tcfg:
                    _trade_pass(mt5, pairs, rows, times, tcfg, atag,
                                weeks.get(atag) or {}, deals, now)
                if store is not None:
                    # Catch fills/fees created during this pass, not just on the next poll.
                    try:
                        store.sync_from_broker(mt5)
                        write_performance(store, args.performance_settings, args.magic)
                    except Exception as exc:
                        print(f"RECORDING ALERT - {atag}: post-pass sync failed: {exc}", flush=True)
                merged = rows if merged is None else _merge_stars(merged, rows)
            finally:
                mt5.shutdown()
        except Exception as exc:
            print(f"DATA ERROR - {atag}: {exc}", flush=True)
    return merged or [], times, weeks


@contextmanager
def _terminal_lock(path: Path):
    """One panel/trader per workspace; OS releases the byte lock after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        lock.seek(0, 2)
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another panel/trader is already running in this workspace. Close it first.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    with ExitStack() as resources:
        return _main(argv, resources)


def _main(argv, resources: ExitStack) -> int:
    ap = argparse.ArgumentParser(
        description="Regime-bias console panel; add --trade for the trading loop (dry-run default).")
    ap.add_argument("--config-dir", default="configs")
    ap.add_argument("--base-config", default=None,
                    help="select a shared preset without changing configs/_base.yaml")
    ap.add_argument("--journal", default=JOURNAL_DEFAULT)
    ap.add_argument("--records-dir", default=RECORDS_DEFAULT)
    ap.add_argument("--memory-dir", default=MEMORY_DEFAULT)
    ap.add_argument("--magic", type=int, default=None,
                    help="override live.magic from _base.yaml (default 100001)")
    ap.add_argument("--bars", type=int, default=H4_BARS)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=POLL_INTERVAL)
    ap.add_argument("--trade", action="store_true",
                     help="enable the trading loop (entries + management). OFF = read-only panel.")
    ap.add_argument("--account", choices=("demo", "real"),
                    help="select one enabled account; never overrides USE_DEMO/USE_REAL")
    ap.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None,
                     help="trade planner only, nothing sent (default: live.dry_run_default=true)")
    ap.add_argument("--record-performance", action=argparse.BooleanOptionalAction, default=True,
                    help="store broker deals/equity locally; order auditing is mandatory for actual sends")
    args = ap.parse_args(argv)
    from quant.performance import PerformanceSettings
    import yaml

    try:
        base = yaml.safe_load(_read_yaml_text(base_config_path(args.config_dir, args.base_config))) or {}
        args.performance_settings = PerformanceSettings.from_dict(base.get("performance"))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"performance config error: {exc}", flush=True)
        return 2
    preset = {"base_config": args.base_config} if args.base_config else {}

    try:
        resources.enter_context(_terminal_lock(Path(__file__).resolve().parents[2] / "memory" / "monitor.lock"))
    except (OSError, RuntimeError) as exc:
        print(f"DATA ERROR - {exc}", flush=True)
        return 2

    from quant.config import get_accounts

    try:
        pairs = load_pairs(args.config_dir, **preset)
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
    # timeframes: locked combos only; every fetch/gate below reads these
    try:
        loss_pct = read_limits(args.config_dir, **preset)
        args.exec_tf, args.reg_tf = read_timeframes(args.config_dir, **preset)
        if args.base_config and args.magic is None:
            args.magic = read_trade_cfg(args.config_dir, **preset)["magic"]
    except (OSError, TypeError, ValueError) as exc:
        print(f"config error: {exc}", flush=True)
        return 2

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
        accounts = get_accounts(args.account) if args.account else get_accounts()
    except Exception as exc:
        print(f"DATA ERROR - account config: {exc}", flush=True)
        return 2
    tag = "+".join("REAL" if a.live else "DEMO" for a in accounts)

    tcfg: dict | None = None
    banner: str | None = None
    if args.trade:
        # the loop trades THE ONE enabled account; two enabled = refuse loudly
        # so demo and real can never fire together
        if len(accounts) != 1:
            print("DATA ERROR - --trade needs exactly ONE enabled account "
                  "(USE_DEMO / USE_REAL). Refusing to trade.", flush=True)
            return 2
        atag = "REAL" if accounts[0].live else "DEMO"
        try:
            tradecfg = read_trade_cfg(args.config_dir, **preset)
        except (TypeError, ValueError) as exc:
            print(f"DATA ERROR - {exc}. Refusing to trade.", flush=True)
            return 2
        magic = args.magic if args.magic is not None else tradecfg["magic"]
        dry = tradecfg["dry_run_default"] if args.dry_run is None else args.dry_run
        args.magic = magic  # records sync + weekly halt must see the same magic
        # percent sizing and a fixed lot cannot run together
        stop_sizing = dict(tradecfg["stop_sizing"] or {})
        conflict = stop_sizing_conflict(stop_sizing, tradecfg["scale_lot_with_balance"])
        if conflict:
            print(f"DATA ERROR - {conflict}. Refusing to trade.", flush=True)
            return 2
        tcfg = {
            "expected_account": {"login": accounts[0].login, "server": accounts[0].server,
                                 "live": accounts[0].live},
            "magic": magic, "dry": dry, "journal": args.journal,
            "mem_path": Path(args.memory_dir) / f"live_{atag.lower()}{'_' + str(magic) if args.base_config else ''}.json",
            "ranges": tradecfg["ranges"], "base_costs": tradecfg["costs"],
            "base": {
                "expected_account": {"login": accounts[0].login, "server": accounts[0].server,
                                     "live": accounts[0].live},
                "max_total_positions": tradecfg["max_total_positions"],
                "max_ccy_net": tradecfg["max_ccy_net"],
                "max_trades_per_day": tradecfg["max_trades_per_day"],
                "max_trades_per_week": tradecfg["max_trades_per_week"],
                "max_trades_per_pair_per_week": tradecfg["max_trades_per_pair_per_week"],
                "disable_pair_after_daily_loss": tradecfg["disable_pair_after_daily_loss"],
                "entry_hours": tradecfg["entry_hours"],
                "max_cost_ratio": tradecfg["max_cost_ratio"],
                "scale_lot_with_balance": tradecfg["scale_lot_with_balance"],
                "balance_risk_pct": tradecfg["balance_risk_pct"],
                "scope_low": tradecfg["scope_low"],
                "scope_high": tradecfg["scope_high"],
                 "stop_sizing": stop_sizing,
                 "default_lot": tradecfg["default_lot"],
                 "exec_tf": args.exec_tf,  # execution TF name for _gate_check
                 "memory_path": Path(args.memory_dir) / f"live_{atag.lower()}{'_' + str(magic) if args.base_config else ''}.json",
            },
        }
        banner = (f"TRADER: ON ({'DRY-RUN - plans only, nothing sent' if dry
                  else f'REAL ORDERS on {atag}'}) magic={magic} "
                  f"caps: total={tcfg['base']['max_total_positions'] or 'off'} "
                  f"ccy-net={tcfg['base']['max_ccy_net'] or 'off'} "
                   f"day={tcfg['base']['max_trades_per_day'] or 'off'} "
                   f"week={tcfg['base']['max_trades_per_week'] or 'off'}")

    from quant import records as rec

    try:
        if args.once:
            rows, times, weeks = _cycle(mt5, accounts, pairs, args,
                                        rec.load_conditions(args.journal), loss_pct,
                                        tcfg)
            broker = _utc(max(times.values())) if times else "-"
            print(render_panel(rows, local_now(), broker, tag, _mode(pairs),
                               weeks, loss_pct, banner,
                               regime=args.reg_tf, exec_tf=args.exec_tf), flush=True)
            if banner:
                print(banner, flush=True)
            return 0
        last: dict | None = None
        first = True
        while True:
            rows, times, weeks = _cycle(mt5, accounts, pairs, args,
                                          rec.load_conditions(args.journal), loss_pct,
                                          tcfg)
            if rows and should_rewrite(first, last, times):
                _clear()
                broker = _utc(max(times.values())) if times else "-"
                print(render_panel(rows, local_now(), broker, tag, _mode(pairs),
                                   weeks, loss_pct, banner,
                                   regime=args.reg_tf, exec_tf=args.exec_tf), flush=True)
                last = dict(times)
                first = False
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
