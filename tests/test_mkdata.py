"""mkdata tests. Synthetic M1 only, never data/."""
import pandas as pd

from quant.mkdata import coverage, load_m1, to_h1


def _m1_rows():
    rows = []
    for h in (10, 11):
        for m in range(60):
            c = 1.1000 + h * 0.0010 + m * 0.00001
            rows.append(f"2020.01.06,{h:02d}:{m:02d},{c - 0.0001:.5f},{c + 0.0001:.5f},"
                        f"{c - 0.0002:.5f},{c:.5f},7")
    return rows


def test_h1_aggregation(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "DAT_MT_TST_M1_2020.csv").write_text("\n".join(_m1_rows()) + "\n", encoding="utf-8")
    m1 = load_m1(d, "TST")
    assert len(m1) == 120
    h1 = to_h1(m1)
    assert len(h1) == 2
    assert list(h1["time"].dt.strftime("%H:%M")) == ["10:00", "11:00"]
    assert h1["open"].iloc[0] == m1["open"].iloc[0]
    assert h1["close"].iloc[0] == m1["close"].iloc[59]
    assert h1["high"].iloc[0] == m1["high"].iloc[:60].max()
    assert h1["tick_volume"].iloc[0] == 7 * 60
    assert list(h1["n_minutes"]) == [60, 60]


def test_coverage_and_missing_symbol(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "DAT_MT_TST_M1_2020.csv").write_text("\n".join(_m1_rows()) + "\n", encoding="utf-8")
    cov = coverage(load_m1(d, "TST"), to_h1(load_m1(d, "TST")))
    assert cov["year"].iloc[0] == 2020 and cov["short_hours"].iloc[0] == 0
    try:
        load_m1(d, "NOPE")
        raise SystemExit("should have raised")
    except FileNotFoundError:
        pass
