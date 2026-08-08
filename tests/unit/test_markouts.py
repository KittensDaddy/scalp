from __future__ import annotations

import pytest

from scalping.accounting.markouts import decide_maker_vs_taker, markout_bps, markout_r
from scalping.domain.models import Side


def test_markout_bps_positive_for_favorable_long_move():
    bps = markout_bps(fill_price=100.0, mid_at_offset=100.5, side=Side.LONG)
    assert bps == pytest.approx(50.0, rel=1e-3)


def test_markout_bps_negative_for_adverse_long_move():
    bps = markout_bps(fill_price=100.0, mid_at_offset=99.5, side=Side.LONG)
    assert bps < 0


def test_markout_bps_sign_flipped_for_short():
    bps_long = markout_bps(fill_price=100.0, mid_at_offset=99.5, side=Side.LONG)
    bps_short = markout_bps(fill_price=100.0, mid_at_offset=99.5, side=Side.SHORT)
    assert bps_short == pytest.approx(-bps_long)


def test_markout_r_conversion():
    r = markout_r(markout_bps_value=50.0, fill_price=100.0, stop_distance=0.5)
    assert r == pytest.approx(1.0)


def test_decide_maker_vs_taker_unresolved_below_min_attempts():
    decision = decide_maker_vs_taker(
        maker_markouts_30s_bps=[1.0] * 50, taker_markouts_30s_bps=[2.0] * 50,
        fee_difference_bps=3.0, min_total_attempts=300,
    )
    assert decision.resolved is False


def test_decide_maker_vs_taker_switches_when_maker_much_worse():
    decision = decide_maker_vs_taker(
        maker_markouts_30s_bps=[-5.0] * 200, taker_markouts_30s_bps=[5.0] * 200,
        fee_difference_bps=3.0, min_total_attempts=300,
    )
    assert decision.resolved is True
    assert decision.switch_to_taker is True


def test_decide_maker_vs_taker_keeps_maker_when_within_fee_difference():
    # maker worse by only 2bps, fee difference is 3bps -> not worse than the fee gap
    decision = decide_maker_vs_taker(
        maker_markouts_30s_bps=[3.0] * 200, taker_markouts_30s_bps=[5.0] * 200,
        fee_difference_bps=3.0, min_total_attempts=300,
    )
    assert decision.resolved is True
    assert decision.switch_to_taker is False
