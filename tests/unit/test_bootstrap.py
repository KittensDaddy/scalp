from __future__ import annotations

import random

from scalping.edge.bootstrap import bootstrap_mean_ci


def test_ci_brackets_true_mean_for_clearly_positive_sample():
    values = [1.0] * 50 + [-0.5] * 10  # clearly positive mean
    lo, hi = bootstrap_mean_ci(values, n_resamples=500, rng=random.Random(1))
    assert lo > 0
    assert lo < hi


def test_ci_excludes_positive_for_clearly_negative_sample():
    values = [-1.0] * 50 + [0.5] * 10
    _lo, hi = bootstrap_mean_ci(values, n_resamples=500, rng=random.Random(1))
    assert hi < 0


def test_empty_values_returns_zero_zero():
    assert bootstrap_mean_ci([]) == (0.0, 0.0)


def test_deterministic_with_seeded_rng():
    values = [0.5, -0.3, 1.2, -0.8, 0.9]
    a = bootstrap_mean_ci(values, n_resamples=300, rng=random.Random(42))
    b = bootstrap_mean_ci(values, n_resamples=300, rng=random.Random(42))
    assert a == b
