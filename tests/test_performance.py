"""Controlled net-equity fixtures, never local history or a terminal."""
import math

import numpy as np
import pandas as pd
import pytest

from quant.performance import (PerformanceSettings, account_performance,
                               performance_html, sharpe_interpretation)


def curve(returns):
    values = 100 * np.r_[1, np.cumprod(1 + np.asarray(returns))]
    return pd.DataFrame({"time": pd.date_range("2026-01-05 21:00", periods=len(values),
                                              freq="B", tz="UTC"), "usd": values})


SETTINGS = PerformanceSettings(minimum_observations=2)


def test_ratios_match_hand_calculation():
    r = np.array([0.01, -0.02, 0.03, -0.01])
    c = curve(r)
    result = account_performance(c, SETTINGS)
    assert result["sharpe_ratio"] == pytest.approx(r.mean() / r.std(ddof=1) * math.sqrt(252))
    assert result["sortino_ratio"] == pytest.approx(
        r.mean() / np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * math.sqrt(252))
    years = (c.time.iloc[-1] - c.time.iloc[0]).total_seconds() / (365.25 * 86400)
    cagr = np.prod(1 + r) ** (1 / years) - 1
    assert result["max_drawdown_pct"] == pytest.approx(2)
    assert result["calmar_ratio"] == pytest.approx(cagr / .02)


@pytest.mark.parametrize("value,word", [(-.01, "Underperforming"), (0, "Weak"),
    (.4999, "Weak"), (.5, "Moderate"), (1, "Good"), (1.5, "Very good"),
    (2, "Very good"), (2.0001, "Excellent"), (3, "Excellent"),
    (3.0001, "Exceptional"), (None, "N/A"), (float("nan"), "N/A")])
def test_sharpe_boundaries(value, word):
    assert word in sharpe_interpretation(value)


def test_fees_reduce_ratios_without_double_deduction():
    gross = curve([.02, -.01, .03, -.02])
    net = gross.copy()
    net["usd"] -= np.arange(len(net)) * .5
    assert account_performance(net, SETTINGS)["sharpe_ratio"] < account_performance(gross, SETTINGS)["sharpe_ratio"]


def test_deposit_is_not_profit():
    c = curve([0, 0, 0])
    when = c.time.iloc[1] - pd.Timedelta(hours=1)
    c.loc[1:, "usd"] += 100
    result = account_performance(c, SETTINGS, pd.DataFrame([{"time": when, "amount": 100}]))
    assert result["annualized_return"] == pytest.approx(0)
    assert result["sharpe_ratio"] is None
    assert "estimate" in result["reason"]


def test_weekend_return_is_not_lost_or_counted_as_extra_period():
    c = pd.DataFrame({"time": pd.to_datetime([
        "2026-01-09", "2026-01-11", "2026-01-12", "2026-01-13"], utc=True),
        "usd": [100, 90, 90, 100]})
    result = account_performance(c, SETTINGS)
    assert result["observations"] == 2
    assert result["max_drawdown_pct"] == pytest.approx(10)


def test_invalid_and_degenerate_histories():
    flat = account_performance(curve([0, 0, 0]), SETTINGS)
    assert all(flat[k] is None for k in ("sharpe_ratio", "sortino_ratio", "calmar_ratio"))
    up = account_performance(curve([.01, .02, .03]), SETTINGS)
    assert up["sortino_ratio"] is None and up["calmar_ratio"] is None
    assert "Insufficient" in account_performance(curve([.01]), SETTINGS)["reason"]
    broken = curve([.01, .02, .03]).drop(index=1)
    assert "Missing weekday" in account_performance(broken, SETTINGS)["reason"]
    c = curve([-.5, -.5])
    c.loc[1, "usd"] = 0
    assert "Non-positive" in account_performance(c, SETTINGS)["reason"]
    assert account_performance(c, PerformanceSettings(enabled=False))["reason"] == "Disabled"


def test_rates_and_options_are_configurable():
    c = curve([.001, -.001, .002])
    zero = account_performance(c, SETTINGS)
    higher = account_performance(c, PerformanceSettings(risk_free_rate=.1, minimum_return=.1,
                                                       minimum_observations=2))
    assert higher["sharpe_ratio"] < zero["sharpe_ratio"]
    assert higher["sortino_ratio"] < zero["sortino_ratio"]
    with pytest.raises(ValueError):
        PerformanceSettings(periods_per_year=0)
    with pytest.raises(ValueError):
        PerformanceSettings(risk_free_rate=-1)
    assert "Sortino Ratio" in performance_html(zero, "<unsafe>")
    assert "&lt;unsafe&gt;" in performance_html(zero, "<unsafe>")
