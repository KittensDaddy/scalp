"""S10 calibration — Wilson CI + min-sample gating."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.edge.calibration import (
    CalibrationKey,
    CalibrationStats,
    accumulate_calibration,
    gate_probability,
    score_bucket,
    wilson_ci,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def test_wilson_ci_bounds_and_empty():
    assert wilson_ci(0, 0) is None
    lo, hi = wilson_ci(50, 100)
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    lo2, hi2 = wilson_ci(100, 100)
    assert lo2 > 0.9
    assert hi2 == pytest.approx(1.0)


def test_wilson_ci_rejects_invalid_wins():
    with pytest.raises(ValueError):
        wilson_ci(11, 10)


def test_gate_probability_insufficient_sample():
    stats = CalibrationStats(
        key=CalibrationKey("caems_v2", "LONG", "trend_up", "70-80"),
        n=10, wins=7, sum_r=5.0, updated_at=NOW,
    )
    est = gate_probability(stats, min_samples=30)
    assert est.available is False
    assert est.win_probability is None
    assert est.reason == "insufficient_sample"


def test_gate_probability_available_when_n_met():
    stats = CalibrationStats(
        key=CalibrationKey("caems_v2", "LONG", "trend_up", "70-80"),
        n=40, wins=24, sum_r=8.0, updated_at=NOW,
    )
    est = gate_probability(stats, min_samples=30)
    assert est.available is True
    assert est.win_probability == pytest.approx(0.6)
    assert est.ci_low is not None and est.ci_high is not None
    assert est.expectancy_r == pytest.approx(0.2)


def test_score_bucket_and_accumulate():
    assert score_bucket(74.0) == "70-80"
    key = CalibrationKey("caems_v2", "LONG", "chop", "70-80")
    s1 = accumulate_calibration(None, key=key, r_multiple=1.0, won=True, updated_at=NOW)
    s2 = accumulate_calibration(s1, key=key, r_multiple=-1.0, won=False, updated_at=NOW)
    assert s2.n == 2 and s2.wins == 1 and s2.sum_r == 0.0
