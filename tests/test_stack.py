"""Stack-up math: hand calculations on the sample assembly, closed-form statistics and Monte Carlo convergence."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from stackup import stack
from stackup.stack import Dimension, analyze, monte_carlo, position_as_bilateral

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def dims():
    return stack.from_frame(pd.read_csv(DATA / "end_play_stack.csv"))


# ------------------------------------------------- unequal-bilateral conversion
def test_unequal_tolerance_converted_to_mean_and_half_tolerance():
    d = Dimension("bearing", 14.00, 0.0, -0.12)
    assert d.mean == pytest.approx(13.94)
    assert d.half_tol == pytest.approx(0.06)


def test_sigma_from_cp_and_uniform():
    assert Dimension("a", 10, 0.06, -0.06, cp=1.0).sigma == pytest.approx(0.02)
    assert Dimension("a", 10, 0.06, -0.06, cp=2.0).sigma == pytest.approx(0.01)
    # uniform on [-t, t] has variance t^2/3 whatever Cp says
    assert Dimension("a", 10, 0.06, -0.06, cp=2.0, distribution="uniform").sigma == pytest.approx(0.06 / math.sqrt(3))


@pytest.mark.parametrize("kwargs", [dict(direction=0), dict(upper=-0.2), dict(cp=0), dict(distribution="beta")])
def test_invalid_dimension_rejected(kwargs):
    base = dict(name="x", nominal=1.0, upper=0.1, lower=-0.1)
    with pytest.raises(ValueError):
        Dimension(**{**base, **kwargs})


def test_position_tolerance_rfs_is_half_each_side():
    assert position_as_bilateral(0.2) == (0.1, -0.1)


# ------------------------------------------------ hand calcs on sample assembly
def test_sample_nominal_and_mean_gap(dims):
    r = analyze(dims, 0.10, 0.60)
    assert r.nominal_gap == pytest.approx(53.28 - 14 - 25 - 14)          # 0.28
    assert r.mean_gap == pytest.approx(53.28 - 13.94 - 25 - 13.94)       # 0.40


def test_sample_worst_case_fails_upper_limit(dims):
    r = analyze(dims, 0.10, 0.60)
    assert r.wc_half == pytest.approx(0.08 + 0.06 + 0.05 + 0.06)         # 0.25
    assert r.wc_limits == pytest.approx((0.15, 0.65))
    assert not r.passes(r.wc_limits)


def test_sample_rss_passes(dims):
    r = analyze(dims, 0.10, 0.60)
    assert r.rss_half == pytest.approx(math.sqrt(0.08**2 + 0.06**2 + 0.05**2 + 0.06**2))   # 0.12689
    assert r.rss_limits == pytest.approx((0.27311, 0.52689), abs=1e-5)
    assert r.passes(r.rss_limits)


def test_sample_statistical_sigma_and_cpk(dims):
    r = analyze(dims, 0.10, 0.60)
    sig = math.sqrt((0.08 / 3.99) ** 2 + 0.02**2 + (0.05 / 3.99) ** 2 + 0.02**2)
    assert r.sigma_gap == pytest.approx(sig)
    assert r.cpk == pytest.approx(0.20 / (3 * sig))
    assert r.cpk == pytest.approx(1.808, abs=1e-3)


def test_contributions_sum_to_100(dims):
    c = analyze(dims).contributions
    assert c["wc_pct"].sum() == pytest.approx(100)
    assert c["stat_pct"].sum() == pytest.approx(100)
    assert c.loc[c.dimension == "Housing bore depth (A)", "wc_pct"].item() == pytest.approx(32.0)


def test_rss_equals_three_sigma_when_cp_is_one():
    d = [Dimension(f"d{i}", 10, t, -t, direction=(-1) ** i) for i, t in enumerate([0.1, 0.05, 0.2])]
    r = analyze(d)
    assert r.rss_half == pytest.approx(3 * r.sigma_gap)


def test_rss_never_exceeds_worst_case():
    rng = np.random.default_rng(1)
    for _ in range(50):
        d = [Dimension("d", 5, t, -t) for t in rng.uniform(0.01, 0.3, rng.integers(1, 8))]
        r = analyze(d)
        assert r.rss_half <= r.wc_half + 1e-12


def test_one_sided_spec_and_no_spec(dims):
    assert analyze(dims, lsl=0.10).cpk == pytest.approx((0.40 - 0.10) / (3 * analyze(dims).sigma_gap))
    r = analyze(dims)
    assert math.isnan(r.cpk) and r.ppm == 0 and r.passes(r.wc_limits)


def test_ppm_matches_normal_tails():
    d = [Dimension("a", 1.0, 0.03, -0.03)]       # sigma 0.01, mean 1.0
    r = analyze(d, 0.98, 1.02)                    # +/- 2 sigma
    assert r.ppm == pytest.approx(2 * stats.norm.sf(2) * 1e6)


def test_empty_stack_rejected():
    with pytest.raises(ValueError):
        analyze([])


# ------------------------------------------------------------ Monte Carlo
def test_monte_carlo_converges_to_statistical_model(dims):
    r = analyze(dims, 0.10, 0.60)
    mc = monte_carlo(dims, 0.10, 0.60, n=400_000, seed=3)
    assert mc.mean == pytest.approx(r.mean_gap, abs=3e-4)
    assert mc.std == pytest.approx(r.sigma_gap, rel=0.01)
    assert mc.p_low == pytest.approx(r.stat_limits[0], abs=2e-3)
    assert mc.p_high == pytest.approx(r.stat_limits[1], abs=2e-3)


def test_monte_carlo_ppm_matches_normal_model_on_tight_spec():
    d = [Dimension("a", 10, 0.06, -0.06), Dimension("b", 5, 0.06, -0.06, direction=-1)]
    r = analyze(d, 4.97, 5.03)                     # sigma_gap = 0.02*sqrt(2); about 13% out
    mc = monte_carlo(d, 4.97, 5.03, n=400_000, seed=4)
    assert mc.ppm == pytest.approx(r.ppm, rel=0.02)


def test_monte_carlo_uniform_variance():
    d = [Dimension("u", 0, 0.1, -0.1, distribution="uniform")] * 3
    mc = monte_carlo(d, n=400_000, seed=5)
    assert mc.std == pytest.approx(math.sqrt(3 * 0.1**2 / 3), rel=0.01)


def test_monte_carlo_is_reproducible(dims):
    assert monte_carlo(dims, seed=7, n=1000).mean == monte_carlo(dims, seed=7, n=1000).mean


# ------------------------------------------------------------------ CSV I/O
def test_frame_round_trip(dims):
    assert stack.from_frame(stack.to_frame(dims)) == dims


def test_optional_columns_default():
    df = pd.DataFrame({"name": ["a"], "nominal": [1.0], "upper": [0.1], "lower": [-0.1], "direction": [1],
                       "cp": [np.nan]})
    (d,) = stack.from_frame(df)
    assert d.cp == 1.0 and d.distribution == "normal" and d.source == ""


def test_missing_column_reported():
    with pytest.raises(ValueError, match="direction"):
        stack.from_frame(pd.DataFrame({"name": ["a"], "nominal": [1], "upper": [0.1], "lower": [-0.1]}))
