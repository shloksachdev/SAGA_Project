"""
Purpose: Pure statistical analysis functions for saga evaluation (§11.2).
Phase: Phase 11
"""

from typing import List, Optional, Tuple, Union
import numpy as np
import scipy.stats as stats


def bootstrap_ci_median(
    data: Union[List[float], np.ndarray],
    confidence: float = 0.95,
    n_resamples: int = 10000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """
    Computes percentile bootstrap confidence interval on the median.
    Returns (median, lower_ci, upper_ci).
    """
    arr = np.asarray(data, dtype=float)
    if len(arr) == 0:
        return 0.0, 0.0, 0.0
    if len(arr) == 1:
        val = float(arr[0])
        return val, val, val

    point_est = float(np.median(arr))
    rng = np.random.default_rng(seed)

    # Vectorized bootstrap resampling
    indices = rng.integers(0, len(arr), size=(n_resamples, len(arr)))
    resampled_medians = np.median(arr[indices], axis=1)

    alpha = 1.0 - confidence
    lower_pct = 100.0 * (alpha / 2.0)
    upper_pct = 100.0 * (1.0 - alpha / 2.0)

    lower_ci = float(np.percentile(resampled_medians, lower_pct))
    upper_ci = float(np.percentile(resampled_medians, upper_pct))

    return point_est, lower_ci, upper_ci


def mann_whitney(
    x: Union[List[float], np.ndarray],
    y: Union[List[float], np.ndarray],
) -> Tuple[float, float]:
    """
    Computes two-sided Mann-Whitney U test between groups x and y.
    Returns (statistic, p_value).
    """
    arr_x = np.asarray(x, dtype=float)
    arr_y = np.asarray(y, dtype=float)
    if len(arr_x) == 0 or len(arr_y) == 0:
        return 0.0, 1.0
    res = stats.mannwhitneyu(arr_x, arr_y, alternative="two-sided")
    return float(res.statistic), float(res.pvalue)


def cliffs_delta(
    x: Union[List[float], np.ndarray],
    y: Union[List[float], np.ndarray],
) -> float:
    """
    Computes Cliff's delta non-parametric effect size between groups x and y:
    delta = (sum_{i,j} sign(x_i - y_j)) / (|x| * |y|).
    Returns float in [-1.0, 1.0].
    """
    arr_x = np.asarray(x, dtype=float)
    arr_y = np.asarray(y, dtype=float)
    n_x = len(arr_x)
    n_y = len(arr_y)
    if n_x == 0 or n_y == 0:
        return 0.0

    diffs = np.subtract.outer(arr_x, arr_y)
    delta = np.sum(np.sign(diffs)) / (n_x * n_y)
    return float(delta)


def hodges_lehmann(
    x: Union[List[float], np.ndarray],
    y: Union[List[float], np.ndarray],
    confidence: float = 0.95,
    n_resamples: int = 10000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """
    Computes Hodges-Lehmann median difference estimator between x and y
    along with a 95% bootstrap confidence interval.
    Returns (hl_median_difference, lower_ci, upper_ci).
    """
    arr_x = np.asarray(x, dtype=float)
    arr_y = np.asarray(y, dtype=float)
    if len(arr_x) == 0 or len(arr_y) == 0:
        return 0.0, 0.0, 0.0

    diffs = np.subtract.outer(arr_x, arr_y).flatten()
    hl_est = float(np.median(diffs))

    rng = np.random.default_rng(seed)
    idx_x = rng.integers(0, len(arr_x), size=(n_resamples, len(arr_x)))
    idx_y = rng.integers(0, len(arr_y), size=(n_resamples, len(arr_y)))

    # Compute bootstrap pairwise median differences
    bs_medians = np.empty(n_resamples, dtype=float)
    for b in range(n_resamples):
        sample_diffs = np.subtract.outer(arr_x[idx_x[b]], arr_y[idx_y[b]]).flatten()
        bs_medians[b] = np.median(sample_diffs)

    alpha = 1.0 - confidence
    lower_pct = 100.0 * (alpha / 2.0)
    upper_pct = 100.0 * (1.0 - alpha / 2.0)

    lower_ci = float(np.percentile(bs_medians, lower_pct))
    upper_ci = float(np.percentile(bs_medians, upper_pct))

    return hl_est, lower_ci, upper_ci


def holm_adjust(p_values: List[float]) -> List[float]:
    """
    Adjusts a list of p-values using the step-down Holm-Bonferroni method.
    Preserves input order.
    """
    m = len(p_values)
    if m == 0:
        return []

    # Sort p-values while tracking original indices
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * m

    cum_max = 0.0
    for rank, (orig_idx, p_val) in enumerate(indexed):
        mult = m - rank
        raw_adj = mult * p_val
        cum_max = max(cum_max, raw_adj)
        p_adj = min(1.0, cum_max)
        adjusted[orig_idx] = float(p_adj)

    return adjusted
