"""Unit test for the presence claim-vector citable atoms (skills/_skills_common/presence_claims.py).
Presence builds its claims MANUALLY (not via ClaimSpec.atom_fn), so this pins that each measured claim
binds its load-bearing card values to {card_id, fields} + entity, and that the key is OMITTED (not
None) when the source card is absent — matching the other axes' atom discipline. Pure; no S3."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.presence_claims import (  # noqa: E402
    presence_claim_vector,
    presence_claim_vector_by_subtype,
)


def _cards():
    return [
        {
            "card_id": "tumor-rna-distribution",
            "summary": {
                "tumor_expression_class": "broadly_detected",
                "control_position_class": "above_negatives_below_positives",
                "control_position": "above 3/4 positive control(s); above 3/5 negative control(s)",
                "allgene_percentile": 52.5,
                "median_log2tpm": 3.97,
                "distribution_pattern": "continuous",
            },
        },
        {
            "card_id": "tumor-rna-vs-adjacent",
            "summary": {
                "expression_call_class": "modest_upregulation",
                "log2_fc": 0.8,
                "q_value": 1e-16,
                "n_tumor": 624,
            },
        },
        {
            "card_id": "tumor-scrna-celltype-expression",
            "summary": {
                "sc_expression_class": "malignant_subset_detected",
                "malignant_detection_fraction": 0.48,
                "malignant_n_donors": 362,
                "caf_vs_malignant_class": "shared_caf_malignant",
            },
        },
        {
            "card_id": "tumor-elevation-breadth",
            "summary": {
                "tumor_elevation_breadth_class": "multi_tumor_elevated",
                "n_cohorts_elevated": 3,
                "n_cohorts_tested": 10,
            },
        },
    ]


def _headline():
    return {
        "bulk_rna_proxy_quality": "rna_positive_proxy_partial",
        "sc_expression_class": "malignant_subset_detected",
        "sc_malignant_detection_fraction": 0.48,
        "sc_n_donor_groups": 362,
        "tumor_elevation_breadth_class": "multi_tumor_elevated",
        "tumor_elevation_n_cohorts_tested": 10,
    }


def test_presence_atoms_present_and_citable_with_cards():
    vec = presence_claim_vector(_headline(), _cards())
    a = vec["A"]["evidence_atom"]
    assert a["cite"]["card_id"] == "tumor-rna-distribution"
    assert a["values"]["median_log2tpm"] == 3.97
    b = vec["B"]["evidence_atom"]
    assert b["cite"]["card_id"] == "tumor-rna-vs-adjacent" and b["values"]["log2_fc"] == 0.8
    assert vec["C"]["evidence_atom"]["values"]["malignant_detection_fraction"] == 0.48
    assert vec["D"]["evidence_atom"]["cite"]["card_id"] == "tumor-elevation-breadth"
    assert vec["D"]["evidence_atom"]["values"]["n_cohorts_elevated"] == 3


def test_presence_atoms_omitted_without_cards():
    # cards=[] → source cards absent → the evidence_atom KEY is omitted (not None), byte-stable
    vec = presence_claim_vector(_headline(), [])
    for ax in ("A", "B", "C", "D"):
        assert "evidence_atom" not in vec[ax], f"{ax} carries an atom with no source card"


def test_homogeneity_unmeasured_not_null_without_scrna():
    # No single-cell card (SCLC / NECTIN4-BRCA-pair scRNA = data_unavailable) → homogeneity must be
    # the STRING sentinel "unmeasured", never null. null fails the evidence_package claim_vector schema
    # (oneOf[string, object]) and aborts the envelope emit for every scRNA-less indication.
    hl = {k: v for k, v in _headline().items() if not k.startswith("sc_")}
    vec = presence_claim_vector(hl, [])
    assert vec["homogeneity"] == "unmeasured"
    assert vec["homogeneity"] is not None
    # a real single-cell homogeneity class still passes through verbatim
    vec2 = presence_claim_vector({**hl, "sc_tce_homogeneity_class": "homogeneous"}, [])
    assert vec2["homogeneity"] == "homogeneous"


def test_claim_d_corroboration_inherits_an_unmeasured_signal():
    # `breadth_class: data_unavailable` is not in claim D's signal map, so the signal is "unmeasured" —
    # and the corroboration must follow it. The two ladders read DIFFERENT card fields (signal <- the
    # breadth CLASS, corroboration <- the n-tested COUNT) and nothing coupled them, so a declined claim
    # used to ship a top-rung tier: measured on the n=504 corpus, 30 pairs emitted (unmeasured, high)
    # off `n_tested = 26`, which is the card's cohort ROSTER size (26 on 502 of 504 pairs), not a
    # per-target measurement. "Tested over 26 cohorts, answer withheld" is not a coverage statement.
    hl = {**_headline(), "tumor_elevation_breadth_class": "data_unavailable", "tumor_elevation_n_cohorts_tested": 26}
    d = presence_claim_vector(hl, [])["D"]
    assert d["signal"] == "unmeasured"
    assert d["corroboration"] == "unmeasured", "a tier for a claim never stated is attached to nothing"
    # the same holds when the count is small enough to have laddered to a LOWER rung — this is the one
    # frozen-atlas row (n_tested=3) that became the lone minority class of an otherwise-constant column
    # and drew a 17.2-sigma one-rung displacement on a claim that was never made.
    hl3 = {**hl, "tumor_elevation_n_cohorts_tested": 3}
    assert presence_claim_vector(hl3, [])["D"]["corroboration"] == "unmeasured"
    # a missing breadth class (key absent entirely) takes the same path
    hl_missing = {k: v for k, v in _headline().items() if k != "tumor_elevation_breadth_class"}
    assert presence_claim_vector(hl_missing, [])["D"]["corroboration"] == "unmeasured"


def test_claim_d_corroboration_still_ladders_when_the_claim_is_stated():
    # NEGATIVE CONTROL — passes before AND after the coupling above. A STATED claim keeps the full
    # n_tested ladder verbatim, so the fix cannot be mistaken for "claim D stopped corroborating":
    # 472 of the 504 corpus pairs sit here and must be byte-identical across the change.
    for n, want in (
        (26, "high"),
        (10, "high"),
        (9, "moderate"),
        (5, "moderate"),
        (4, "low"),
        (1, "low"),
        (0, "unmeasured"),
    ):
        hl = {
            **_headline(),
            "tumor_elevation_breadth_class": "multi_tumor_elevated",
            "tumor_elevation_n_cohorts_tested": n,
        }
        d = presence_claim_vector(hl, [])["D"]
        assert d["signal"] == "moderate", "a stated breadth class must still state its signal"
        assert d["corroboration"] == want, f"n_tested={n} must ladder to {want}, not {d['corroboration']}"
    # and every non-unmeasured signal rung reaches the ladder, not just the one above
    for br, sig in (
        ("broadly_tumor_elevated", "strong"),
        ("multi_tumor_elevated", "moderate"),
        ("single_tumor_elevated", "weak"),
        ("not_tumor_elevated", "absent"),
    ):
        hl = {**_headline(), "tumor_elevation_breadth_class": br, "tumor_elevation_n_cohorts_tested": 26}
        d = presence_claim_vector(hl, [])["D"]
        assert (d["signal"], d["corroboration"]) == (sig, "high"), f"{br} must keep its laddered tier"


def _by_subtype_cards():
    """A tumor-rna-distribution-by-subtype card mirroring CD274/COADREAD: MSI_H/CMS1/CIMP_High enriched,
    MSS uniform — the per-stratum subtype_signal is set, the rollup carries n_subtypes_enriched=3."""
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_stratification_class": "subtype_enriched",
                "subtype_variance_explained": 0.34,
                "subtype_effect_size_class": "large",
                "which_subtypes_separate": {"highest": "CMS1", "lowest": "CMS2"},
                "n_subtypes_measured": 4,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "MSI_H",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 2.51,
                        "n_tumor_samples": 47,
                        "fraction_tumor_above_normal_p95": 0.4,
                    },
                    {
                        "stratum_id": "CMS1",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_enriched",
                        "median_log2tpm": 2.29,
                        "n_tumor_samples": 90,
                        "fraction_tumor_above_normal_p95": 0.35,
                    },
                    {
                        "stratum_id": "MSS",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_uniform",
                        "median_log2tpm": 1.01,
                        "n_tumor_samples": 205,
                        "fraction_tumor_above_normal_p95": 0.1,
                    },
                ],
            },
        }
    ]


def test_enriched_subtype_identities_are_projected_and_ranked():
    # FACET 1: the enriched-stratum IDENTITIES are surfaced (not just the count), ranked by median desc,
    # and top_enriched_subtype is the data-driven pick (distinct from the query-echo spotlight_subtype).
    cv = presence_claim_vector_by_subtype(_by_subtype_cards())
    ids = [e["stratum"] for e in cv["enriched_subtypes"]]
    assert ids == ["MSI_H", "CMS1"], f"enriched identities MSI_H>CMS1 by median, got {ids}"
    assert "MSS" not in ids  # subtype_uniform is not a positive-selection identity
    assert cv["top_enriched_subtype"] == "MSI_H"
    assert cv["enriched_subtypes"][0]["subtype_signal"] == "subtype_enriched"


def test_no_axis_returns_none_and_empty_enrichment_is_a_list():
    assert presence_claim_vector_by_subtype([]) is None
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_stratification_class": "pan_subtype_uniform",
                "n_subtypes_measured": 3,
                "per_subgroup_metrics": [
                    {
                        "stratum_id": "A",
                        "evidence_state": "measured",
                        "subtype_signal": "subtype_uniform",
                        "median_log2tpm": 1.0,
                        "n_tumor_samples": 50,
                    }
                ],
            },
        }
    ]
    cv = presence_claim_vector_by_subtype(cards)
    assert cv["enriched_subtypes"] == [] and cv["top_enriched_subtype"] is None  # uniform → empty, never None list
