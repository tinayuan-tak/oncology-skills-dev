"""Unit tests for the subtype-stratified CPTAC protein reader (pure logic + monkeypatched reader)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from onc_methods.cptac_protein_distribution.read import (
    _classify_subtype_signal,
    _protein_class,
    _protein_projection,
    _subtype_rollup,
    build_protein_subtype_panorama,
    read_stratified_protein,
)


def test_protein_class_bands():
    assert _protein_class(1.0) == "protein_elevated"
    assert _protein_class(0.0) == "protein_neutral"
    assert _protein_class(-1.0) == "protein_reduced"
    assert _protein_class(None) == "insufficient"


def test_subtype_signal_vs_pooled():
    # PREFIXED tokens as of TC#816 (squash 98a7990): all three tier:subtype arms spell this field one way.
    # This arm's None (no comparison ran) is UNCHANGED — the stronger contract; only the spelling moved.
    assert _classify_subtype_signal(1.0, 0.0) == "subtype_enriched"
    assert _classify_subtype_signal(-1.0, 0.0) == "subtype_depleted"
    assert _classify_subtype_signal(0.1, 0.0) == "subtype_uniform"
    assert _classify_subtype_signal(None, 0.0) is None


def test_no_bare_vocabulary_survives_anywhere_in_this_arm():
    """The bare tokens must be GONE from the module source, not merely unused by the classifier.

    Asserting only return values would leave a stray comparison (`== "enriched"`) silently
    unmatchable — it would never raise, just never be true, and a count would read 0 forever. So this
    greps the module SOURCE. Scoped to `subtype_signal`'s vocabulary: the identically-spelled
    `{process}_class` literals in tcga_mc3_signatures are a DIFFERENT field and out of scope.
    """
    import re

    import onc_methods.cptac_protein_distribution.read as R

    src = Path(R.__file__).read_text()
    bare = re.findall(r'"(enriched|depleted|uniform)"', src)
    assert bare == [], f"bare subtype_signal tokens still present in read.py: {sorted(set(bare))}"
    # ...and the prefixed ones ARE present, so the assertion above cannot pass by the field vanishing.
    assert re.findall(r'"subtype_(?:enriched|depleted|uniform)"', src), "no prefixed tokens found — vacuous"


def test_rollup_axis_quality_and_stratification():
    records = [
        {"stratum": "MSI_H", "evidence_state": "measured", "median_log2_ratio": 0.9},
        {"stratum": "MSS", "evidence_state": "measured", "median_log2_ratio": 0.1},
    ]
    out = _subtype_rollup(records, pooled_median=0.1)
    assert out["subtype_axis_available"] is True
    assert out["subtype_axis_quality"] == "powered"  # 2 measured strata
    assert out["n_subtypes_measured"] == 2
    assert out["subtype_stratification_class"] == "subtype_enriched"  # MSI_H enriched vs pooled 0.1
    # underpowered -> axis quality drops
    under = [{"stratum": "MSI_H", "evidence_state": "underpowered", "median_log2_ratio": 0.9}]
    assert _subtype_rollup(under, 0.1)["subtype_axis_quality"] == "underpowered"


def _fake_per_sample():
    # 40 MSI_H aliquots (elevated), 40 MSS (neutral); tumor condition, COAD cohort
    rows = []
    for i in range(40):
        rows.append(
            {
                "gene_symbol": "EPCAM",
                "cohort": "COAD",
                "aliquot_submitter_id": f"MSI_{i}",
                "condition": "Tumor",
                "log2_ratio": 1.2,
            }
        )
    for i in range(40):
        rows.append(
            {
                "gene_symbol": "EPCAM",
                "cohort": "COAD",
                "aliquot_submitter_id": f"MSS_{i}",
                "condition": "Tumor",
                "log2_ratio": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_read_stratified_protein_filters_and_classifies(monkeypatch):
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    # single-call (no subgroups) with an explicit member filter -> the MSI_H stratum
    rec = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD", _sample_id_filter={f"MSI_{i}" for i in range(40)})
    assert rec["subgroup_n"] == 40
    assert rec["evidence_state"] == "measured"
    assert rec["protein_class"] == "protein_elevated"
    assert rec["median_log2_ratio"] == 1.2
    # a stratum below the n-floor -> underpowered
    rec2 = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD", _sample_id_filter={"MSS_0", "MSS_1"})
    assert rec2["subgroup_n"] == 2 and rec2["evidence_state"] == "underpowered"


def _fake_per_sample_with_missing():
    """40 MSI_H members: 10 detectable (finite), 29 below-LOD (NaN), 1 non-finite (+Inf).
    Plus a fully-below-LOD MSS stratum (all NaN)."""
    import numpy as np

    rows = []
    for i in range(10):
        rows.append(
            {
                "gene_symbol": "EPCAM",
                "cohort": "COAD",
                "aliquot_submitter_id": f"MSI_{i}",
                "condition": "Tumor",
                "log2_ratio": 1.2,
            }
        )
    for i in range(10, 39):
        rows.append(
            {
                "gene_symbol": "EPCAM",
                "cohort": "COAD",
                "aliquot_submitter_id": f"MSI_{i}",
                "condition": "Tumor",
                "log2_ratio": np.nan,
            }
        )
    # a stray +Inf (MSstatsTMT one-condition artefact) — must NOT poison the median or count as detectable
    rows.append(
        {
            "gene_symbol": "EPCAM",
            "cohort": "COAD",
            "aliquot_submitter_id": "MSI_39",
            "condition": "Tumor",
            "log2_ratio": np.inf,
        }
    )
    for i in range(40):
        rows.append(
            {
                "gene_symbol": "EPCAM",
                "cohort": "COAD",
                "aliquot_submitter_id": f"MSS_{i}",
                "condition": "Tumor",
                "log2_ratio": np.nan,
            }
        )
    return pd.DataFrame(rows)


def test_detectable_fraction_uses_total_aliquot_denominator(monkeypatch):
    """detectable_fraction divides FINITE values by the MEMBER count, not by themselves.

    Before F1 it was `np.isfinite(vals).mean()` on an already-dropna'd array — structurally ~1.0, so
    the field named to carry below-LOD information carried none. Here 10 of 40 members are finite
    (29 NaN + 1 +Inf), so the honest fraction is 0.25. The +Inf must also be excluded from the
    median (the F1 fold-in): it is non-finite, so it is neither counted nor allowed to poison
    np.median -> inf -> protein_elevated."""
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample_with_missing())
    rec = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD", _sample_id_filter={f"MSI_{i}" for i in range(40)})
    assert rec["subgroup_n"] == 10  # finite/detectable count, not the 40 members
    assert rec["detectable_fraction"] == 0.25  # 10 finite / 40 members
    assert rec["median_log2_ratio"] == 1.2  # +Inf did not poison the median
    assert rec["protein_class"] == "protein_elevated"


def test_all_below_lod_stratum_abstains_not_measured_absent(monkeypatch):
    """A POPULATED stratum whose every value is below-LOD must NOT read as a measured `absent`.

    This is the F1 headline false-negative: dropna() collapsed a members-present-but-undetectable
    stratum to n==0 and the `empty` template graded it `absent` (a measured negative) whenever the
    assigner had evaluated it. There is no denominator here, so no absence was tested (Card 4's
    `_unestimable_reason` posture): the stratum abstains with evidence_state `unevaluable` and an
    honest detectable_fraction of 0.0 — distinct from the membership-missing 0-member case, which
    still grades `absent` when evaluated."""
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample_with_missing())
    # MSS members are all NaN -> detection-missing, and _stratum_evaluated=True would have graded `absent`
    rec = read_stratified_protein(
        "EPCAM",
        "COADREAD",
        cohort="COAD",
        _sample_id_filter={f"MSS_{i}" for i in range(40)},
        _stratum_evaluated=True,
    )
    assert rec["evidence_state"] == "unevaluable"  # abstain, NOT the measured `absent` false-negative
    assert rec["detectable_fraction"] == 0.0
    assert rec["subgroup_n"] == 0
    assert rec["median_log2_ratio"] is None
    # contrast: a genuinely 0-MEMBER evaluated stratum is still a measured `absent` (unchanged path)
    zero_member = read_stratified_protein(
        "EPCAM", "COADREAD", cohort="COAD", _sample_id_filter=set(), _stratum_evaluated=True
    )
    assert zero_member["evidence_state"] == "absent"


def test_build_panorama_no_shard_is_honest_false():
    # an indication with no landed CPTAC shard -> honest subtype_axis_available:false, no S3 touched
    pan = build_protein_subtype_panorama("EPCAM", "GBM", subgroups=["x"])
    assert pan["subtype_axis_available"] is False
    assert pan["subtype_axis_quality"] == "unavailable"
    assert pan["subtype_stratification_class"] == "subtype_axis_unavailable"


# ── Finer evidence grades (AM#659 opt-in, cards widened by contracts #806) ─────────────────────


def test_exploratory_band_edges_are_inclusive(monkeypatch):
    """The 10-29 band, at both edges. n=10 is `exploratory` and n=9 is not.

    The floor is inclusive (`subgroup_n >= exploratory_floor`), which is not cosmetic: on the live
    NSCLC MAF shard `EGFR_mut_ex19del` has exactly n=10, so an exclusive comparison would leave the
    most clinically loaded stratum on the arm invisible. Both edges are asserted because a
    one-sided test cannot tell an inclusive floor from an exclusive one.
    """
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    grade = lambda k: read_stratified_protein(  # noqa: E731
        "EPCAM", "COADREAD", cohort="COAD", _sample_id_filter={f"MSI_{i}" for i in range(k)}
    )["evidence_state"]
    assert grade(10) == "exploratory"
    assert grade(29) == "exploratory"
    assert grade(9) == "underpowered"
    assert grade(30) == "measured"  # SUBGROUP_N_FLOOR keeps its one meaning


def test_exploratory_stratum_carries_stats_but_no_signal(monkeypatch):
    """An `exploratory` stratum stops being invisible WITHOUT becoming claimable.

    It reports its distribution stats, but the rollup keys `subtype_signal` off
    `evidence_state == "measured"`, so it can never carry a scoped call and never drives the
    cross-stratum reducers. That is the whole difference from relaxing SUBGROUP_N_FLOOR.
    """
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    rec = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD", _sample_id_filter={f"MSI_{i}" for i in range(15)})
    assert rec["evidence_state"] == "exploratory"
    assert rec["median_log2_ratio"] == 1.2  # stats ARE reported
    out = _subtype_rollup([_protein_projection("MSI_H", rec)], pooled_median=0.1)
    assert out["n_subtypes_measured"] == 0  # excluded from the measured count
    assert out["subtype_stratification_class"] == "pan_subtype_uniform"  # no signal claimed
    # …but the axis is now visibly contrastable-as-hypothesis rather than flatly underpowered.
    two = [_protein_projection("MSI_H", rec), _protein_projection("MSS", rec)]
    assert _subtype_rollup(two, 0.1)["subtype_axis_quality"] == "exploratory"


def test_unevaluable_only_when_the_assigner_abstained(monkeypatch):
    """0 members is graded three different ways depending on WHY, and the default is unchanged.

    `absent` is a measured negative ("we looked; nobody here qualifies"). A stratum nobody was ever
    classified into supports no such claim — that is the live DepMap STAD/PAAD shape. The `None`
    case is the byte-identity guarantee for every unstratified caller.
    """
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    call = lambda flag: read_stratified_protein(  # noqa: E731
        "EPCAM", "COADREAD", cohort="COAD", _sample_id_filter=set(), _stratum_evaluated=flag
    )["evidence_state"]
    assert call(False) == "unevaluable"
    assert call(True) == "absent"
    assert call(None) == "absent"  # historical default preserved


# ── The APPLIED enrichment cut + the resolved-shard stamp (AM follow-on to contracts #811) ────────


def _projected_row(stratum: str, evidence_state: str, median) -> dict:
    """A per_subgroup_metrics row built the way PRODUCTION builds it — through the projection.

    Not a convenience: the key-presence guarantee for the two post-pass fields lives in
    `_protein_projection`, NOT in `_subtype_rollup` (which writes them onto `measured` rows only and
    never visits the others). A hand-built dict therefore tests a record shape the module never
    emits, and it fails on the null cases for a reason that has nothing to do with the behaviour
    under test. `build_panorama(..., record_projection=_protein_projection)` is the single producer.
    """
    return _protein_projection(
        stratum,
        {
            "protein_class": "protein_neutral",
            "evidence_state": evidence_state,
            "median_log2_ratio": median,
            "detectable_fraction": 1.0,
            "subgroup_n": 40,
            "subgroup_n_floor_met": True,
            "source_cohort": "CPTAC-COAD",
        },
    )


def test_projection_declares_both_post_pass_keys(monkeypatch):
    """The record SHAPE must not encode whether the row was measured.

    `_subtype_rollup` writes `subtype_signal` and `subtype_enrich_log2_delta` onto `measured` rows
    only, so before these defaults an unmeasured stratum came back with the keys ABSENT while a
    measured one had them present. That is worse than a null: `rec["subtype_signal"]` KeyErrors on
    the first empty stratum, and `rec.get("subtype_signal", "subtype_uniform")` silently returns its default
    for exactly the rows that were never compared. Asserting `in` (not just the value) is the point —
    an `is None` check alone passes on an absent key via `.get`.
    """
    import onc_methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    # an EMPTY stratum: 0 members -> the `empty` template, i.e. exactly the unmeasured row whose
    # shape used to differ from a measured one.
    rec = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD", _sample_id_filter=set())
    assert rec["evidence_state"] != "measured"
    proj = _protein_projection("MSI_H", rec)
    assert "subtype_signal" in proj and proj["subtype_signal"] is None
    assert "subtype_enrich_log2_delta" in proj and proj["subtype_enrich_log2_delta"] is None


def test_applied_delta_emitted_only_where_the_cut_actually_ran():
    """Emit the cut that PRODUCED the call, not the cut that was in force.

    The card (tumor-protein-distribution-by-subtype) declares this field as "the enrichment cutoff
    ACTUALLY APPLIED to produce `subtype_signal` on this row", which makes the null cases load-
    bearing rather than cosmetic. Here the gate is the signal itself, and that is exact rather than
    convenient: this arm's classifier returns None precisely when a median is missing. Both
    directions are asserted, because a test that only checks the populated case cannot distinguish
    "emitted where the cut ran" from "emitted unconditionally".
    """
    records = [
        _projected_row("MSI_H", "measured", 0.9),
        _projected_row("MSS", "measured", 0.1),
        _projected_row("unknown", "measured", None),
    ]
    _subtype_rollup(records, pooled_median=0.1)
    by_id = {r["stratum"]: r for r in records}
    assert by_id["MSI_H"]["subtype_signal"] == "subtype_enriched"
    assert by_id["MSI_H"]["subtype_enrich_log2_delta"] == 0.25
    # a `subtype_uniform` call is still a call the cut produced -> the delta IS attested
    assert by_id["MSS"]["subtype_signal"] == "subtype_uniform"
    assert by_id["MSS"]["subtype_enrich_log2_delta"] == 0.25
    # no median -> no comparison ran -> null, and the signal is null too (no "subtype_uniform" laundering)
    assert by_id["unknown"]["subtype_signal"] is None
    assert by_id["unknown"]["subtype_enrich_log2_delta"] is None
    # …and with no pooled baseline, NOTHING was compared on any row
    fresh = [_projected_row("MSI_H", "measured", 0.9)]
    _subtype_rollup(fresh, pooled_median=None)
    assert fresh[0]["subtype_enrich_log2_delta"] is None


def test_emitted_delta_is_the_constant_the_classifier_reads(monkeypatch):
    """The emitted number must be the one the comparison used — not a coincidentally equal literal.

    Naming `_SUBTYPE_ENRICH_LOG2_DELTA` (behaviour-neutral: 0.25 both before and after) is only worth
    anything if the constant is load-bearing on BOTH sides. Moving it must move the classification
    boundary AND the emitted value together; a copy of the old inline literal left behind at either
    comparison site survives every assertion above but fails here.
    """
    import onc_methods.cptac_protein_distribution.read as R

    monkeypatch.setattr(R, "_SUBTYPE_ENRICH_LOG2_DELTA", 1.0)
    # 0.9 above pooled cleared the real 0.25 cut; under a 1.0 cut it must not
    assert R._classify_subtype_signal(1.0, 0.1) == "subtype_uniform"
    assert R._classify_subtype_signal(1.2, 0.1) == "subtype_enriched"
    recs = [_projected_row("MSI_H", "measured", 1.2)]
    R._subtype_rollup(recs, pooled_median=0.1)
    assert recs[0]["subtype_enrich_log2_delta"] == 1.0


def test_assignment_manifest_stamps_the_shard_the_run_resolved(monkeypatch):
    """A reader-side stamp of the RESOLVED shard, which is what makes staleness auditable.

    `envelope.py::_refine_product_id_staleness` reports staleness as INDETERMINATE for want of
    exactly this: a card may pin several candidate shards, so without the stamp the envelope cannot
    tell WHICH one a given run read. The caller override is asserted separately from the fallback
    because a stamp that always re-derives from INDICATION_TO_CPTAC_ASSIGNMENT_MANIFEST would attest
    the wrong shard on every explicit-manifest call while looking correct on the default path.
    """
    import onc_methods.cptac_protein_distribution.read as R

    monkeypatch.setattr(R, "build_panorama", lambda *a, **k: {"per_subgroup_metrics": []})
    monkeypatch.setattr(R, "read_stratified_protein", lambda *a, **k: {"median_log2_ratio": 0.1})

    default = R.build_protein_subtype_panorama("EPCAM", "COADREAD", subgroups=["MSI_H"])
    assert default["assignment_manifest"] == "cptac-subgroup-assignments-coadread-v1"

    override = R.build_protein_subtype_panorama(
        "EPCAM", "COADREAD", subgroups=["MSI_H"], subgroup_assignments_manifest="cptac-shard-under-test"
    )
    assert override["assignment_manifest"] == "cptac-shard-under-test"

    # the no-shard path carries the key as an explicit null: nothing was resolved, so there is
    # nothing to attest — but the record shape must not vary by which path produced it.
    none_path = R.build_protein_subtype_panorama("EPCAM", "GBM", subgroups=["x"])
    assert "assignment_manifest" in none_path and none_path["assignment_manifest"] is None
