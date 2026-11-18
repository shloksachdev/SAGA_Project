"""
Purpose: Acceptance tests for statistical functions (§11.2, §11.6).
Phase: Phase 11
"""

import numpy as np
import pytest
from paper.stats import (
    bootstrap_ci_median,
    cliffs_delta,
    hodges_lehmann,
    holm_adjust,
    mann_whitney,
)


def test_bootstrap_ci_coverage():
    """
    Assert bootstrap CI covers the true population median in >= 93% of 200 synthetic datasets (§11.6).
    Distribution: Standard Normal N(0, 1) where true median = 0.0.
    """
    rng = np.random.default_rng(12345)
    true_median = 0.0
    num_datasets = 200
    n_samples = 40
    n_resamples = 1000

    covered_count = 0
    for i in range(num_datasets):
        sample = rng.normal(loc=true_median, scale=1.0, size=n_samples)
        _, lower, upper = bootstrap_ci_median(sample, confidence=0.95, n_resamples=n_resamples, seed=i)
        if lower <= true_median <= upper:
            covered_count += 1

    coverage_rate = covered_count / num_datasets
    assert coverage_rate >= 0.93, f"Bootstrap coverage rate {coverage_rate:.3f} was below 0.93 threshold ({covered_count}/{num_datasets})"


def test_cliffs_delta_hand_computed():
    """Assert Cliff's delta matches hand-computed exact values (§11.6)."""
    # Identical groups -> delta = 0.0
    assert cliffs_delta([1, 2, 3], [1, 2, 3]) == 0.0

    # Completely separated groups -> delta = 1.0 or -1.0
    assert cliffs_delta([5, 6, 7], [1, 2, 3]) == 1.0
    assert cliffs_delta([1, 2, 3], [5, 6, 7]) == -1.0

    # Hand-computed mixed case:
    # x = [1, 2, 3, 4], y = [2, 3, 4, 5]
    # Total pairs = 16. Pos = 3, Neg = 10 -> (3 - 10) / 16 = -7 / 16 = -0.4375
    val = cliffs_delta([1, 2, 3, 4], [2, 3, 4, 5])
    assert pytest.approx(val, rel=1e-6) == -0.4375


def test_holm_adjust_textbook_example():
    """Assert Holm-Bonferroni adjustment matches standard textbook calculation (§11.6)."""
    # Raw p-values: [0.01, 0.04, 0.03, 0.005] (m=4)
    # Sorted order:
    # rank 0: 0.005 * 4 = 0.02
    # rank 1: 0.010 * 3 = 0.03
    # rank 2: 0.030 * 2 = 0.06
    # rank 3: 0.040 * 1 = 0.04 -> monotonic cum_max = 0.06
    # In original order: [0.03, 0.06, 0.06, 0.02]
    raw_p = [0.01, 0.04, 0.03, 0.005]
    adj_p = holm_adjust(raw_p)

    expected = [0.03, 0.06, 0.06, 0.02]
    for actual, exp in zip(adj_p, expected):
        assert pytest.approx(actual, abs=1e-5) == exp


def test_hodges_lehmann_hand_computed():
    """Assert Hodges-Lehmann estimator matches hand-computed pairwise median (§11.6)."""
    # x = [10, 20], y = [2, 4]
    # Pairwise differences: 10-2=8, 10-4=6, 20-2=18, 20-4=16
    # Sorted differences: [6, 8, 16, 18] -> median = (8 + 16)/2 = 12.0
    hl_est, lower, upper = hodges_lehmann([10, 20], [2, 4], n_resamples=500, seed=42)
    assert pytest.approx(hl_est, rel=1e-6) == 12.0
    assert lower <= hl_est <= upper


def test_mann_whitney_basic():
    """Assert Mann-Whitney U test functions as expected."""
    x = [1, 2, 3, 4, 5]
    y = [10, 11, 12, 13, 14]
    stat, p_val = mann_whitney(x, y)
    assert p_val < 0.01
    assert stat >= 0.0
