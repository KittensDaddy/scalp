from __future__ import annotations

import random

from scalping.edge.evidence_bar import EvidenceBarInputs, evaluate_evidence_bar


def _passing_inputs(n_trades: int = 320) -> EvidenceBarInputs:
    # deterministic alternating pattern (never more than one consecutive loss) so
    # drawdown stays bounded regardless of RNG — a fair proxy for "no long losing
    # streak" rather than a coin-flip sequence that could occasionally cluster losses
    block = [1.35, -1.0, 1.35, -1.0, 1.35]  # 60% win rate, PF = 2*1.35/2*1.0 = 1.35
    trades = (block * ((n_trades // len(block)) + 1))[:n_trades]
    return EvidenceBarInputs(
        trade_r_multiples=trades,
        entry_attempts=n_trades + 200,
        protection_gap_p99_ms=900.0,
        maker_taker_resolved=True,
        reconciliation_clean_restarts=3,
        reconciliation_clean_disconnects=3,
        kill_switch_verified_end_to_end=True,
    )


def test_all_criteria_pass_on_engineered_good_sample():
    report = evaluate_evidence_bar(_passing_inputs(), n_bootstrap=300, rng=random.Random(1))
    assert report.passed is True
    assert len(report.criteria) == 8


def test_fails_on_insufficient_sample_size():
    inputs = _passing_inputs(n_trades=100)
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    sample_criterion = next(c for c in report.criteria if c.name == "sample_size")
    assert sample_criterion.passed is False
    assert report.passed is False


def test_fails_on_negative_expectancy():
    inputs = _passing_inputs()
    losing_trades = [-1.0] * 200 + [0.5] * 120
    inputs = EvidenceBarInputs(**{**inputs.__dict__, "trade_r_multiples": losing_trades})
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    expectancy_criterion = next(c for c in report.criteria if c.name == "net_expectancy_positive")
    assert expectancy_criterion.passed is False


def test_fails_on_protection_gap_too_high():
    inputs = _passing_inputs()
    inputs = EvidenceBarInputs(**{**inputs.__dict__, "protection_gap_p99_ms": 2000.0})
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    gap_criterion = next(c for c in report.criteria if c.name == "protection_gap")
    assert gap_criterion.passed is False
    assert report.passed is False


def test_fails_on_unresolved_maker_taker_decision():
    inputs = _passing_inputs()
    inputs = EvidenceBarInputs(**{**inputs.__dict__, "maker_taker_resolved": False})
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    assert report.passed is False


def test_fails_on_insufficient_reconciliation_drills():
    inputs = _passing_inputs()
    inputs = EvidenceBarInputs(**{**inputs.__dict__, "reconciliation_clean_restarts": 1})
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    assert report.passed is False


def test_fails_on_kill_switch_not_verified():
    inputs = _passing_inputs()
    inputs = EvidenceBarInputs(**{**inputs.__dict__, "kill_switch_verified_end_to_end": False})
    report = evaluate_evidence_bar(inputs, n_bootstrap=300, rng=random.Random(1))
    assert report.passed is False


def test_summary_contains_pass_fail_lines():
    report = evaluate_evidence_bar(_passing_inputs(), n_bootstrap=300, rng=random.Random(1))
    text = report.summary()
    assert "OVERALL: PASS" in text
    assert text.count("PASS") == 9  # 8 criteria + overall, all passing
