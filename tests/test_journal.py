"""Journal tests. No terminal."""
import csv

from quant.journal import COLUMNS, COMMENT_MAX, append_row, build_comment, ensure_header


def test_comment_fits_mt5_limit():
    c = build_comment("LONG", "E1")
    assert c == "QT B1-L E1" and len(c) <= COMMENT_MAX
    assert len(build_comment("SHORT", "E2-channel-breakout-very-long-name-here")) <= COMMENT_MAX


def test_append_creates_header_once(tmp_path):
    p = tmp_path / "journal.csv"
    append_row(p, {"symbol": "EURUSD", "direction": "LONG", "comment": "QT B1-L E1"})
    append_row(p, {"symbol": "USDJPY", "direction": "SHORT", "comment": "QT B1-S E1"})
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2 and rows[0]["symbol"] == "EURUSD"
    assert set(rows[0].keys()) == set(COLUMNS)


def test_ensure_header_is_idempotent(tmp_path):
    p = ensure_header(tmp_path / "sub" / "journal.csv")
    assert p.exists()
    ensure_header(p)
    with open(p, encoding="utf-8") as fh:
        assert len(fh.readlines()) == 1


def test_ensure_header_upgrades_legacy_file(tmp_path):
    p = tmp_path / "journal.csv"
    legacy = ",".join(COLUMNS[:-2])  # old 19-col header (no position/risk_usd)
    p.write_text(legacy + "\n"
                 "2026-10-17 00:00:00Z,EURUSD,LONG,1.1,1.09,1.11,0.01,UP,,,,,,"
                 ",,100001,QT B1-L E1,55,False,entry,,\n", encoding="utf-8")
    ensure_header(p)
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1 and rows[0]["symbol"] == "EURUSD"
    assert set(rows[0].keys()) == set(COLUMNS)      # header widened in place
    assert rows[0].get("position") in (None, "",)    # old rows simply lack it
    append_row(p, {"symbol": "GBPUSD", "position": 7})  # new rows carry position
    assert rows[0].get("position") in (None, "",)
