"""classify() ns-split (2026-08-14 multi-pair review, finding #5).

The former single `ns` conflated "not statistically significant" (q>=0.05) with "significant but
biologically small" (q<0.05, |logfc|<=0.5). classify() now returns not_significant vs small_effect.
VERDICT-SAFE invariant pinned here: the UNION of the two new labels == the old `ns` set, and neither
is an elevated class — so the breadth/coverage rollups (which key on {strong_up, modest_up} /
data_unavailable, never on the literal `ns`) are unchanged.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import numpy as np  # noqa: E402

_STEP = Path(__file__).resolve().parents[3] / "onc_methods" / "cptac_protein_deg" / "steps" / "03_pool_and_write.py"


def _load():
    spec = importlib.util.spec_from_file_location("cptac_pool_write", _STEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_m = _load()


def test_not_significant_when_q_high():
    assert _m.classify(0.1, 0.9) == "not_significant"
    assert _m.classify(3.0, 0.20) == "not_significant"  # large fc but q>=0.05 → still not significant


def test_missing_estimate_is_data_unavailable_missing_q_is_not_significant():
    """W4 (2026-09-12) corrected an ASYMMETRY this test previously pinned.

    A missing EFFECT ESTIMATE and a missing Q-VALUE are not the same thing:
      - no logFC (NaN, or +/-Inf when MSstatsTMT has only one condition) -> nothing was estimated, so
        `not_significant` ("tested, no difference") is a claim the data cannot support -> data_unavailable.
      - a logFC with no q -> an effect WAS estimated but significance could not be assessed; the
        conservative `not_significant` is right (it keeps the row out of the elevated classes).
    Zero rows of the shipped v1.2.0 product have a NaN logFC (all 1,618 unestimable rows are +/-Inf), so
    the NaN half of this change is behavior-neutral on real data; it removes the conflation that let the
    Inf half ship as `not_significant`. See test_unestimable_contrast.py."""
    assert _m.classify(np.nan, 0.01) == "data_unavailable"
    assert _m.classify(np.inf, np.nan) == "data_unavailable"
    assert _m.classify(-np.inf, np.nan) == "data_unavailable"
    assert _m.classify(0.8, np.nan) == "not_significant"


def test_small_effect_when_significant_but_small():
    assert _m.classify(0.5, 1e-4) == "small_effect"  # q<0.05, |logfc|<=0.5
    assert _m.classify(-0.5, 1e-3) == "small_effect"
    assert _m.classify(0.0, 1e-6) == "small_effect"


def test_up_down_bands_unchanged():
    assert _m.classify(2.0, 1e-4) == "strong_up"
    assert _m.classify(0.8, 1e-3) == "modest_up"
    assert _m.classify(-2.0, 1e-4) == "strong_down"
    assert _m.classify(-0.8, 1e-3) == "modest_down"


def test_variance_aware_negligible_d_demotes_to_small_effect_G7():
    """G7: a significant call with a large RAW logFC but NEGLIGIBLE standardized effect (Cohen's d < 0.2 —
    cleared significance via cohort size) is small_effect, not strong_up/modest_up."""
    # logFC 2.0, SE 0.5 → t=4.0; n_t=n_n=900 → n_eff=450 → d≈0.189 (negligible) → small_effect
    assert _m.classify(2.0, 1e-4, se=0.5, n_tumor=900, n_normal=900) == "small_effect"
    # a modest_up-magnitude call likewise demotes when d is negligible
    assert _m.classify(0.8, 1e-3, se=0.2, n_tumor=900, n_normal=900) == "small_effect"


def test_variance_aware_real_effect_keeps_up_class_G7():
    """A significant call with a REAL standardized effect (small n → large Cohen's d) keeps its up class."""
    # logFC 2.0, SE 0.5 → t=4.0; n_t=n_n=30 → n_eff=15 → d≈1.03 (large) → strong_up
    assert _m.classify(2.0, 1e-4, se=0.5, n_tumor=30, n_normal=30) == "strong_up"


def test_variance_aware_falls_back_to_raw_bands_when_se_missing_G7():
    """SE / n unavailable (older upstream rows) → fall back to the raw-logFC bands (no downgrade)."""
    assert _m.classify(2.0, 1e-4) == "strong_up"  # no se/n
    assert _m.classify(2.0, 1e-4, se=None, n_tumor=900, n_normal=900) == "strong_up"
    assert _m.classify(2.0, 1e-4, se=float("nan"), n_tumor=9, n_normal=9) == "strong_up"


def test_variance_aware_via_pvalue_fallback_no_se():
    """The p-value fallback (no SE) makes classify variance-aware on a product that carries p + n but not
    SE (the currently-deployed cptac product). A modest_up-magnitude call with a marginal RAW p at large n
    → negligible Cohen's d → small_effect, WITHOUT any SE."""
    # logFC 0.8, raw p 0.04 → z≈2.05; n_t=n_n=900 → n_eff=450 → d≈0.097 (negligible) → small_effect
    assert _m.classify(0.8, 1e-3, se=None, n_tumor=900, n_normal=900, p_value=0.04) == "small_effect"
    # same effect at small n → real Cohen's d → keeps modest_up
    assert _m.classify(0.8, 1e-3, se=None, n_tumor=20, n_normal=20, p_value=0.04) == "modest_up"


def test_exact_se_preferred_over_pvalue_when_present():
    """When SE is present it drives the standardized effect (exact), regardless of p_value."""
    # SE path: logFC 2.0 / SE 0.5 = t 4.0; n_eff 450 → d≈0.189 negligible → small_effect
    assert _m.classify(2.0, 1e-4, se=0.5, n_tumor=900, n_normal=900, p_value=0.001) == "small_effect"


def test_no_se_and_no_pvalue_falls_back_to_raw_bands():
    """Neither SE nor p available → raw-logFC bands (no downgrade)."""
    assert _m.classify(2.0, 1e-4, se=None, n_tumor=900, n_normal=900, p_value=None) == "strong_up"


def test_old_ns_union_preserved_and_not_elevated():
    """Everything that used to be `ns` is now not_significant OR small_effect, and NEITHER is an
    elevated class — the verdict-safety invariant for breadth/coverage rollups."""
    old_ns_cases = [(0.1, 0.9), (3.0, 0.20), (0.5, 1e-4), (0.0, 1e-6)]
    labels = {_m.classify(fc, q) for fc, q in old_ns_cases}
    assert labels <= {"not_significant", "small_effect"}
    assert labels.isdisjoint({"strong_up", "modest_up"})  # never elevated
    # (np.nan, 0.01) moved out of this union in W4 -> data_unavailable, which is likewise never elevated.
    # That is the invariant this test exists to protect, so it is asserted here rather than dropped.
    assert _m.classify(np.nan, 0.01) not in {"strong_up", "modest_up"}
