"""spreadcheck rows: swap_mode-aware conversion; MT5 itself stays mocked away."""

from types import SimpleNamespace

from quant.spreadcheck import _per_001_swap, _profit_ccy_fx, _row


class _Info:
    # Pepperstone-Demo reality: swap_mode = POINTS (points per 1.0 lot)
    point = 0.00001
    spread = 25
    digits = 5
    swap_long = -8.16
    swap_short = -11.0
    swap_mode = 1
    trade_contract_size = 100000.0
    currency_profit = "USD"
    volume_max = 100.0


class _InfoJPY(_Info):
    point = 0.001
    spread = 18
    digits = 3
    swap_long = -21.4
    swap_short = 12.2
    currency_profit = "JPY"
    volume_max = 50.0


class _FakeMT5:
    def __init__(self, quotes):
        self._q = quotes

    def symbol_info(self, name):
        return self._q.get(name)


def test_points_mode_converts_via_point_value():
    # 1 point on 0.01 lot = point x contract x 0.01 = 0.01 USD -> swap / 100
    s_l, s_s, mode = _per_001_swap(_Info())
    assert (round(s_l, 4), round(s_s, 4), mode) == (-0.0816, -0.11, "points")


def test_jpy_points_mode_needs_fx_not_plain_division():
    # JPY point value on 0.01 lot = 1.0 JPY -> per-0.01 swap is JPY, not USD
    s_l, s_s, mode = _per_001_swap(_InfoJPY())
    assert (round(s_l, 4), round(s_s, 4)) == (-21.4, 12.2)
    mt5 = _FakeMT5({"USDJPY": SimpleNamespace(bid=150.0)})
    rate, note = _profit_ccy_fx(mt5, _InfoJPY())
    assert abs(rate - 1 / 150.0) < 1e-12 and note == "via 1/USDJPY bid"
    assert -0.1427 == round(s_l * rate, 4)   # the OLD /100 code printed -0.214 here
    assert "+0.0813" in _row("USDJPY", _InfoJPY(), mt5)


def test_money_mode_divides_by_100():
    info = SimpleNamespace(point=0.00001, trade_contract_size=100000.0,
                           currency_profit="USD", swap_mode=2, swap_long=-0.8,
                           swap_short=-1.1)
    s_l, s_s = _per_001_swap(info)[:2]
    assert (round(s_l, 6), round(s_s, 6)) == (-0.008, -0.011)


def test_disabled_mode_is_zero():
    info = SimpleNamespace(point=0.00001, trade_contract_size=100000.0,
                           currency_profit="USD", swap_mode=0)
    assert _per_001_swap(info) == (0.0, 0.0, "disabled")


def test_missing_swap_mode_flags_manual_recalibration():
    class _Legacy:
        point = 0.00001
        spread = 25
        swap_long = -8.16
        swap_short = -11.0
        volume_max = 100.0

    assert "recalibrate by hand" in _row("EURUSD", _Legacy())


def test_row_reads_points_pips_and_swaps():
    line = _row("EURUSD", _Info())
    assert "spread 25 points = 2.5 pips" in line  # points -> pips via point/pip
    assert "swap L/S -0.0816 / -0.1100 USD per 0.01 lot (points; USD direct)" in line


def test_jpy_pip_and_none_info():
    line = _row("USDJPY", _InfoJPY())
    assert "spread 18 points = 1.8 pips" in line  # JPY pip = 0.01, point = 0.001
    assert "XXZUSD: no symbol info" in _row("XXZUSD", None)


def test_zero_spread_gets_closed_market_hint():
    class _InfoClosed(_Info):
        spread = 0

    assert "market closed or stale" in _row("EURUSD", _InfoClosed())
