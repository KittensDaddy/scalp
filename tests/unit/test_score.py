from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scalping.scoring.score import ScoreInputs, ScoreWeights, score

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _inputs(**overrides) -> ScoreInputs:
    defaults = dict(
        trend_alignment_frac=1.0, momentum_frac=1.0, relative_volume_frac=1.0,
        entry_quality_frac=1.0, historical_edge_frac=1.0, liquidity_frac=1.0,
        volatility_regime_frac=1.0, confirmations_frac=1.0,
        spread_penalty_frac=0.0, slippage_penalty_frac=0.0, stale=False, evaluated_at=NOW,
    )
    defaults.update(overrides)
    return ScoreInputs(**defaults)


def test_golden_all_full_credit_no_penalty():
    """Every positive component maxed, no penalties -> exact breakdown, total 100."""
    breakdown = score(_inputs())
    assert breakdown.components == {
        "trend_alignment": 18.0, "momentum": 16.0, "relative_volume": 14.0,
        "entry_quality": 13.0, "historical_edge": 12.0, "liquidity": 10.0,
        "volatility_regime": 8.0, "confirmations": 4.0,
        "spread_penalty": 0.0, "slippage_penalty": 0.0,
    }
    # SCANNER_DASHBOARD_PLAN.md §E's own component weights sum to 95 (18+16+14+13+
    # 12+10+8+4), not 100 -- clamp(..., 0, 100) is a safety ceiling, not a claim
    # that every component maxed reaches exactly 100.
    assert breakdown.total == pytest.approx(95.0)
    assert breakdown.stale is False


def test_golden_zero_everything():
    breakdown = score(_inputs(
        trend_alignment_frac=0, momentum_frac=0, relative_volume_frac=0,
        entry_quality_frac=0, historical_edge_frac=0, liquidity_frac=0,
        volatility_regime_frac=0, confirmations_frac=0,
    ))
    assert all(v == 0.0 for k, v in breakdown.components.items())
    assert breakdown.total == pytest.approx(0.0)


def test_golden_mixed_values_exact_breakdown():
    breakdown = score(_inputs(
        trend_alignment_frac=0.5, momentum_frac=0.25, relative_volume_frac=0.75,
        entry_quality_frac=1.0, historical_edge_frac=0.0, liquidity_frac=0.5,
        volatility_regime_frac=0.5, confirmations_frac=0.0,
        spread_penalty_frac=0.5, slippage_penalty_frac=1.0,
    ))
    assert breakdown.components == {
        "trend_alignment": 9.0, "momentum": 4.0, "relative_volume": 10.5,
        "entry_quality": 13.0, "historical_edge": 0.0, "liquidity": 5.0,
        "volatility_regime": 4.0, "confirmations": 0.0,
        "spread_penalty": -4.0, "slippage_penalty": -5.0,
    }
    assert breakdown.total == pytest.approx(9 + 4 + 10.5 + 13 + 0 + 5 + 4 + 0 - 4 - 5)


def test_stale_nukes_score_regardless_of_other_components():
    breakdown = score(_inputs(stale=True))
    assert breakdown.total == 0.0
    assert breakdown.stale is True
    assert breakdown.components == {"staleness_penalty": -100.0}


def test_total_clamped_to_100_even_if_weights_overridden_high():
    weights = ScoreWeights(trend_alignment_max=200.0)
    breakdown = score(_inputs(), weights)
    assert breakdown.total == 100.0


def test_total_clamped_to_0_floor():
    breakdown = score(_inputs(
        trend_alignment_frac=0, momentum_frac=0, relative_volume_frac=0,
        entry_quality_frac=0, historical_edge_frac=0, liquidity_frac=0,
        volatility_regime_frac=0, confirmations_frac=0,
        spread_penalty_frac=1.0, slippage_penalty_frac=1.0,
    ))
    assert breakdown.total == 0.0


def test_out_of_range_fracs_are_clamped():
    breakdown = score(_inputs(trend_alignment_frac=1.5, momentum_frac=-0.5))
    assert breakdown.components["trend_alignment"] == 18.0
    assert breakdown.components["momentum"] == 0.0


def test_deterministic_same_inputs_same_output():
    inputs = _inputs(trend_alignment_frac=0.42)
    a = score(inputs)
    b = score(inputs)
    assert a == b


@pytest.mark.parametrize(
    "component_field,weight_name",
    [
        ("trend_alignment_frac", "trend_alignment"),
        ("momentum_frac", "momentum"),
        ("relative_volume_frac", "relative_volume"),
        ("entry_quality_frac", "entry_quality"),
        ("historical_edge_frac", "historical_edge"),
        ("liquidity_frac", "liquidity"),
        ("volatility_regime_frac", "volatility_regime"),
        ("confirmations_frac", "confirmations"),
    ],
)
def test_positive_component_monotonic_in_its_input(component_field, weight_name):
    low = score(_inputs(**{component_field: 0.2}))
    high = score(_inputs(**{component_field: 0.8}))
    assert high.components[weight_name] > low.components[weight_name]
    assert high.total >= low.total


@pytest.mark.parametrize("penalty_field,weight_name", [
    ("spread_penalty_frac", "spread_penalty"),
    ("slippage_penalty_frac", "slippage_penalty"),
])
def test_penalty_monotonic_decreasing_in_its_input(penalty_field, weight_name):
    low_penalty = score(_inputs(**{penalty_field: 0.1}))
    high_penalty = score(_inputs(**{penalty_field: 0.9}))
    assert high_penalty.components[weight_name] < low_penalty.components[weight_name]
    assert high_penalty.total <= low_penalty.total
