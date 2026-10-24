"""Account-separated local JSON records. Broker deals are the source of truth."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from quant.performance import PerformanceSettings, account_performance


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                      prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=1, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def account_directory(root, info) -> Path:
    identity = f"{info.server}|{int(info.login)}|{int(info.trade_mode)}"
    # Hash the server so broker names cannot become unsafe filesystem paths.
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    kind = "demo" if int(info.trade_mode) == 0 else "real" if int(info.trade_mode) == 2 else "contest"
    return Path(root) / f"{kind}_{int(info.login)}_{digest}"


def _plain(item):
    return dict(item._asdict()) if hasattr(item, "_asdict") else vars(item).copy()


class AccountStore:
    """Single writer (monitor lock); atomic replacement, never an empty-history fallback."""

    def __init__(self, root, info):
        self.directory = account_directory(root, info)
        self.path = self.directory / "account.json"
        self.identity = {"login": int(info.login), "server": str(info.server),
                         "trade_mode": int(info.trade_mode), "currency": str(info.currency)}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if self.data["identity"] != self.identity:
                raise ValueError("Stored account identity mismatch")
        else:
            self.data = {"identity": self.identity, "deals": {}, "snapshots": [], "intents": {}}

    def save(self):
        atomic_json(self.path, self.data)

    def begin(self, key: str, request: dict):
        previous = self.data["intents"].get(key)
        if previous is not None and previous["status"] not in ("rejected", "not_sent"):
            raise ValueError("Entry already recorded; reconcile broker before retry")
        attempts = []
        if previous is not None:
            attempts = previous.get("attempts", []) + [
                {name: value for name, value in previous.items() if name != "attempts"}]
        self.data["intents"][key] = {"request": request, "status": "pending", "attempts": attempts}
        self.save()  # Write ahead: a crash after order_send must not authorize a resend.

    def result(self, key, result, *, sent: bool = True):
        item = self.data["intents"][key]
        item["response"] = _plain(result) if result is not None else None
        if not sent:
            item["status"] = "not_sent"
        elif getattr(result, "retcode", None) in REJECTED_CODES:
            item["status"] = "rejected"
        else:
            item["status"] = "unconfirmed"
        self.save()

    def sync_from_broker(self, mt5):
        """Bracket history with account reads; do not combine different balances."""
        before = mt5.account_info()
        sampled_at = datetime.now(timezone.utc)
        if before is None:
            raise ValueError("Broker account unavailable; recording incomplete")
        deals = mt5.history_deals_get(sampled_at - timedelta(days=365), datetime.now(timezone.utc))
        positions = mt5.positions_get()
        after = mt5.account_info()
        if after is None or account_directory(self.directory.parent, after) != self.directory:
            raise ValueError("Account changed during snapshot; retry broker sync")
        if any(float(getattr(before, field, 0)) != float(getattr(after, field, 0))
               for field in ("balance", "credit")):
            raise ValueError("Account balance/credit changed during snapshot; retry broker sync")
        self.reconcile(before, deals, positions, sampled_at)

    def reconcile(self, info, deals, positions, now):
        if deals is None or positions is None:
            raise ValueError("Broker history/positions unavailable; recording incomplete")
        identity = {"login": int(info.login), "server": str(info.server),
                    "trade_mode": int(info.trade_mode), "currency": str(info.currency)}
        if identity != self.identity:
            raise ValueError("Account changed during reconciliation")
        for deal in deals:
            self.data["deals"][str(int(deal.ticket))] = _plain(deal)
        self.data["positions"] = [_plain(p) for p in positions]
        for item in self.data["intents"].values():
            response = item.get("response") or {}
            deal_id = str(response.get("deal", ""))
            order_id = response.get("order", 0)
            matches = [d for d in self.data["deals"].values()
                       if (deal_id != "0" and str(d["ticket"]) == deal_id)
                       or (order_id and d.get("order") == order_id)]
            if matches:
                item["status"] = "broker_confirmed"
                item["deals"] = [d["ticket"] for d in matches]
            elif response.get("retcode") in REJECTED_CODES:
                item["status"] = "rejected"
        stamp = pd.Timestamp(now).isoformat()
        snapshot = {"time": stamp, "equity": float(info.equity), "balance": float(info.balance)}
        snapshots = self.data["snapshots"]
        if snapshots and snapshots[-1]["time"] == stamp:
            snapshots[-1] = snapshot
        else:
            snapshots.append(snapshot)
        self.data["last_sync"] = stamp
        self.save()

    def unresolved(self):
        return [k for k, v in self.data["intents"].items()
                if v["status"] in ("pending", "unconfirmed")]

    def performance(self, settings=None, magic=None):
        settings = settings or PerformanceSettings()
        deals = list(self.data["deals"].values())
        # The shared calculator uses the backtest's historical column name; live amounts
        # remain in the account's native currency, never falsely exported as USD.
        curve = pd.DataFrame(self.data["snapshots"]).rename(columns={"equity": "usd"})
        # MT5 balance/credit movements are external capital, not strategy returns.
        flows = [{"time": (pd.Timestamp(d["time_msc"], unit="ms", tz="UTC")
                           if (d.get("time_msc") or 0) > 0 else pd.Timestamp(d["time"], unit="s", tz="UTC")),
                  "amount": float(d.get("profit", 0))}
                 for d in deals if d.get("type") in (2, 3)]
        result = account_performance(curve, settings, pd.DataFrame(flows))
        def totals(selected):
            fields = {field: sum(float(d.get(field, 0)) for d in selected
                                 if field != "profit" or d.get("type") not in (2, 3))
                      for field in ("profit", "commission", "swap", "fee")}
            return {**fields, "net_realized": sum(fields.values())}

        result.update(identity=self.identity, whole_account=True, deal_totals=totals(deals),
                      last_sync=self.data.get("last_sync"),
                      strategy_deal_totals=(totals([d for d in deals if d.get("magic") == magic])
                                            if magic is not None else None),
                      strategy_magic=magic, unresolved=self.unresolved(),
                      warning="Ratios are whole-account, net of broker costs. Strategy deal totals "
                              "exclude unallocated account charges. No historical equity is invented.")
        return result


# MT5 explicit rejection codes; placed/partial/timeout/unknown are not safe rejections.
REJECTED_CODES = (10004, 10006, 10007, 10013, 10014, 10015, 10016, 10017,
                  10018, 10019, 10020, 10021, 10022, 10024, 10026, 10027,
                  10030, 10033, 10034, 10035, 10040, 10042, 10043, 10044, 10046)


def write_performance(store, settings=None, magic=None):
    from quant.performance import performance_html

    result = store.performance(settings, magic)
    atomic_json(store.directory / "performance.json", result)
    pd.DataFrame(store.data["deals"].values()).to_csv(store.directory / "deals.csv", index=False)
    pd.DataFrame(store.data["snapshots"]).to_csv(store.directory / "equity.csv", index=False)
    ratios = (performance_html(result, result["warning"]) if result["settings"]["enabled"]
              else '<p>Performance ratios disabled.</p>')
    html = ('<!doctype html><html><head><meta charset="utf-8"><title>Account performance</title>'
            '</head><body>' + ratios + '</body></html>')
    from html import escape

    sections = []
    for label, totals in (("Whole-account recorded deals", result["deal_totals"]),
                          (f'Strategy recorded deals (magic {magic})', result["strategy_deal_totals"])):
        if totals is not None:
            rows = "".join(f"<tr><td>{escape(key)}</td><td>{value:.2f}</td></tr>"
                           for key, value in totals.items())
            sections.append(f"<h2>{escape(label)}</h2><table>{rows}</table>")
    identity = store.identity
    kind = "DEMO" if identity["trade_mode"] == 0 else "REAL" if identity["trade_mode"] == 2 else "CONTEST"
    header = (f'<h1>{kind}: {escape(str(identity["server"]))} / {identity["login"]}</h1>'
              f'<p>Account currency: {escape(identity["currency"])}. '
              f'Last broker sync: {escape(result["last_sync"] or "N/A")}. '
              f'Unresolved orders: {len(result["unresolved"])}. '
              'Deal totals cover stored broker history, not necessarily account inception. '
              'Ratios cover the equity period shown above.</p>')
    html = html.replace("<body>", "<body>" + header).replace("</body>", "".join(sections) + "</body>")
    (store.directory / "performance.html").write_text(html, encoding="utf-8")
    return result


def recorded_open(mt5, store, request):
    """One-shot executor write-ahead; uncertainty blocks subsequent new entries."""
    from uuid import uuid4

    if store.unresolved():
        raise ValueError("Unresolved order: reconcile with broker before opening another trade")
    info = mt5.account_info()
    if info is None or account_directory(store.directory.parent, info) != store.directory:
        raise ValueError("Account changed before order recording; nothing sent")
    key = uuid4().hex
    store.begin(key, request)
    result = mt5.order_send(request)
    try:
        store.result(key, result)
    except Exception as exc:
        # Keep the broker response so the caller can still protect/close a filled position.
        print(f"RECORDING ALERT - response could not be saved: {exc}; CHECK TERMINAL", flush=True)
    return result


def main(argv=None):
    """Rebuild an account report from local files only. Never connects to MT5."""
    import argparse
    from types import SimpleNamespace

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--account-dir", required=True)
    parser.add_argument("--risk-free-rate", type=float, default=0.0)
    parser.add_argument("--minimum-return", type=float, default=0.0)
    parser.add_argument("--periods-per-year", type=float, default=252.0)
    parser.add_argument("--minimum-observations", type=int, default=20)
    parser.add_argument("--magic", type=int)
    args = parser.parse_args(argv)
    path = Path(args.account_dir)
    identity = json.loads((path / "account.json").read_text(encoding="utf-8"))["identity"]
    store = AccountStore(path.parent, SimpleNamespace(**identity))
    if store.directory.resolve() != path.resolve():
        parser.error("account-dir name does not match its saved account identity")
    settings = PerformanceSettings(risk_free_rate=args.risk_free_rate,
                                   minimum_return=args.minimum_return,
                                   periods_per_year=args.periods_per_year,
                                   minimum_observations=args.minimum_observations)
    result = write_performance(store, settings, args.magic)
    print(f"{store.directory / 'performance.html'}: {result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
