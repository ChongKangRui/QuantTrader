"""Shared fee-net account performance. No terminal or database required."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceSettings:
    enabled: bool = True
    risk_free_rate: float = 0.0  # annual decimal, not percent
    minimum_return: float = 0.0  # annual Sortino target
    periods_per_year: float = 252.0
    minimum_observations: int = 20

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError("performance.enabled must be boolean")
        for value in (self.risk_free_rate, self.minimum_return):
            if not math.isfinite(value) or value <= -1:
                raise ValueError("annual performance rates must be finite and greater than -1")
        if not math.isfinite(self.periods_per_year) or self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        if (not isinstance(self.minimum_observations, int) or isinstance(self.minimum_observations, bool)
                or self.minimum_observations < 2):
            raise ValueError("minimum_observations must be at least 2")

    @classmethod
    def from_dict(cls, values=None):
        return cls(**(values or {}))


SHARPE_BANDS = (
    ("Below 0", "Underperforming the risk-free return"),
    ("0 to below 0.5", "Weak risk-adjusted performance"),
    ("0.5 to below 1.0", "Moderate"),
    ("1.0 to below 1.5", "Good"),
    ("1.5 through 2.0", "Very good"),
    ("Above 2.0 through 3.0", "Excellent"),
    ("Above 3.0", "Exceptional; worth investigating carefully"),
)


def sharpe_interpretation(value) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    for ceiling, label in ((0, 0), (0.5, 1), (1, 2), (1.5, 3)):
        if value < ceiling:
            return SHARPE_BANDS[label][1]
    return SHARPE_BANDS[4 if value <= 2 else 5 if value <= 3 else 6][1]


def account_performance(curve: pd.DataFrame, settings=None,
                        cashflows: pd.DataFrame | None = None) -> dict:
    """UTC weekday close returns; cash flows use time-weighted Modified Dietz.

    Equity must ALREADY include costs. Never subtract broker fees a second time.
    Missing weekdays are not filled. With cash flows, returns are an estimate
    unless valuations are available at every cash flow.
    """
    settings = settings or PerformanceSettings()
    out = {"sharpe_ratio": None, "sortino_ratio": None, "calmar_ratio": None,
           "sharpe_interpretation": "N/A", "observations": 0,
           "annualized_return": None, "max_drawdown_pct": None,
           "settings": asdict(settings), "reason": "Disabled"}
    if not settings.enabled:
        return out

    def unavailable(reason):
        out["reason"] = reason
        return out

    if curve.empty or not {"time", "usd"}.issubset(curve):
        return unavailable("No account equity history")
    frame = curve[["time", "usd"]].copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="raise")
    frame = frame.sort_values("time").drop_duplicates("time", keep="last")
    values = pd.to_numeric(frame["usd"], errors="raise")
    if not np.isfinite(values).all() or (values <= 0).any():
        return unavailable("Non-positive or invalid equity")
    series = pd.Series(values.to_numpy(float), index=pd.DatetimeIndex(frame["time"]))
    # Weekend changes belong to the next weekday return, not an extra annualized period.
    daily = series.resample("D").last()
    daily = daily[daily.index.dayofweek < 5]
    if daily.isna().any():
        return unavailable("Missing weekday equity snapshots; no gaps filled")
    times = series.index.to_series().resample("D").last().reindex(daily.index)
    out["observations"] = max(len(daily) - 1, 0)
    if len(daily):
        out["start"] = times.iloc[0].isoformat()
        out["end"] = times.iloc[-1].isoformat()
    if len(daily) - 1 < settings.minimum_observations:
        return unavailable("Insufficient daily observations")
    flows = None
    if cashflows is not None and not cashflows.empty:
        flows = cashflows.copy()
        flows["time"] = pd.to_datetime(flows["time"], utc=True, errors="raise")
        flows["amount"] = pd.to_numeric(flows["amount"], errors="raise")
        if not np.isfinite(flows["amount"]).all():
            return unavailable("Invalid cash flows")
    returns = []
    for i in range(1, len(daily)):
        start, end = times.iloc[i - 1], times.iloc[i]
        capital, flow = float(daily.iloc[i - 1]), 0.0
        if flows is not None:
            selected = flows[(flows["time"] > start) & (flows["time"] <= end)]
            flow = float(selected["amount"].sum())
            weights = (end - selected["time"]).dt.total_seconds() / (end - start).total_seconds()
            capital += float((weights * selected["amount"]).sum())
        if capital <= 0:
            return unavailable("Non-positive cash-flow-adjusted capital")
        returns.append((float(daily.iloc[i]) - float(daily.iloc[i - 1]) - flow) / capital)
    r = np.asarray(returns)
    if not np.isfinite(r).all() or (r <= -1).any():
        return unavailable("Invalid cash-flow-adjusted returns")
    annual = settings.periods_per_year
    rf = math.expm1(math.log1p(settings.risk_free_rate) / annual)
    target = math.expm1(math.log1p(settings.minimum_return) / annual)
    deviation = float(np.std(r - rf, ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(r - target, 0) ** 2)))
    if deviation > 1e-12:
        out["sharpe_ratio"] = float(np.mean(r - rf) / deviation * math.sqrt(annual))
    if downside > 1e-12:
        out["sortino_ratio"] = float(np.mean(r - target) / downside * math.sqrt(annual))
    growth = np.r_[1.0, np.cumprod(1 + r)]
    # Calmar uses daily-close percentage drawdown on the flow-adjusted growth curve.
    drawdown = float(np.max(1 - growth / np.maximum.accumulate(growth)))
    years = (times.iloc[-1] - times.iloc[0]).total_seconds() / (365.25 * 86400)
    try:
        cagr = math.expm1(float(np.log1p(r).sum()) / years)
    except OverflowError:
        return unavailable("Annualized growth overflow")
    out["annualized_return"] = cagr
    out["max_drawdown_pct"] = 100 * drawdown
    if drawdown > 1e-12:
        out["calmar_ratio"] = cagr / drawdown
    out["sharpe_interpretation"] = sharpe_interpretation(out["sharpe_ratio"])
    out["reason"] = ("Cash-flow-adjusted estimate (Modified Dietz)" if flows is not None
                     else "Daily net equity returns")
    return out


def performance_html(result: dict, warning: str = "") -> str:
    def display(value):
        return "N/A" if value is None else f"{value:.3f}"

    rows = "".join(f"<tr><td>{name}</td><td>{display(result[key])}</td></tr>"
                   for name, key in (("Sharpe Ratio", "sharpe_ratio"),
                                     ("Sortino Ratio", "sortino_ratio"),
                                     ("Calmar Ratio", "calmar_ratio")))
    bands = "".join(f"<tr><td>{escape(band)}</td><td>{escape(label)}</td></tr>"
                    for band, label in SHARPE_BANDS)
    settings = result["settings"]
    return ('<section id="performance-ratios"><h2>Net account performance</h2>'
            f'<table class="summary"><tr><th>Metric</th><th>Value</th></tr>{rows}</table>'
            f'<p>Sharpe interpretation: {escape(result["sharpe_interpretation"])}. '
            f'{result["observations"]} daily returns. {escape(result["reason"])}.</p>'
            f'<p>Period: {escape(result.get("start", "N/A"))} to '
            f'{escape(result.get("end", "N/A"))}. '
            f'Annual risk-free rate: {settings["risk_free_rate"]:.2%}; '
            f'Sortino target: {settings["minimum_return"]:.2%}; '
            f'{settings["periods_per_year"]:g} periods/year. UTC weekday closes. '
            'Calmar uses annualized growth and daily-close drawdown over this period. '
            'N/A also means zero volatility, no downside, or no drawdown. '
            'Short histories can be misleading.</p>'
            f'<p>{escape(warning)}</p><h3>Sharpe Ratio — general interpretation</h3>'
            f'<table class="summary">{bands}</table>'
            '<p>These bands do not apply to Sortino or Calmar.</p></section>')
