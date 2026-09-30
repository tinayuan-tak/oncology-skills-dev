"""Tests for the indication-conditioned stratified-dependency ladder (T2.0).

The ladder is the CRITICAL fix: it stops a lineage-context-dependent oncogene (BRAF) from reading a
pan-cancer strong biomarker under an indication label. Pure-function (no S3): a fake `compute` thunk
returns canned results keyed on the restrict set, so we test the DECISION logic exactly.
"""

from __future__ import annotations

from onc_methods.depmap_common.lineage_ladder import (
    apply_lineage_ladder,
    models_in_lineage,
)

CLS = "mutation_stratification_class"

# Synthetic Model.csv metadata: 3 Bowel lines + 3 Skin lines.
META = {
    "ACH-b1": {"OncotreeLineage": "Bowel"},
    "ACH-b2": {"OncotreeLineage": "Bowel"},
    "ACH-b3": {"OncotreeLineage": "Bowel"},
    "ACH-s1": {"OncotreeLineage": "Skin"},
    "ACH-s2": {"OncotreeLineage": "Skin"},
}


# ── models_in_lineage ────────────────────────────────────────────────────────
def test_models_in_lineage_maps_indication():
    assert models_in_lineage(META, "COADREAD") == {"ACH-b1", "ACH-b2", "ACH-b3"}
    assert models_in_lineage(META, "SKCM") == {"ACH-s1", "ACH-s2"}


def test_models_in_lineage_none_when_unmapped_or_missing():
    assert models_in_lineage(META, None) is None
    assert models_in_lineage(META, "NOT_AN_INDICATION") is None


# ── the ladder decision ──────────────────────────────────────────────────────
def _thunk(pan_class, within_class, hybrid_class=None):
    """compute(mut_models, wt_models):
      (None, None) → pan; (L, L) → full within-lineage; (L, None) → lineage-mut-vs-pan-wt hybrid.
    hybrid_class defaults to within_class when not exercised."""

    def compute(mut_models, wt_models):
        if mut_models is None and wt_models is None:
            return {CLS: pan_class}
        if mut_models is not None and wt_models is not None:
            return {CLS: within_class}  # rung 1: full within-lineage
        return {CLS: hybrid_class if hybrid_class is not None else within_class}  # rung 2: mut vs pan-wt

    return compute


def test_within_lineage_wins_when_powered():
    # BRAF archetype: pan says strong (melanoma/thyroid pooled), within-CRC says not-stratified.
    r = apply_lineage_ladder(_thunk("mutant_strongly_dependent", "not_mutation_stratified"), CLS, META, "COADREAD")
    assert r["evidence_scope"] == "within_indication"
    assert r[CLS] == "not_mutation_stratified"  # the honest CRC answer
    assert r[f"pan_lineage_{CLS}"] == "mutant_strongly_dependent"  # pan kept for audit
    assert r["lineage_context_divergent"] is True  # within (no) vs pan (yes) disagree


def test_within_lineage_confirms_when_agree():
    # KRAS archetype: strong both pan and within-CRC → within wins, no divergence.
    r = apply_lineage_ladder(_thunk("mutant_strongly_dependent", "mutant_strongly_dependent"), CLS, META, "COADREAD")
    assert r["evidence_scope"] == "within_indication"
    assert r[CLS] == "mutant_strongly_dependent"
    assert r["lineage_context_divergent"] is False


def test_rung2_hybrid_when_within_wt_underpowered():
    # BRAF/melanoma archetype: full within-lineage insufficient (too few WT), but lineage-mut-vs-pan-WT
    # IS powered and strong → rung 2 keeps the strong call (NOT downgraded). This is the fix for the
    # high-prevalence-driver under-call the live backtest exposed.
    r = apply_lineage_ladder(
        _thunk("mutant_strongly_dependent", "insufficient_mutation_rate", hybrid_class="mutant_strongly_dependent"),
        CLS,
        META,
        "SKCM",
    )
    assert r["evidence_scope"] == "within_indication_mut_vs_pan_wt"
    assert r[CLS] == "mutant_strongly_dependent"  # NOT downgraded — the whole point


