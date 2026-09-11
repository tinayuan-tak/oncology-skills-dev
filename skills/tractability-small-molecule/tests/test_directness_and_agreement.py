"""Unit tests for the verdict-INERT surfacing flags added with the --literature lane (v3.8.0):
  - _directness_caveat      — the DGIdb/ChEMBL druggability-INFLATION surface (a positive snapshot carried
                              by a retrospective-annotation rung WITHOUT direct-engagement corroboration).
  - _chemical_genetic_agreement — the explicit AGREE / conflict / unmeasured arm over the concordance class.

Both are verdict-INERT: the druggability_snapshot spine is byte-stable (frozen resolver + golden + replay).
These pin the FIRING conditions (so the byte-stability discipline is testable) and the mappings. Pure over
the run.py functions — no S3, no resolver.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run_da")

_ALL_CARD_IDS = [
    "prism-compound-activity",
    "prism-crispr-concordance",
    "dependency-predictability",
    "structure-features-static",
    "known-drug-tractability",
    "degradation-feasibility",
    "gdsc-drug-activity",
    "mutation-hotspot-frequency",  # #993 pt1: read by _minority_allele_coverage_caveat
]


def _cards(**summaries):
    return [{"card_id": cid, "summary": summaries.get(cid, {})} for cid in _ALL_CARD_IDS]


# ── _directness_caveat ────────────────────────────────────────────────────────────────────────────
def test_caveat_fires_on_annotation_driven_positive_without_direct_engagement():
    """The CTNNB1/MYC inflation shape: chemically_active carried by the DGIdb known-drug rung, PRISM only a
    tool compound, concordance thin → the caveat MUST fire and name the annotation-driven / indirect risk."""
    c = tp._directness_caveat(
        "chemically_active",
        "known-drug-approved-antineoplastic-sm-supportive",
        "tool_compound_only",
        "thin_evidence",
        known_drug_class="approved_drug_tractable",
        n_antineoplastic=27,
    )
    assert c is not None
    assert "annotation" in c.lower() and "unconfirmed" in c.lower()
    assert "27 antineoplastic interactions" in c
    # covers the other annotation-driven rungs too
    for rung in (
        "measured-chembl-approved-sm-supportive",
        "known-drug-druggable-category-sm-supportive",
        "measured-potent-ligand-sm-supportive",
        "measured-weak-ligand-sm-supportive",
    ):
        snap = "structurally_ligandable" if "category" in rung or "weak" in rung else "chemically_active"
        snap = "measured_potent_ligand" if rung == "measured-potent-ligand-sm-supportive" else snap
        assert tp._directness_caveat(snap, rung, "tool_compound_only", "thin_evidence") is not None, rung


def test_caveat_none_when_direct_engagement_present():
    """A MEASURED PRISM cellular hit OR chemical-genetic concordance proves direct engagement → no caveat
    (even on an annotation-driven rung)."""
    assert (
        tp._directness_caveat(
            "chemically_active",
            "known-drug-approved-antineoplastic-sm-supportive",
            "clinically_active",
            "thin_evidence",
        )
        is None
    )  # measured PRISM hit
    assert (
        tp._directness_caveat(
            "chemically_active",
            "known-drug-approved-antineoplastic-sm-supportive",
            "tool_compound_only",
            "triangulated_target_engaged",
        )
        is None
    )  # concordance
    assert (
        tp._directness_caveat(
            "chemically_active",
            "known-drug-approved-antineoplastic-sm-supportive",
            "tool_compound_only",
            "crispr_confirmed_engagement",
        )
        is None
    )


def test_caveat_none_on_on_target_and_structural_and_gap_rungs():
    """Byte-stable everywhere the positive does NOT rest on an annotation rung: the on-target concordance
    rung (KRAS well_covered), a real structural rung (FOXA1), and the gap/negative verdicts."""
    assert (
        tp._directness_caveat(
            "well_covered",
            "e7-triangulated-target-engaged-supportive",
            "clinical_precedent_only",
            "triangulated_target_engaged",
        )
        is None
    )
    assert (
        tp._directness_caveat(
            "chemically_confirmed_genetic",
            "e7-crispr-confirmed-supportive-sm",
            "tool_compound_only",
            "crispr_confirmed_engagement",
        )
        is None
    )
    assert (
        tp._directness_caveat(
            "chemically_active", "prism-clinically-active-supportive-sm", "clinically_active", "thin_evidence"
        )
        is None
    )  # PRISM measured rung
    assert tp._directness_caveat("structurally_ligandable", "ligandability-predicted-sm-supportive", None, None) is None
    assert tp._directness_caveat("insufficient", None, None, None) is None
    assert tp._directness_caveat("chemically_unhit", "prism-no-compounds-found-neutral", None, None) is None


# ── _chemical_genetic_agreement ───────────────────────────────────────────────────────────────────
def test_agreement_maps_each_concordance_class():
    cases = {
        "triangulated_target_engaged": "on_target_confirmed",
        "crispr_confirmed_engagement": "on_target_crispr",
        "rnai_confirmed_engagement": "on_target_rnai_only",
        "mixed_engagement": "partial",
        "discordant_off_target_likely": "off_target_conflict",
        "thin_evidence": "unmeasured",
        "data_unavailable": "unmeasured",
    }
    for concord, cls in cases.items():
        arm = tp._chemical_genetic_agreement(concord)
        assert arm and arm["agreement_class"] == cls, (concord, arm)
        assert arm["source_concordance_class"] == concord and arm["note"]


def test_agreement_none_when_unread():
    assert tp._chemical_genetic_agreement(None) is None
    assert tp._chemical_genetic_agreement("") is None


# ── _headline integration + byte-stability ──────────────────────────────────────────────────────────
def test_headline_surfaces_both_flags_on_inflation_shape():
    cards = _cards(
        **{
            "prism-compound-activity": {"prism_activity_class": "tool_compound_only"},
            "prism-crispr-concordance": {"crispr_prism_concordance_class": "thin_evidence"},
            "known-drug-tractability": {
                "known_drug_tractability_class": "approved_drug_tractable",
                "has_approved_drug": True,
                "n_antineoplastic_interactions": 27,
            },
        }
    )
    h = tp._headline(
        cards, fired=[], verdict_pair=("chemically_active", "known-drug-approved-antineoplastic-sm-supportive")
    )
    assert h["directness_caveat"] is not None
    assert h["chemical_genetic_agreement"]["agreement_class"] == "unmeasured"
    assert h["druggability_snapshot"] == "chemically_active"  # spine untouched


def test_headline_no_caveat_on_on_target_shape():
    cards = _cards(
        **{
            "prism-compound-activity": {"prism_activity_class": "clinical_precedent_only"},
            "prism-crispr-concordance": {"crispr_prism_concordance_class": "triangulated_target_engaged"},
        }
    )
    h = tp._headline(cards, fired=[], verdict_pair=("well_covered", "e7-triangulated-target-engaged-supportive"))
    assert h["directness_caveat"] is None
    assert h["chemical_genetic_agreement"]["agreement_class"] == "on_target_confirmed"


def test_headline_flags_none_when_empty():
    """Byte-stable coverage-gap: no annotation rung + no concordance → both flags None."""
    h = tp._headline(_cards(), fired=[], verdict_pair=("insufficient", None))
    assert h["directness_caveat"] is None
    assert h["chemical_genetic_agreement"] is None


# ── _sm_modality_mismatch_caveat (CASE-008) ─────────────────────────────────────────────────────────
def test_modality_mismatch_fires_for_biologics_approved_antigen():
    """DLL3/STEAP1/FOLR1/NECTIN4/CEACAM5: an approved-drug annotation on a biologics-approved antigen
    must fire the modality-mismatch caveat naming the biologic modality."""
    for gene, mod in [("DLL3", "tce"), ("STEAP1", "tce"), ("FOLR1", "adc"), ("NECTIN4", "adc"), ("CEACAM5", "adc_tce")]:
        c = tp._sm_modality_mismatch_caveat(
            {"has_approved_drug": True, "n_antineoplastic_interactions": 3}, target=gene
        )
        assert c is not None, gene
        assert "MODALITY MISMATCH" in c and f"modality={mod}" in c
        assert "3 antineoplastic interactions" in c


def test_modality_mismatch_none_without_approved_drug():
    # biologics-approved target but no approved-drug annotation present → nothing to inflate → None
    assert tp._sm_modality_mismatch_caveat({"has_approved_drug": False}, target="DLL3") is None
    assert tp._sm_modality_mismatch_caveat({}, target="DLL3") is None


def test_modality_mismatch_none_for_small_molecule_target():
    # a bona-fide SM target (not in the biologics crosswalk) never fires, even with an approved drug
    for gene in ("KRAS", "EGFR", "BRAF", "HER3", None):
        assert tp._sm_modality_mismatch_caveat({"has_approved_drug": True}, target=gene) is None


def test_modality_mismatch_is_headline_key_and_faceted():
    # wired into _headline output + carried in the composed facet (verdict-INERT surfacing)
    assert "sm_modality_mismatch_caveat" in tp._SYNTHESIS_FACET_KEYS
