"""Statistics for small samples of dependent binary outcomes (standard library only).

* Wilson score interval: trial-level, assumes independent trials (reference interval).
* Cluster bootstrap: resamples whole templates (clusters) with replacement; percentile
  interval. Honest about dependence within a template, but with few clusters (8 in the
  pilot) it is itself imprecise and tends to be too narrow: read it as indicative.
* Paired differences between conditions on the same items: mean difference, cluster
  bootstrap interval, discordant counts and McNemar's exact test.
* Power: half-width of a proportion's interval and the minimum detectable paired
  difference (Connor 1987), both inflated by a design effect 1 + (m - 1) * ICC.
"""

from __future__ import annotations

import math
import random
from collections.abc import Hashable, Iterable
from statistics import NormalDist

Z95 = NormalDist().inv_cdf(0.975)


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty sample")
    pos = (len(sorted_values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def cluster_bootstrap_ratio(
    by_cluster: dict[Hashable, tuple[float, int]], *, draws: int = 2000, seed: int = 0
) -> tuple[float, float] | None:
    """Percentile interval for sum(numerators) / sum(denominators), resampling clusters."""
    clusters = [c for c, (_, n) in by_cluster.items() if n > 0]
    if len(clusters) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        num = den = 0.0
        for _ in clusters:
            k, n = by_cluster[clusters[rng.randrange(len(clusters))]]
            num += k
            den += n
        if den:
            stats.append(num / den)
    stats.sort()
    return quantile(stats, 0.025), quantile(stats, 0.975)


def mcnemar_exact(n10: int, n01: int) -> float:
    """Two-sided exact McNemar test (binomial on the discordant pairs)."""
    n = n10 + n01
    if n == 0:
        return 1.0
    k = min(n10, n01)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_difference(
    units: Iterable[tuple[Hashable, int, int]], *, draws: int = 2000, seed: int = 0
) -> dict[str, float | int | tuple[float, float] | None]:
    """units: (cluster, outcome in A, outcome in B). Difference is A - B."""
    units = list(units)
    n = len(units)
    if n == 0:
        return {
            "n_pairs": 0,
            "rate_a": None,
            "rate_b": None,
            "diff": None,
            "cluster_ci": None,
            "n10": 0,
            "n01": 0,
            "mcnemar_p": None,
        }
    n10 = sum(1 for _, a, b in units if a and not b)
    n01 = sum(1 for _, a, b in units if b and not a)
    by_cluster: dict[Hashable, tuple[float, int]] = {}
    for cluster, a, b in units:
        s, c = by_cluster.get(cluster, (0.0, 0))
        by_cluster[cluster] = (s + (a - b), c + 1)
    return {
        "n_pairs": n,
        "rate_a": sum(a for _, a, _ in units) / n,
        "rate_b": sum(b for _, _, b in units) / n,
        "diff": (n10 - n01) / n,
        "cluster_ci": cluster_bootstrap_ratio(by_cluster, draws=draws, seed=seed),
        "n10": n10,
        "n01": n01,
        "mcnemar_p": mcnemar_exact(n10, n01),
    }


def holm(pvalues: list[float | None]) -> list[float | None]:
    """Holm-Bonferroni step-down adjusted p-values (None entries are left out of the family)."""
    indexed = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    m = len(indexed)
    adjusted: list[float | None] = [None] * len(pvalues)
    running = 0.0
    for rank, (p, i) in enumerate(indexed):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[i] = running
    return adjusted


def design_effect(cluster_size: float, icc: float) -> float:
    return 1.0 + max(0.0, cluster_size - 1.0) * icc


def proportion_halfwidth(n: float, p: float = 0.5, deff: float = 1.0, z: float = Z95) -> float | None:
    if n <= 0:
        return None
    return z * math.sqrt(p * (1 - p) * deff / n)


def paired_mde(
    n_pairs: float, p_discordant: float, *, alpha: float = 0.05, power: float = 0.8, deff: float = 1.0
) -> float | None:
    """Smallest |p10 - p01| detectable by McNemar's test (Connor 1987 approximation)."""
    n_eff = n_pairs / deff
    if n_eff <= 0 or not 0 < p_discordant <= 1:
        return None
    za = NormalDist().inv_cdf(1 - alpha / 2)
    zb = NormalDist().inv_cdf(power)

    def needed(delta: float) -> float:
        return (za * math.sqrt(p_discordant) + zb * math.sqrt(max(p_discordant - delta**2, 0.0))) ** 2 / delta**2

    lo, hi = 1e-6, p_discordant
    if needed(hi) > n_eff:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if needed(mid) > n_eff:
            lo = mid
        else:
            hi = mid
    return hi
