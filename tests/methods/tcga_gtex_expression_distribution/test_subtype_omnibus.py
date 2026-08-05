"""Phase 3: across-subtype Kruskal-Wallis + ε² omnibus (stats + reader wiring).

The hand-implemented KW H + tie correction + chi-square-SF p are pinned against scipy
as the ORACLE (scipy is a test-only dependency; the method stays numpy-only). ε² is
checked against its closed form, the effect-size class against the cutoffs, and the
"class tracks EFFECT not p" property is pinned explicitly (the plan's risk #3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import stats as S  # noqa: E402


# ---- H + p vs scipy oracle ----
def test_kruskal_h_and_p_match_scipy():
    sp = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(0)
    groups = {"a": list(rng.normal(2, 1, 60)),
              "b": list(rng.normal(5, 1, 55)),
              "c": list(rng.normal(8, 1, 70))}
    out = S.kruskal_epsilon_squared(groups)
    H_sp, p_sp = sp.kruskal(*[np.asarray(v, float) for v in groups.values()])
    assert out["subtype_omnibus_kruskal_h"] == pytest.approx(H_sp, rel=1e-9)
    assert out["subtype_omnibus_p"] == pytest.approx(p_sp, rel=1e-6)


def test_kruskal_tie_correction_matches_scipy():
    """Heavily-tied integer data — exercises the tie-correction term; scipy applies the
    same correction, so an exact match proves it."""
    sp = pytest.importorskip("scipy.stats")
    groups = {"a": [1, 1, 2, 2, 3] * 8, "b": [2, 3, 3, 4, 4] * 8, "c": [5, 5, 6, 6, 7] * 8}
    out = S.kruskal_epsilon_squared(groups)
    H_sp, p_sp = sp.kruskal(*[np.asarray(v, float) for v in groups.values()])
    assert out["subtype_omnibus_kruskal_h"] == pytest.approx(H_sp, rel=1e-9)
    assert out["subtype_omnibus_p"] == pytest.approx(p_sp, rel=1e-6)


# ---- ε² + effect-size class ----
def test_epsilon_squared_closed_form_and_class():
    sp = pytest.importorskip("scipy.stats")
    rng = np.random.default_rng(1)
    groups = {"a": list(rng.normal(2, 1, 50)), "b": list(rng.normal(8, 1, 50))}
    out = S.kruskal_epsilon_squared(groups)
    H = out["subtype_omnibus_kruskal_h"]
    N = 100; k = 2
    assert out["subtype_variance_explained"] == pytest.approx((H - k + 1) / (N - k), rel=1e-9)
    assert out["subtype_effect_size_class"] == "large"     # well-separated → ε² >> 0.14
    assert out["which_subtypes_separate"] == {"highest": "b", "lowest": "a"}


def test_class_tracks_effect_not_p():
    """The plan's risk #3: at large n a TRIVIAL between-group difference is still 'significant'
    (small p) yet has a NEGLIGIBLE effect size. The class must bin on ε², not p."""
    rng = np.random.default_rng(2)
    # tiny mean shift (0.15 log2TPM) but big n → significant p, negligible ε²
    groups = {"a": list(rng.normal(4.0, 1.0, 400)), "b": list(rng.normal(4.15, 1.0, 400))}
    out = S.kruskal_epsilon_squared(groups)
    assert out["subtype_variance_explained"] < S.EPSILON_SQUARED_MODERATE
    assert out["subtype_effect_size_class"] == "negligible"
    # ...even if the p-value is (or is near) significant — significance != actionability.
    assert out["subtype_omnibus_p"] is not None


def test_epsilon_squared_clamped_nonnegative():
    """Identical groups → H below its df floor → ε² noise clamps to 0 / negligible."""
    groups = {"a": [4.0, 4.1, 3.9, 4.05] * 12, "b": [4.0, 4.1, 3.9, 4.05] * 12}
    out = S.kruskal_epsilon_squared(groups)
    assert out["subtype_variance_explained"] >= 0.0
    assert out["subtype_effect_size_class"] in {"negligible"}


# ---- degenerate / data_unavailable safety ----
@pytest.mark.parametrize("groups", [
    {},                                   # no strata
    {"a": [1, 2, 3]},                     # one stratum
    {"a": [1, 2, 3], "b": [4]},           # second stratum below min_group_n
])
def test_data_unavailable_when_under_two_powered_strata(groups):
    out = S.kruskal_epsilon_squared(groups)
    assert out["subtype_effect_size_class"] == "data_unavailable"
    assert out["subtype_variance_explained"] is None
    assert out["which_subtypes_separate"] is None


def test_non_finite_dropped_before_test():
    """inf/NaN must be dropped (they'd poison ranking) — a group left with <min_group_n
    finite values falls out of the test."""
    out = S.kruskal_epsilon_squared({"a": [1.0, 2.0, float("inf"), 3.0, float("nan")],
                                     "b": [5.0, 6.0, 7.0]})
    # both groups still have >=2 finite → test runs; the inf/nan simply excluded
    assert out["n_subtypes_tested"] == 2
    assert out["subtype_omnibus_kruskal_h"] is not None
