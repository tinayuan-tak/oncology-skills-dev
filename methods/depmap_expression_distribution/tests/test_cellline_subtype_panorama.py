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


# ── Finer evidence grades (AM#659 opt-in, cards widened by contracts #806) ─────────────────────


def _stub_tpm(monkeypatch, n_models: int = 200, value: float = 6.0):
    """Stub the DepMap TPM load with `n_models` ModelIDs at a fixed log2(TPM+1). Offline."""
    tpm = {f"ACH-{i:06d}": value for i in range(n_models)}
    monkeypatch.setattr(R, "_cached_tpm", lambda target, release_pin: (tpm, []))
    return tpm


def test_exploratory_band_edges_are_inclusive(monkeypatch):
    """n=10 grades `exploratory`, n=9 does not — the inclusive floor, asserted at both edges.

    This arm is why the second band exists at all: DepMap panels are n~20-130 per indication BEFORE
    the stratum split, so a floor of 30 rejects nearly every cell-line stratum. Measured on the
    landed shards the real information sits in this band (coadread-cms CMS3 19 / CMS1 17,
    hnsc larynx 10, sclc SCLC_N 15).
    """
    _stub_tpm(monkeypatch)
    grade = lambda k: R.read_stratified_expression(  # noqa: E731
        "EPCAM", "COADREAD", _sample_id_filter={f"ACH-{i:06d}" for i in range(k)}
    )["evidence_state"]
    assert grade(9) == "underpowered"
    assert grade(10) == "exploratory"
    assert grade(29) == "exploratory"
    assert grade(30) == "measured"


def test_exploratory_stratum_reports_stats_but_is_excluded_from_the_rollup(monkeypatch):
    """Visible, not claimable: stats present, `subtype_signal` never filled, measured count 0."""
    _stub_tpm(monkeypatch, value=7.5)
    rec = R.read_stratified_expression("EPCAM", "COADREAD", _sample_id_filter={f"ACH-{i:06d}" for i in range(15)})
    assert rec["evidence_state"] == "exploratory"
    assert rec["median_log2tpm"] == 7.5 and rec["subgroup_n"] == 15
    out = R._subtype_rollup([R._expression_projection("CMS3", rec)], pooled_median=5.0)
    assert out["n_subtypes_measured"] == 0 and out["n_subtypes_enriched"] == 0
    assert out["spotlight_subtype"] is None  # cannot be spotlighted on hypothesis-grade n


def test_unevaluable_vs_absent_is_decided_by_the_assigner_not_the_count(monkeypatch):
    """0 member ModelIDs: `unevaluable` when nobody was classified, `absent` when they were.

    Unlike the CPTAC arm there is no `n == 0` early return here, so this is the live path — and it
    is the DepMap STAD/PAAD case, where the axis is defined in the catalog but every stratum is
    unclassified. `absent` would have laundered that into a measured negative about the axis.
    """
    _stub_tpm(monkeypatch)
    grade = lambda flag: R.read_stratified_expression(  # noqa: E731
        "EPCAM", "STAD", _sample_id_filter=set(), _stratum_evaluated=flag
    )["evidence_state"]
    assert grade(False) == "unevaluable"
    assert grade(True) == "absent"
    assert grade(None) == "absent"  # unstratified callers unchanged


def test_all_unclassified_axis_grades_unevaluable_not_empty(monkeypatch):
    """The axis rollup must not assert a measured absence it never measured.

    `unevaluable` is ranked ABOVE `empty` deliberately: `empty` claims "we looked, nobody
    qualifies", and there is no such measurement when the assigner abstained on everyone. The
    `empty` control below is what makes this a real discrimination rather than a relabelling.
    """
    _stub_tpm(monkeypatch)
    unclassified = [
        R._expression_projection(
            s,
            R.read_stratified_expression("EPCAM", "STAD", _sample_id_filter=set(), _stratum_evaluated=False),
        )
        for s in ("stratum_a", "stratum_b")
    ]
    assert R._subtype_rollup(unclassified, pooled_median=None)["subtype_axis_quality"] == "unevaluable"
    # CONTROL: same shape, but the assigner DID classify — a real negative about the axis.
    evaluated_empty = [
        R._expression_projection(
            s,
            R.read_stratified_expression("EPCAM", "STAD", _sample_id_filter=set(), _stratum_evaluated=True),
        )
        for s in ("stratum_a", "stratum_b")
    ]
    assert R._subtype_rollup(evaluated_empty, pooled_median=None)["subtype_axis_quality"] == "empty"


