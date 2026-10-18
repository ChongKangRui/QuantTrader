"""spreadcheck row formatting; MT5 module itself stays mocked away."""

from quant.spreadcheck import _row


class _Info:
    point = 0.00001
    spread = 25
    digits = 5
    swap_long = -8.16
    swap_short = -11.0
    volume_max = 100.0


class _InfoJPY:
    point = 0.001
    spread = 18
    digits = 3
    swap_long = -21.4
    swap_short = 12.2
    volume_max = 50.0


def test_row_reads_points_pips_and_swaps():
    line = _row("EURUSD", _Info())
    assert "spread 25 points = 2.5 pips" in line  # points -> pips via point/pip
    assert "swap L/S -0.0816 / -0.1100" in line   # server per-lot -> per 0.01 lot


def test_jpy_pip_and_none_info():
    line = _row("USDJPY", _InfoJPY())
    assert "spread 18 points = 1.8 pips" in line  # JPY pip = 0.01, point = 0.001
    assert "XXZUSD: no symbol info" in _row("XXZUSD", None)


def test_zero_spread_gets_closed_market_hint():
    class _InfoClosed(_Info):
        spread = 0

    assert "market closed or stale" in _row("EURUSD", _InfoClosed())