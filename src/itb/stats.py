"""Statistics used by the analysis. Small, dependency-light, unit-tested on synthetic data."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import stats


def wilson_ci(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    z = stats.norm.ppf(1 - (1 - conf) / 2)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (float(max(0.0, centre - half)), float(min(1.0, centre + half)))


def binom_two_sided_p(k: int, n: int, p0: float = 0.5) -> float:
    if n == 0:
        return float("nan")
    return float(stats.binomtest(k, n, p0, alternative="two-sided").pvalue)


def cluster_bootstrap_ci(values: Sequence[float], clusters: Sequence, conf: float = 0.95,
                         n_boot: int = 4000, seed: int = 0) -> tuple[float, float]:
    """Percentile CI of the mean of `values`, resampling whole clusters (e.g. slots) with replacement,
    so that several pairs from the same block are not treated as independent."""
    v = np.asarray(values, float)
    cl = np.asarray(clusters)
    if len(v) == 0:
        return (float("nan"), float("nan"))
    uniq, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=v, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[idx].sum(1) / cnts[idx].sum(1)
    lo, hi = np.quantile(means, [(1 - conf) / 2, 1 - (1 - conf) / 2])
    return (float(lo), float(hi))


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as input)."""
    p = np.asarray(pvalues, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj.tolist()


def min_n_for_power(p1: float, alpha: float = 0.05, power: float = 0.8, p0: float = 0.5) -> int:
    """Smallest n such that an exact two-sided binomial test at level alpha rejects p0 with the
    given power when the true concordance is p1."""
    for n in range(5, 5000):
        # critical region: k with two-sided p <= alpha
        ks = np.arange(n + 1)
        pv = np.array([binom_two_sided_p(int(k), n, p0) for k in ks])
        rej = ks[pv <= alpha]
        if len(rej) and stats.binom.pmf(rej, n, p1).sum() >= power:
            return n
    return -1
