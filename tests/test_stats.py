import numpy as np

from itb.stats import binom_two_sided_p, cluster_bootstrap_ci, holm, min_n_for_power, wilson_ci


def test_wilson_contains_truth_and_bounds():
    lo, hi = wilson_ci(80, 100)
    assert 0.70 < lo < 0.75 and 0.86 < hi < 0.88
    assert wilson_ci(0, 10)[0] == 0.0 and abs(wilson_ci(10, 10)[1] - 1.0) < 1e-9


def test_planted_rule_detected_and_null_not_detected():
    rng = np.random.default_rng(1)
    # planted rule: 90% concordance, 150 pairs
    k = int((rng.random(150) < 0.9).sum())
    assert binom_two_sided_p(k, 150) < 1e-6
    # null: randomized labels, false-positive rate close to alpha over many repetitions
    fp = sum(binom_two_sided_p(int((rng.random(150) < 0.5).sum()), 150) < 0.05 for _ in range(2000))
    assert fp / 2000 < 0.07


def test_cluster_bootstrap_wider_than_naive_when_clustered():
    rng = np.random.default_rng(2)
    clusters = np.repeat(np.arange(40), 5)
    cluster_effect = np.repeat(rng.random(40) < 0.5, 5).astype(float)
    lo, hi = cluster_bootstrap_ci(cluster_effect, clusters, seed=3)
    nlo, nhi = wilson_ci(int(cluster_effect.sum()), len(cluster_effect))
    assert (hi - lo) > (nhi - nlo)


def test_holm_monotone_and_bounded():
    adj = holm([0.01, 0.04, 0.03, 0.5])
    assert adj[0] == 0.04 and max(adj) <= 1.0
    assert adj[2] >= adj[0]


def test_power_reasonable():
    n = min_n_for_power(0.75)
    assert 25 <= n <= 45
