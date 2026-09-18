"""Unit tests for the subtype-stratified CPTAC protein reader (pure logic + monkeypatched reader)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cptac_protein_distribution.read import (  # noqa: E402
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
    assert _classify_subtype_signal(1.0, 0.0) == "enriched"
    assert _classify_subtype_signal(-1.0, 0.0) == "depleted"
    assert _classify_subtype_signal(0.1, 0.0) == "uniform"
    assert _classify_subtype_signal(None, 0.0) is None


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
    import methods.cptac_protein_deg.read as cpr

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
    import methods.cptac_protein_deg.read as cpr

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
    import methods.cptac_protein_deg.read as cpr

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
    import methods.cptac_protein_deg.read as cpr

    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    call = lambda flag: read_stratified_protein(  # noqa: E731
        "EPCAM", "COADREAD", cohort="COAD", _sample_id_filter=set(), _stratum_evaluated=flag
    )["evidence_state"]
    assert call(False) == "unevaluable"
    assert call(True) == "absent"
    assert call(None) == "absent"  # historical default preserved
