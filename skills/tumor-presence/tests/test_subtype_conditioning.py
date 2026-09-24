"""Phase 3 — subtype as a conditioning axis with MULTIPLICITY-AWARE certainty.

The per-stratum claim vector surfaces a subtype-conditional POSITIVE (e.g. CD274/MSI-H: present in the
MSI-H stratum while the pooled read is low) rather than suppressing it. To keep that honest, per-stratum
certainty takes a 1-tier haircut when several strata are scanned (k >= 5) — the burden moves from
'never mint a positive' to 'discount its certainty'. Verdict-INERT: the function is descriptive and
emits no presence_verdict; the pooled spine is byte-stable by construction.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.presence_claims import presence_claim_vector_by_subtype  # noqa: E402


def _cards(n_subtypes_measured, rows):
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "subtype_variance_explained": 0.21,
                "n_subtypes_measured": n_subtypes_measured,
                "per_subgroup_metrics": rows,
            },
        }
    ]


# CD274-shaped: MSI-H present (strong), MSS low — across a 14-stratum panel (the flattening case).
# Both strata are MEASURED (n=100). `evidence_state: "measured"` is now load-bearing: SK#1518 gates the
# per-stratum A/B signal on it (a non-measured stratum reads `unmeasured`, not a minted differential),
# matching subgroup_derivation.py and the reader, which always emits evidence_state on every row.
_MSIH = {
    "stratum_id": "MSI_H",
    "evidence_state": "measured",
    "median_log2tpm": 6.0,
    "n_tumor_samples": 100,
    "fraction_tumor_above_normal_p95": 0.6,
}
_MSS = {
    "stratum_id": "MSS",
    "evidence_state": "measured",
    "median_log2tpm": 1.5,
    "n_tumor_samples": 100,
    "fraction_tumor_above_normal_p95": 0.05,
}


def test_stratum_positive_is_surfaced():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    assert v["strata"]["MSI_H"]["A"]["signal"] == "strong"  # positive surfaced, not suppressed
    assert v["strata"]["MSS"]["A"]["signal"] == "weak"


def test_certainty_is_multiplicity_discounted():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    # base corroboration high (n=100) → moderate under a 14-stratum multiple-testing surface
    a = v["strata"]["MSI_H"]["A"]
    assert a["corroboration"] == "moderate"
    assert "high→moderate" in a["evidence"] and "of 14 strata" in a["evidence"]
    assert v["multiplicity_strata_tested"] == 14


def test_no_haircut_when_few_strata():
    v = presence_claim_vector_by_subtype(_cards(3, [_MSIH, _MSS]))
    assert v["strata"]["MSI_H"]["A"]["corroboration"] == "high"  # k<5 → no discount


def test_k_falls_back_to_row_count():
    cards = _cards(None, [_MSIH, _MSS])
    cards[0]["summary"].pop("n_subtypes_measured", None)
    v = presence_claim_vector_by_subtype(cards)
    assert v["multiplicity_strata_tested"] == 2  # counted from rows
    assert v["strata"]["MSI_H"]["A"]["corroboration"] == "high"  # k=2 < 5 → no discount


def test_verdict_inert_no_spine_key():
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    assert "presence_verdict" not in v and "driving_rule_id" not in v


# ── Stage 5: the PROTEIN arm is filled per-stratum (retires "protein stays indication-grain") ─────


def _cards_with_protein(rna_rows, protein_rows):
    """RNA arm (keys stratum as `stratum_id`) + CPTAC by-subtype protein arm (keys as `stratum`)."""
    return [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_available": True,
                "n_subtypes_measured": len(rna_rows),
                "per_subgroup_metrics": rna_rows,
            },
        },
        {
            "card_id": "tumor-protein-distribution-by-subtype",
            "summary": {"subtype_axis_available": True, "per_subgroup_metrics": protein_rows},
        },
    ]


# CPTAC by-subtype rows: MSS measured (elevated), MSI_H NOT measured (must omit the protein leg).
_PR_MSS = {
    "stratum": "MSS",
    "class": "protein_elevated",
    "evidence_state": "measured",
    "median_log2_ratio": 1.2,
    "detectable_fraction": 0.9,
    "subgroup_n": 40,
}
_PR_MSIH_UNMEASURED = {"stratum": "MSI_H", "class": "protein_neutral", "evidence_state": "unevaluable", "subgroup_n": 8}


def test_protein_leg_filled_where_measured():
    v = presence_claim_vector_by_subtype(_cards_with_protein([_MSIH, _MSS], [_PR_MSS, _PR_MSIH_UNMEASURED]))
    assert v["protein_strata_measured"] == 1  # only MSS is a measured protein stratum
    mss = v["strata"]["MSS"]["protein"]
    assert mss["signal"] == "elevated"  # from class protein_elevated
    assert "detectable in 90%" in mss["evidence"] and "log2 T/N 1.20" in mss["evidence"]
    assert mss["corroboration"] == "moderate"  # n=40 → moderate base; k_protein=1 < 5 → no haircut
    # MSI_H is not a MEASURED protein stratum → the protein leg is omitted, not faked
    assert "protein" not in v["strata"]["MSI_H"]


def test_protein_leg_omitted_when_no_protein_card():
    """No protein by-subtype card → protein_strata_measured 0 and no protein leg anywhere (the arm is
    absent, not invented)."""
    v = presence_claim_vector_by_subtype(_cards(14, [_MSIH, _MSS]))
    assert v["protein_strata_measured"] == 0
    assert all("protein" not in st for st in v["strata"].values())


def test_protein_leg_multiplicity_over_k_protein():
    """The protein leg's certainty haircut runs over the PROTEIN arm's own k (measured protein strata),
    not the RNA k — 5 measured protein strata (k_protein=5) haircut a high-n leg to moderate."""
    strata_ids = ["MSS", "MSI_H", "CMS1", "CMS2", "CMS3"]
    rna = [{"stratum_id": s, "median_log2tpm": 6.0, "n_tumor_samples": 100} for s in strata_ids]
    protein = [
        {
            "stratum": s,
            "class": "protein_elevated",
            "evidence_state": "measured",
            "median_log2_ratio": 1.0,
            "detectable_fraction": 0.9,
            "subgroup_n": 120,
        }
        for s in strata_ids
    ]
    v = presence_claim_vector_by_subtype(_cards_with_protein(rna, protein))
    assert v["protein_strata_measured"] == 5
    # n=120 → high base; k_protein=5 → 1-tier haircut → moderate
    assert v["strata"]["MSS"]["protein"]["corroboration"] == "moderate"