def test_pan_fallback_downgrades_only_when_even_hybrid_insufficient():
    # within-lineage AND hybrid both insufficient (even lineage mutants too few) → pan-DepMap, strong→moderate.
    r = apply_lineage_ladder(
        _thunk("mutant_strongly_dependent", "insufficient_mutation_rate", hybrid_class="insufficient_mutation_rate"),
        CLS,
        META,
        "COADREAD",
    )
    assert r["evidence_scope"] == "pan_lineage_evidence_only"
    assert r[CLS] == "mutant_moderately_dependent"  # DOWNGRADED
    assert r[f"pan_lineage_raw_{CLS}"] == "mutant_strongly_dependent"


def test_pan_fallback_keeps_moderate_as_is():
    # both within arms insufficient; a pan 'moderate' has nothing to downgrade → unchanged, pan-only.
    r = apply_lineage_ladder(
        _thunk("mutant_moderately_dependent", "insufficient_mutation_rate", hybrid_class="insufficient_mutation_rate"),
        CLS,
        META,
        "COADREAD",
    )
    assert r["evidence_scope"] == "pan_lineage_evidence_only"
    assert r[CLS] == "mutant_moderately_dependent"


# ── amp-expr class vocabulary (regression guard) ─────────────────────────────
# depmap_amp_expr_dependency emits the fully-spelled labels below (cli._LABELS), NOT the
# abbreviated `amp_expr_*` form. A prior version of _STRONG_TO_MODERATE keyed the abbreviated
# form, so the amp-expr class was absent from both the downgrade map and _DEPENDENT_CLASSES:
# rung-3 never downgraded a strong amp-expr call, and the divergence flag mis-computed. These two
# tests pin the ladder to the real amp-expr vocabulary so that regression cannot return silently.
_AE_STRONG = "amplified_overexpressed_strongly_dependent"
_AE_MODERATE = "amplified_overexpressed_moderately_dependent"
_AE_INSUFFICIENT = "insufficient_amp_expr_rate"
_AE_CLS = "amp_expr_stratification_class"


def _ae_thunk(pan_class, within_class, hybrid_class=None):
    """Like `_thunk`, but keys the returned dict on the amp-expr class field (`_AE_CLS`)."""

    def compute(mut_models, wt_models):
        if mut_models is None and wt_models is None:
            return {_AE_CLS: pan_class}
        if mut_models is not None and wt_models is not None:
            return {_AE_CLS: within_class}
        return {_AE_CLS: hybrid_class if hybrid_class is not None else within_class}

    return compute


def test_amp_expr_pan_fallback_downgrades_strong():
    # within + hybrid both insufficient → pan-DepMap, and a STRONG amp-expr call must be
    # downgraded to moderate (cannot confirm indication-specificity). Pre-fix this stayed strong.
    r = apply_lineage_ladder(
        _ae_thunk(_AE_STRONG, _AE_INSUFFICIENT, hybrid_class=_AE_INSUFFICIENT), _AE_CLS, META, "COADREAD"
    )
    assert r["evidence_scope"] == "pan_lineage_evidence_only"
    assert r[_AE_CLS] == _AE_MODERATE  # DOWNGRADED (was strong pre-fix)
    assert r[f"pan_lineage_raw_{_AE_CLS}"] == _AE_STRONG


def test_amp_expr_divergence_flag_uses_real_labels():
    # within-lineage says not-stratified, pan says strongly-dependent → the two disagree, so the
    # divergence flag must fire. Pre-fix the amp-expr strong class was not in _DEPENDENT_CLASSES,
    # so the flag was computed as False (pan read as "not a dependency call").
    r = apply_lineage_ladder(_ae_thunk(_AE_STRONG, "not_amp_expr_stratified"), _AE_CLS, META, "COADREAD")
    assert r["evidence_scope"] == "within_indication"
    assert r[_AE_CLS] == "not_amp_expr_stratified"
    assert r["lineage_context_divergent"] is True


def test_unmapped_indication_is_pan_no_indication():
    r = apply_lineage_ladder(_thunk("mutant_strongly_dependent", "x"), CLS, META, None)
    assert r["evidence_scope"] == "pan_no_indication"
    assert r[CLS] == "mutant_strongly_dependent"  # pan, un-downgraded (no lineage to try)
    assert r["lineage_context_divergent"] is False
