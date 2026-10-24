"""Backtest HTML upgrades use only controlled saved artifacts."""
import json

from quant.report import write_report
from tests.test_report import _run_dir
from tests.test_performance import curve


def test_report_has_three_fee_net_ratios_and_interpretations(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    (run / "params.json").write_text(json.dumps({"performance": {"minimum_observations": 2},
        "equity_cost_timing": "accrued", "performance_equity_complete": True}), encoding="utf-8")
    curve([.01, -.02, .03, -.01]).to_csv(run / "equity_curve.csv", index=False)
    assert write_report(run, data)
    html = (run / "report.html").read_text(encoding="utf-8")
    assert all(name in html for name in ("Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
                                         "Exceptional; worth investigating carefully"))
    saved = json.loads((run / "performance.json").read_text(encoding="utf-8"))
    assert saved["sharpe_ratio"] is not None
    assert "entry commission" in html and "do not apply to Sortino" in html


def test_legacy_or_partial_report_does_not_invent_net_equity(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    curve([.01, -.02, .03, -.01]).to_csv(run / "equity_curve.csv", index=False)
    assert write_report(run, data)
    saved = json.loads((run / "performance.json").read_text(encoding="utf-8"))
    assert saved["sharpe_ratio"] is None
    assert "legacy or incomplete" in saved["reason"]


def test_performance_section_can_be_disabled(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    (run / "params.json").write_text(json.dumps({"performance": {"enabled": False}}), encoding="utf-8")
    assert write_report(run, data)
    assert 'id="performance-ratios"' not in (run / "report.html").read_text(encoding="utf-8")
