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

import bisect
import math
import random
from collections.abc import Hashable, Iterable
from statistics import NormalDist
from typing import Any

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


# ----------------------------------------------------------------------------- pair-level contrasts
# The act design (ADR-0009): the unit of analysis is the pair, the observation is the (pair, world,
# pressure) unit, and the cluster is the template. A contrast is summarized by the mean, over pairs,
# of each pair's mean unit difference.


def pair_means(units: Iterable[tuple[Hashable, Hashable, float]]) -> dict[Hashable, tuple[Hashable, float]]:
    """units: (pair, template, unit value). Returns pair -> (template, mean of its units)."""
    sums: dict[Hashable, list[Any]] = {}
    for pair, template, value in units:
        cell = sums.setdefault(pair, [template, 0.0, 0])
        cell[1] += value
        cell[2] += 1
    return {pair: (template, total / n) for pair, (template, total, n) in sums.items()}


def _signed_sums(values: list[float]) -> list[float]:
    sums = [0.0]
    for v in values:
        sums = [s + v for s in sums] + [s - v for s in sums]
    return sums


def sign_flip_p(values: list[float], *, exact_limit: int = 20, draws: int = 200_000, seed: int = 0) -> float | None:
    """Two-sided sign-flip test of a zero mean, over pair means.

    Under the null each value is symmetric about zero, so its sign is flipped at random. Exact by
    enumeration when at most ``exact_limit`` values are non-zero, else ``draws`` seeded random flips.
    The p-value counts flips whose |sum| is at least the observed |sum|."""
    if not values:
        return None
    nonzero = [v for v in values if abs(v) > 1e-12]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero)) - 1e-9
    n = len(nonzero)
    if n <= exact_limit:  # meet in the middle: every signed sum of each half, then count the pairs
        half = n // 2
        left, right = _signed_sums(nonzero[:half]), sorted(_signed_sums(nonzero[half:]))
        hits = 0
        for a in left:
            hits += len(right) - bisect.bisect_left(right, observed - a)  # a + b >= observed
            hits += bisect.bisect_right(right, -observed - a)  # a + b <= -observed
        return min(1.0, hits / 2**n)
    rng = random.Random(seed)
    hits = sum(abs(sum(v if rng.random() < 0.5 else -v for v in nonzero)) >= observed for _ in range(draws))
    return (hits + 1) / (draws + 1)


def cluster_bootstrap_mean(
    by_cluster: dict[Hashable, list[float]], *, draws: int = 2000, seed: int = 0
) -> tuple[float, float] | None:
    """Percentile interval of the mean of pair means, resampling clusters (templates) with replacement."""
    clusters = [c for c, values in by_cluster.items() if values]
    if len(clusters) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        picked: list[float] = []
        for _ in clusters:
            picked += by_cluster[clusters[rng.randrange(len(clusters))]]
        stats.append(sum(picked) / len(picked))
    stats.sort()
    return quantile(stats, 0.025), quantile(stats, 0.975)


def leave_one_out_range(by_cluster: dict[Hashable, list[float]]) -> tuple[float, float] | None:
    """Lowest and highest mean of pair means when one cluster (template) is left out."""
    clusters = [c for c, values in by_cluster.items() if values]
    if len(clusters) < 2:
        return None
    means = []
    for out in clusters:
        rest = [v for c in clusters if c != out for v in by_cluster[c]]
        means.append(sum(rest) / len(rest))
    return min(means), max(means)


def pair_contrast(
    units: Iterable[tuple[Hashable, Hashable, float]], *, draws: int = 2000, seed: int = 0
) -> dict[str, Any]:
    """A unit-matched contrast summarized over pairs: estimate, sign-flip p, cluster interval and the
    leave-one-template-out range (design §6.1)."""
    means = pair_means(units)
    values = [m for _, m in means.values()]
    by_cluster: dict[Hashable, list[float]] = {}
    for template, m in means.values():
        by_cluster.setdefault(template, []).append(m)
    return {
        "n_pairs": len(values),
        "n_templates": len(by_cluster),
        "n_nonzero_pairs": sum(1 for v in values if abs(v) > 1e-12),
        "estimate": sum(values) / len(values) if values else None,
        "sign_flip_p": sign_flip_p(values, seed=seed),
        "cluster_ci": cluster_bootstrap_mean(by_cluster, draws=draws, seed=seed),
        "leave_one_out": leave_one_out_range(by_cluster),
    }


def confirmed(p: float | None, threshold: float, ci: Any, loo: Any) -> bool:
    """The three-part rule: p below its Holm threshold, the cluster interval excludes 0, and the
    leave-one-template-out range keeps the sign."""
    if p is None or not ci or not loo or p >= threshold:
        return False
    excludes_zero = ci[0] > 0 or ci[1] < 0
    keeps_sign = (loo[0] > 0 and loo[1] > 0) or (loo[0] < 0 and loo[1] < 0)
    return excludes_zero and keeps_sign


def holm_thresholds(pvalues: list[float | None], alpha: float = 0.05) -> list[float | None]:
    """Holm's step-down thresholds: the smallest p-value is compared with alpha/m, the next with
    alpha/(m-1), and so on (with two contrasts: 0.025, then 0.05)."""
    order = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    m = len(order)
    out: list[float | None] = [None] * len(pvalues)
    for rank, (_, i) in enumerate(order):
        out[i] = alpha / (m - rank)
    return out


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