# ── The APPLIED enrichment cut + the resolved-shard stamp (AM follow-on to contracts #811) ────────


def _projected(stratum: str, median, state: str = "measured") -> dict:
    """A per_subgroup_metrics row built through the PRODUCTION projection.

    The two post-pass fields get their null defaults in `_expression_projection`, not in
    `_subtype_rollup` (which visits `measured` rows only), so a hand-built dict like `_rec` above
    tests a shape the module never emits and KeyErrors on exactly the null cases under test.
    """
    return R._expression_projection(
        stratum,
        {
            "expression_class": "broadly_detected",
            "evidence_state": state,
            "median_log2tpm": median,
            "fraction_expressed": 0.9,
            "subgroup_n": 40,
            "subgroup_n_floor_met": True,
            "source_cohort": "DepMap-26q1",
        },
    )


def test_projection_declares_both_post_pass_keys():
    proj = _projected("KRAS_G12C", None, state="underpowered")
    assert "subtype_signal" in proj and proj["subtype_signal"] is None
    assert "subtype_enrich_log2_delta" in proj and proj["subtype_enrich_log2_delta"] is None


def test_applied_delta_separates_a_measured_uniform_from_an_abstention():
    """On THIS arm the signal alone cannot gate the delta, and that is the whole subtlety.

    `_classify_subtype_signal` falls THROUGH to "uniform" when either median is None (unlike the
    CPTAC arm, which returns None) — so a stratum that was never compared carries a token that looks
    like a measured finding. The delta is therefore gated on the MEDIANS, and a null delta on a
    `uniform` row is the reader's only signal that no comparison ran. Asserting both rows is
    essential: they carry the same `subtype_signal` and differ ONLY in the new field.
    """
    compared = _projected("EGFR_mut", 5.4)  # within the band -> a real `uniform` call
    abstained = _projected("unknown", None)  # no median -> fall-through `uniform`
    R._subtype_rollup([compared, abstained], pooled_median=5.0)
    assert compared["subtype_signal"] == "uniform" and abstained["subtype_signal"] == "uniform"
    assert compared["subtype_enrich_log2_delta"] == 1.0
    assert abstained["subtype_enrich_log2_delta"] is None
    # no pooled baseline -> nothing was compared on ANY row
    fresh = [_projected("EGFR_mut", 5.4)]
    R._subtype_rollup(fresh, pooled_median=None)
    assert fresh[0]["subtype_enrich_log2_delta"] is None


def test_emitted_delta_is_the_cut_this_arm_actually_applies():
    """The emitted value must be 1.0 HERE and 0.585 on the tumour RNA arm — the cross-arm point.

    Same word (`enriched`), a 2x linear shift on cell lines vs a 1.5x shift in tumours. The two
    constants are deliberately NOT aligned (moving the cell-line cut would silently reclassify live
    strata); emitting the applied value is what makes the arms joinable instead. Pinning the number
    against the module constant AND against the sibling's would let a single edit satisfy both, so
    this asserts the literal.
    """
    enriched = _projected("KRAS_G12C", 6.5)
    R._subtype_rollup([enriched], pooled_median=5.0)
    assert enriched["subtype_signal"] == "enriched"
    assert enriched["subtype_enrich_log2_delta"] == R._SUBTYPE_ENRICH_LOG2_DELTA == 1.0


def test_assignment_manifest_stamps_the_shard_the_run_read(monkeypatch):
    """A reader-side stamp of the resolved shard, which is what makes staleness auditable.

    `envelope.py::_refine_product_id_staleness` calls staleness INDETERMINATE for want of exactly
    this: a card may pin several candidate shards, so without the stamp the envelope cannot tell
    WHICH one a run read. This arm previously emitted nothing, while its tumour-RNA sibling always
    has. The composer is faked because the assertion is about the stamp, not the read.
    """
    monkeypatch.setattr(R, "build_panorama", lambda *a, **k: {"per_subgroup_metrics": []})
    monkeypatch.setattr(R, "_pooled_lineage_median", lambda *a, **k: None)
    pan = R.build_expression_subtype_panorama(
        "EPCAM",
        "COADREAD",
        subgroups=["MSI_H"],
        subgroup_assignments_manifest="depmap-subgroup-assignments-coadread-v1",
    )
    assert pan["assignment_manifest"] == "depmap-subgroup-assignments-coadread-v1"
