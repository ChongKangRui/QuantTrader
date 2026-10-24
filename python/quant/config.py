"""Credential + account selection. Demo and real are independent flags; both may be true."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


USE_DEMO: bool = _flag("USE_DEMO", "true")
USE_REAL: bool = _flag("USE_REAL", "false")


@dataclass(frozen=True)
class Account:
    login: int
    password: str
    server: str
    live: bool


def _load(prefix: str, live: bool) -> Account:
    login = os.getenv(prefix + "LOGIN", "").strip()
    password = os.getenv(prefix + "PASSWORD", "").strip()
    server = os.getenv(prefix + "SERVER", "").strip()
    missing = [prefix + k for k, v in (("LOGIN", login), ("PASSWORD", password), ("SERVER", server)) if not v]
    if missing:
        raise RuntimeError(f"Missing {missing} in .env.")
    return Account(login=int(login), password=password, server=server, live=live)


def get_accounts(selection: str | None = None) -> list[Account]:
    """Enabled accounts, optionally narrowed without overriding either enable flag."""
    if selection not in (None, "demo", "real"):
        raise ValueError("account selection must be demo or real")
    if selection == "demo":
        if not USE_DEMO:
            raise RuntimeError("Demo account is disabled (USE_DEMO).")
        return [_load("MT5_DEMO_", live=False)]
    if selection == "real":
        if not USE_REAL:
            raise RuntimeError("Real account is disabled (USE_REAL).")
        return [_load("MT5_REAL_", live=True)]
    accounts: list[Account] = []
    if USE_DEMO:
        accounts.append(_load("MT5_DEMO_", live=False))
    if USE_REAL:
        accounts.append(_load("MT5_REAL_", live=True))
    if not accounts:
        raise RuntimeError("Neither USE_DEMO nor USE_REAL is true in .env.")
    return accounts


def get_account() -> Account:
    """Single-account helper. Fails if not exactly one account enabled."""
    accounts = get_accounts()
    if len(accounts) != 1:
        raise RuntimeError("Expected exactly one of USE_DEMO/USE_REAL to be true for this entrypoint.")
    return accounts[0]
