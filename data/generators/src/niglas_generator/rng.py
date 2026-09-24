"""Deterministic, stream-keyed randomness.

The generator must satisfy two properties at once:

1. **Reproducibility** - same seed + same generator version => byte-identical data.
2. **Counterfactual stability** - injecting a fault must change *only* the outcomes
   the fault touches. Everything else (how many sessions occurred, which platform
   each one used, which customer it belonged to) must be identical to the fault-free
   run, so that "true impact" can be measured by differencing the two runs rather
   than estimated.

A single shared ``random.Random`` cannot give property 2: the moment a fault causes
one extra draw, every later value shifts. Instead, each logical entity gets its own
stream, seeded by hashing ``(seed, generator_version, key...)``. Streams are
independent, so a fault that perturbs session 91 leaves session 92 untouched.
"""

import hashlib
import math
import random
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

_SEED_BITS = 128


class StreamRandom:
    """Factory for independent, reproducible random streams."""

    def __init__(self, seed: int, generator_version: str) -> None:
        self._seed = seed
        self._generator_version = generator_version

    def stream(self, *key: object) -> random.Random:
        """Return the stream for ``key``.

        The same key always yields the same sequence, and different keys yield
        statistically independent sequences (they are distinct BLAKE2b digests).
        """
        material = "|".join(
            [str(self._seed), self._generator_version, *(str(part) for part in key)]
        )
        digest = hashlib.blake2b(material.encode("utf-8"), digest_size=_SEED_BITS // 8).digest()
        return random.Random(int.from_bytes(digest, "big"))  # noqa: S311 - simulation, not crypto


def poisson(rng: random.Random, mean: float) -> int:
    """Draw from a Poisson distribution.

    Knuth's product method below ~30, normal approximation above it (where Knuth's
    loop gets slow and the approximation error is under a percent of the standard
    deviation). Event arrivals are Poisson in reality, and using it rather than a
    fixed count means detectors face genuine count noise.
    """
    if mean < 0:
        raise ValueError("Poisson mean must be non-negative")
    if mean == 0:
        return 0
    if mean < 30:
        limit = math.exp(-mean)
        count = 0
        product = rng.random()
        while product > limit:
            count += 1
            product *= rng.random()
        return count
    return max(0, round(rng.gauss(mean, math.sqrt(mean))))


def bernoulli(rng: random.Random, probability: float) -> bool:
    """Draw a single yes/no outcome."""
    return rng.random() < clamp_probability(probability)


def clamp_probability(value: float) -> float:
    """Clamp to ``[0, 1]``.

    Fault effects are applied as additive deltas to probabilities; clamping keeps a
    large delta from producing a nonsensical probability instead of raising deep
    inside a simulation loop.
    """
    return min(1.0, max(0.0, value))


def weighted_choice(rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    """Pick one option, with probability proportional to its weight."""
    if not options:
        raise ValueError("weighted_choice requires at least one option")
    total = sum(weight for _, weight in options)
    if total <= 0:
        raise ValueError("weighted_choice requires positive total weight")
    threshold = rng.random() * total
    cumulative = 0.0
    for value, weight in options:
        cumulative += weight
        if threshold < cumulative:
            return value
    return options[-1][0]


def lognormal_amount(rng: random.Random, median: float, sigma: float) -> float:
    """Draw a positive amount whose median is ``median``.

    Order values are right-skewed - a few large baskets, many small ones - which a
    normal draw would not reproduce and which matters because average order value
    feeds the revenue-impact formula.
    """
    if median <= 0:
        raise ValueError("lognormal median must be positive")
    return median * math.exp(rng.gauss(0.0, sigma))
