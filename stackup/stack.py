"""1-D tolerance stack-up: worst case, RSS (statistical) and Monte Carlo.

A stack is a closed loop of dimensions that adds up to one result, usually a
gap.  Each dimension enters the loop with a direction of +1 or -1:

    gap = sum(direction_i * x_i)

Tolerances may be unequal (e.g. a bearing width of 14.00 +0/-0.12).  Every
dimension is first converted to an equal-bilateral form (mean +/- t):

    mean_i = nominal_i + (upper_i + lower_i) / 2
    t_i    = (upper_i - lower_i) / 2

Methods (Fischer, *Mechanical Tolerance Stackup and Analysis*, 2nd ed., ch. 9-10;
ASME Y14.5 is used for the drawing callouts, not the arithmetic):

    Worst case   gap = mean_gap +/- sum(t_i)
    RSS          gap = mean_gap +/- sqrt(sum(t_i^2))
    Statistical  sigma_i = t_i / (3 Cp_i),  sigma_gap = sqrt(sum(sigma_i^2))

RSS is the statistical method with Cp = 1 for every dimension (each tolerance
is +/-3 sigma).  A Cp above 1 claims the process is better than the drawing
requires, which shrinks sigma_i.  That claim then has to be enforced in the
control plan; see ``stackup.controlplan.check_stack_assumptions``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

DISTRIBUTIONS = ("normal", "uniform")


@dataclass(frozen=True)
class Dimension:
    name: str
    nominal: float
    upper: float              # upper deviation, e.g. +0.08
    lower: float              # lower deviation, e.g. -0.12 (signed)
    direction: int = 1        # +1 opens the gap, -1 closes it
    cp: float = 1.0           # assumed process capability for statistical methods
    distribution: str = "normal"
    source: str = ""          # drawing / feature reference

    def __post_init__(self):
        if self.direction not in (1, -1):
            raise ValueError(f"{self.name}: direction must be +1 or -1, got {self.direction}")
        if self.upper < self.lower:
            raise ValueError(f"{self.name}: upper deviation {self.upper} is below lower {self.lower}")
        if self.cp <= 0:
            raise ValueError(f"{self.name}: Cp must be positive")
        if self.distribution not in DISTRIBUTIONS:
            raise ValueError(f"{self.name}: distribution must be one of {DISTRIBUTIONS}")

    @property
    def mean(self) -> float:
        return self.nominal + (self.upper + self.lower) / 2

    @property
    def half_tol(self) -> float:
        return (self.upper - self.lower) / 2

    @property
    def sigma(self) -> float:
        """Standard deviation implied by the tolerance and the assumed Cp."""
        if self.distribution == "uniform":
            return self.half_tol / math.sqrt(3)
        return self.half_tol / (3 * self.cp)


def position_as_bilateral(position_dia: float) -> tuple[float, float]:
    """A diametral position tolerance contributes +/- half its value to a 1-D stack.

    This is the RFS (regardless of feature size) case.  At MMC the bonus
    tolerance depends on the produced hole size and must be added separately.
    """
    return position_dia / 2, -position_dia / 2


@dataclass
class StackResult:
    nominal_gap: float
    mean_gap: float
    wc_half: float
    rss_half: float
    sigma_gap: float
    lsl: float | None
    usl: float | None
    contributions: pd.DataFrame = field(repr=False)

    @property
    def wc_limits(self) -> tuple[float, float]:
        return self.mean_gap - self.wc_half, self.mean_gap + self.wc_half

    @property
    def rss_limits(self) -> tuple[float, float]:
        return self.mean_gap - self.rss_half, self.mean_gap + self.rss_half

    @property
    def stat_limits(self) -> tuple[float, float]:
        return self.mean_gap - 3 * self.sigma_gap, self.mean_gap + 3 * self.sigma_gap

    def passes(self, limits: tuple[float, float]) -> bool:
        lo, hi = limits
        return (self.lsl is None or lo >= self.lsl - 1e-12) and (self.usl is None or hi <= self.usl + 1e-12)

    @property
    def cpk(self) -> float:
        """Predicted Cpk of the gap from the statistical model."""
        sides = []
        if self.usl is not None:
            sides.append((self.usl - self.mean_gap) / (3 * self.sigma_gap))
        if self.lsl is not None:
            sides.append((self.mean_gap - self.lsl) / (3 * self.sigma_gap))
        return min(sides) if sides else math.nan

    @property
    def ppm(self) -> float:
        """Predicted out-of-spec parts per million, assuming a normal gap."""
        p = 0.0
        if self.lsl is not None:
            p += stats.norm.cdf(self.lsl, self.mean_gap, self.sigma_gap)
        if self.usl is not None:
            p += stats.norm.sf(self.usl, self.mean_gap, self.sigma_gap)
        return p * 1e6


def analyze(dims: list[Dimension], lsl: float | None = None, usl: float | None = None) -> StackResult:
    if not dims:
        raise ValueError("stack has no dimensions")
    t = np.array([d.half_tol for d in dims])
    s = np.array([d.sigma for d in dims])
    wc_half = t.sum()
    contrib = pd.DataFrame({
        "dimension": [d.name for d in dims],
        "direction": [d.direction for d in dims],
        "mean": [d.mean for d in dims],
        "half_tol": t,
        "sigma": s,
        "wc_pct": 100 * t / wc_half if wc_half else 0.0,
        "stat_pct": 100 * s**2 / (s**2).sum() if s.any() else 0.0,
    })
    return StackResult(
        nominal_gap=sum(d.direction * d.nominal for d in dims),
        mean_gap=sum(d.direction * d.mean for d in dims),
        wc_half=float(wc_half),
        rss_half=float(math.sqrt((t**2).sum())),
        sigma_gap=float(math.sqrt((s**2).sum())),
        lsl=lsl, usl=usl, contributions=contrib,
    )


@dataclass
class MonteCarloResult:
    samples: np.ndarray = field(repr=False)
    mean: float
    std: float
    p_low: float               # 0.135th percentile (-3 sigma equivalent)
    p_high: float              # 99.865th percentile (+3 sigma equivalent)
    ppm_below: float
    ppm_above: float

    @property
    def ppm(self) -> float:
        return self.ppm_below + self.ppm_above


def monte_carlo(dims: list[Dimension], lsl: float | None = None, usl: float | None = None,
                n: int = 200_000, seed: int | None = 0) -> MonteCarloResult:
    """Sample every dimension from its distribution and build the gap directly."""
    rng = np.random.default_rng(seed)
    gap = np.zeros(n)
    for d in dims:
        if d.distribution == "uniform":
            x = rng.uniform(d.mean - d.half_tol, d.mean + d.half_tol, n)
        else:
            x = rng.normal(d.mean, d.sigma, n)
        gap += d.direction * x
    below = float((gap < lsl).mean() * 1e6) if lsl is not None else 0.0
    above = float((gap > usl).mean() * 1e6) if usl is not None else 0.0
    lo, hi = np.percentile(gap, [0.135, 99.865])
    return MonteCarloResult(gap, float(gap.mean()), float(gap.std(ddof=1)), float(lo), float(hi), below, above)


# ------------------------------------------------------------------ CSV I/O
COLUMNS = ["name", "nominal", "upper", "lower", "direction", "cp", "distribution", "source"]


def from_frame(df: pd.DataFrame) -> list[Dimension]:
    missing = {"name", "nominal", "upper", "lower", "direction"} - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    def opt(row, key, default):
        value = row.get(key)
        return default if value is None or (isinstance(value, float) and math.isnan(value)) or value == "" else value

    return [Dimension(
        name=str(row["name"]), nominal=float(row["nominal"]),
        upper=float(row["upper"]), lower=float(row["lower"]), direction=int(row["direction"]),
        cp=float(opt(row, "cp", 1.0)), distribution=str(opt(row, "distribution", "normal")),
        source=str(opt(row, "source", "")),
    ) for row in df.to_dict("records")]


def to_frame(dims: list[Dimension]) -> pd.DataFrame:
    return pd.DataFrame([{c: getattr(d, c) for c in COLUMNS} for d in dims])
