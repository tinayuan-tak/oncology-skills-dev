"""Offline unit tests for the cell-line RNA subtype panorama (WS-C).

The live reader (read_stratified_expression) is exercised end-to-end against the COADREAD DepMap
shard in the live-smoke; these tests pin the pure classification/rollup logic + record shape with
no S3/DepMap dependency."""

from __future__ import annotations

from methods.depmap_expression_distribution import read as R


def test_classify_subtype_signal_vs_pooled():
    # >= +1.0 log2 over pooled → enriched; <= -1.0 → depleted; within → uniform
    assert R._classify_subtype_signal(6.5, 5.0) == "enriched"
    assert R._classify_subtype_signal(3.5, 5.0) == "depleted"
    assert R._classify_subtype_signal(5.4, 5.0) == "uniform"
    # null-safe
    assert R._classify_subtype_signal(None, 5.0) == "uniform"
    assert R._classify_subtype_signal(6.0, None) == "uniform"


def test_expression_class_thresholds():
    assert R._expression_class(6.0) == "broadly_high"  # >= 5.0
    assert R._expression_class(2.0) == "broadly_detected"  # >= 1.0
    assert R._expression_class(0.3) == "broadly_low"
    assert R._expression_class(None) == "insufficient"


def _rec(stratum, median, n, state="measured"):
    return {
        "stratum": stratum,
        "median_log2tpm": median,
        "subgroup_n": n,
        "evidence_state": state,
        "subtype_signal": None,
    }


def test_rollup_enriched_and_uniform():
    # only 'measured' strata are classified; underpowered are excluded from counts
    recs = [_rec("KRAS_G12C", 7.5, 40), _rec("EGFR_mut", 5.0, 35), _rec("rare", 8.0, 10, state="underpowered")]
    out = R._subtype_rollup(recs, pooled_median=5.0)
    assert out["subtype_axis_available"] is True
    assert out["n_subtypes_measured"] == 2  # rare (underpowered) excluded
    assert out["n_subtypes_enriched"] == 1  # KRAS_G12C 7.5 vs 5.0 pooled
    assert out["subtype_stratification_class"] == "subtype_enriched"
    assert out["spotlight_subtype"] == "KRAS_G12C"
    # the measured records got their signal filled
    assert recs[0]["subtype_signal"] == "enriched"
    assert recs[1]["subtype_signal"] == "uniform"


def test_rollup_variable_when_both_enriched_and_depleted():
    recs = [_rec("A", 7.0, 40), _rec("B", 3.0, 40)]
    out = R._subtype_rollup(recs, pooled_median=5.0)
    assert out["n_subtypes_enriched"] == 1 and out["n_subtypes_depleted"] == 1
    assert out["subtype_stratification_class"] == "subtype_variable"


def test_rollup_pan_uniform():
    recs = [_rec("A", 5.2, 40), _rec("B", 4.9, 40)]
    out = R._subtype_rollup(recs, pooled_median=5.0)
    assert out["subtype_stratification_class"] == "pan_subtype_uniform"
    assert out["spotlight_subtype"] is None


def test_projection_shape():
    rec = {
        "expression_class": "broadly_high",
        "evidence_state": "measured",
        "median_log2tpm": 9.9,
        "fraction_expressed": 0.98,
        "subgroup_n": 100,
        "subgroup_n_floor_met": True,
        "source_cohort": "DepMap-26q1",
    }
    proj = R._expression_projection("MSS", rec)
    assert proj["stratum"] == "MSS" and proj["class"] == "broadly_high"
    assert proj["subtype_defining_data"] == "genomic" and proj["subtype_signal"] is None
