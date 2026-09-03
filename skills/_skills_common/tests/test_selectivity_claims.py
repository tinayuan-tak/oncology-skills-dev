"""Unit tests for tumor-selectivity's claim vector (skills/_skills_common/selectivity_claims.py), the
THIRD concrete over claim_vector_core. Pin the WIN/DIST/INT/SAFE tier maps + corroboration combination
(comparator-agreement cap, distribution-overlap, purity/CAF agreement, normal-side agreement) + the
deterministic key-signals read. Pure over a headline dict — no S3, no card reads.

The CEACAM5-shaped headline mirrors the frozen CEACAM5/COADREAD replay fixture
(tumor-selectivity/tests/fixtures/ceacam5_coadread.yaml) so the unit expectations track the replay.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.selectivity_claims import (  # noqa: E402
    selectivity_claim_vector, selectivity_key_signals,
)


def _ceacam5_headline():
    """CEACAM5/COADREAD-shaped: strong distributional + tumor-cell-intrinsic selectivity, but a weak
    (field-effect, discordant) tumor-vs-adjacent window and an origin-tissue normal liability."""
    return {
        "axis_a_selectivity_class": "field_effect_tumor_selective",
        "cells_supporting": 1.0, "cells_ran": 3.0, "discordant": True, "max_abs_log2fc": 2.94,
        "percentile_crossing_class": "strongly_tumor_enriched",
        "fraction_tumor_above_normal_p95": 0.758, "distribution_overlap_tumor_normal": 0.25,
        "sc_tumor_expression_class": "malignant_broadly_detected",
        "sc_malignant_detection_fraction": 0.756, "sc_caf_vs_malignant_class": "caf_low",
        "purity_confound_class": "purity_independent",
        "sc_normal_safety_essential_class": "origin_tissue_liability",
        "sc_normal_expression_class": "HIGH_LIABILITY", "sc_normal_n_cell_types_above_20pct": 26,
    }


def test_ceacam5_claim_vector_tiers():
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    # weak, discordant tumor-vs-adjacent window: comparator disagreement caps corroboration + flags conflict
    assert vec["WIN"]["signal"] == "weak" and vec["WIN"]["corroboration"] == "low"
    assert "DISAGREE" in (vec["WIN"]["conflict"] or "")
    # strong distributional separation (low overlap → high corroboration)
    assert vec["DIST"]["signal"] == "strong" and vec["DIST"]["corroboration"] == "high"
    # tumor-cell-intrinsic (malignant-broad + caf_low + purity-independent → strong/high)
    assert vec["INT"]["signal"] == "strong" and vec["INT"]["corroboration"] == "high"
    # origin-tissue normal liability → weak window signal, high-confidence read
    assert vec["SAFE"]["signal"] == "weak" and vec["SAFE"]["corroboration"] == "high"


def test_ceacam5_key_signals():
    ks = selectivity_key_signals(_ceacam5_headline(), [])
    assert ks["headline"] == "Tumor-selective."
    # only DIST + INT are >= moderate → cited; WIN/SAFE (weak) gated out of supports
    assert len(ks["supports"]) == 2
    # the decision-critical caveat is the normal-tissue window liability (SAFE wins the tie)
    assert ks["caveat"] is not None and "therapeutic-window liability" in ks["caveat"]


def test_strong_clean_selective():
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "strong_tumor_selective", "cells_supporting": 3.0,
              "cells_ran": 3.0, "discordant": False, "sc_normal_safety_essential_class": "none",
              "sc_normal_expression_class": "NOT_EXPRESSED"})
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "strong" and vec["WIN"]["corroboration"] == "high"
    assert vec["SAFE"]["signal"] == "strong"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Tumor-selective."
    assert ks["caveat"] is None   # all critical claims strong/clean


def test_critical_organ_liability_is_negative_window():
    h = _ceacam5_headline()
    h["sc_normal_safety_essential_class"] = "critical_organ_liability"
    vec = selectivity_claim_vector(h, [])
    assert vec["SAFE"]["signal"] == "negative"
    assert "veto" in (vec["SAFE"]["conflict"] or "")
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Selective signal, but a critical-organ normal-tissue liability."


def test_window_veto_floors_safe_negative_even_with_clean_sc_normal():
    """B1-02: a target the therapeutic-window veto KILLED (no window vs the worst critical/full normal —
    the housekeeping GAPDH / TROP2 broadly-normal archetype) must NOT read SAFE='strong' off a clean
    sc-normal side. The window arm floors SAFE at negative and flags the conflict."""
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "strong_tumor_selective", "cells_supporting": 3.0,
              "cells_ran": 3.0, "discordant": False,
              "sc_normal_safety_essential_class": "none",          # CLEAN sc-normal side
              "sc_normal_expression_class": "NOT_EXPRESSED",
              "therapeutic_window_class": "no_therapeutic_window"})  # but the window veto KILLED it
    vec = selectivity_claim_vector(h, [])
    assert vec["SAFE"]["signal"] == "negative"
    assert "window" in (vec["SAFE"]["conflict"] or "")
    # a fired window veto is itself a measured normal-side read → corroboration is not unmeasured
    assert vec["SAFE"]["corroboration"] != "unmeasured"


def test_full_normal_window_veto_also_floors_safe():
    """The pan-normal window arm (full_normal_window_class == no_full_normal_window) floors SAFE too."""
    h = _ceacam5_headline()
    h.update({"sc_normal_safety_essential_class": "none", "sc_normal_expression_class": "NOT_EXPRESSED",
              "full_normal_window_class": "no_full_normal_window"})
    assert selectivity_claim_vector(h, [])["SAFE"]["signal"] == "negative"


def test_clean_window_leaves_safe_strong():
    """A clean therapeutic window must NOT downgrade a clean-sc-normal SAFE axis (no false negative)."""
    h = _ceacam5_headline()
    h.update({"sc_normal_safety_essential_class": "none", "sc_normal_expression_class": "NOT_EXPRESSED",
              "therapeutic_window_class": "clean_window",
              "full_normal_window_class": "clean_full_normal_window"})
    assert selectivity_claim_vector(h, [])["SAFE"]["signal"] == "strong"


def test_microenvironment_confounded_downgrades_and_flags():
    h = _ceacam5_headline()
    h["purity_confound_class"] = "microenvironment_confounded"
    vec = selectivity_claim_vector(h, [])
    # purity contradicts an apparent intrinsic single-cell signal → downgraded + conflict + low corroboration
    assert vec["INT"]["signal"] == "weak"
    assert "microenvironment" in (vec["INT"]["conflict"] or "")
    assert vec["INT"]["corroboration"] == "low"


def test_microenvironment_dominant_is_negative():
    h = _ceacam5_headline()
    h["sc_tumor_expression_class"] = "microenvironment_dominant"
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert "microenvironment-driven" in ks["headline"]


def test_not_selective_case():
    h = {
        "axis_a_selectivity_class": "not_selective", "cells_supporting": 0.0, "cells_ran": 3.0,
        "discordant": False, "percentile_crossing_class": "not_enriched",
        "distribution_overlap_tumor_normal": 0.9,
        "sc_tumor_expression_class": "broadly_low", "purity_confound_class": "purity_independent",
        "sc_normal_safety_essential_class": "none", "sc_normal_expression_class": "NOT_EXPRESSED",
    }
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "absent" and vec["DIST"]["signal"] == "absent"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Not tumor-selective."
    assert ks["supports"] == []


def test_not_selective_with_critical_organ_liability_is_not_selective():
    """REGRESSION (key_signals over-claim): a measured-NEGATIVE target (WIN+DIST absent) that also
    carries a near-universal critical-organ normal liability (SAFE negative) must NOT read
    "Selective signal, but …". The endothelial-marker archetype (PECAM1/VWF in COADREAD): not
    tumor-selective by every selectivity axis, yet expressed in critical normal organs."""
    h = {
        "axis_a_selectivity_class": "not_selective", "cells_supporting": 0.0, "cells_ran": 3.0,
        "discordant": False, "percentile_crossing_class": "not_enriched",
        "distribution_overlap_tumor_normal": 0.9,
        "sc_tumor_expression_class": "microenvironment_dominant",
        "purity_confound_class": "microenvironment_confounded",
        "sc_normal_safety_essential_class": "critical_organ_liability",
        "sc_normal_expression_class": "HIGH_LIABILITY",
    }
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "absent" and vec["DIST"]["signal"] == "absent"
    assert vec["SAFE"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert not ks["headline"].startswith("Selective signal")
    assert ks["headline"].startswith("Not tumor-selective")
    assert "normal-tissue liability" in ks["headline"]
    assert ks["supports"] == []


def test_weak_selectivity_with_liability_does_not_claim_selective():
    """REGRESSION: a discordant / weak-signal target (WIN+DIST weak, below the moderate bar) with a
    critical-organ liability (the KRAS/COADREAD archetype) must not lead with "Selective signal"."""
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "discordant_across_comparators", "cells_supporting": 1.0,
              "discordant": True, "percentile_crossing_class": "minimally_enriched",
              "fraction_tumor_above_normal_p95": 0.19, "distribution_overlap_tumor_normal": 0.7,
              "sc_tumor_expression_class": "malignant_subset_detected",
              "sc_normal_safety_essential_class": "critical_organ_liability"})
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["signal"] == "weak" and vec["DIST"]["signal"] == "weak"
    assert vec["SAFE"]["signal"] == "negative"
    ks = selectivity_key_signals(h, [])
    assert not ks["headline"].startswith("Selective signal")
    assert "normal-tissue liability" in ks["headline"]


def test_selective_with_critical_organ_liability_unchanged():
    """BYTE-STABILITY guard: a genuinely selective target (DIST strong — the CEACAM5 shape) with a
    critical-organ liability KEEPS the prior "Selective signal, but …" wording. Complements
    test_critical_organ_liability_is_negative_window; pins that the fix does not regress selective cases."""
    h = _ceacam5_headline()
    h["sc_normal_safety_essential_class"] = "critical_organ_liability"
    ks = selectivity_key_signals(h, [])
    assert ks["headline"] == "Selective signal, but a critical-organ normal-tissue liability."


def test_win_corroboration_capped_by_single_comparator_family():
    """cells_supporting double-counts cells A (raw) + B (ComBat) as two votes of the same
    tumor-vs-adjacent comparison. A 3/3 support count with comparator_concordance == single_comparator
    (only the adjacent family reached significance; GTEx silent) must NOT read WIN corroboration 'high' —
    it rests on ONE independent comparator family. Cap at 'moderate'. Verdict-inert."""
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "strong_tumor_selective", "cells_supporting": 3.0,
              "cells_ran": 3.0, "discordant": False, "comparator_concordance": "single_comparator"})
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "moderate"


def test_win_corroboration_high_when_families_concordant():
    """A 3/3 support count WITH genuine cross-comparator agreement (both families sig-up) keeps 'high'."""
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "strong_tumor_selective", "cells_supporting": 3.0,
              "cells_ran": 3.0, "discordant": False, "comparator_concordance": "concordant"})
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "high"


def test_win_corroboration_unaffected_when_concordance_absent():
    """Byte-stability: with no comparator_concordance in the headline (older summaries) the cell-count
    tier is unchanged — the CEACAM5 fixture (discordant, 1/3) still reads 'low'."""
    assert selectivity_claim_vector(_ceacam5_headline(), [])["WIN"]["corroboration"] == "low"


def test_field_names_are_corroboration_not_reliability():
    """Post reliability→corroboration rename: the claim dicts carry `corroboration`."""
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    assert "corroboration" in vec["WIN"] and "reliability" not in vec["WIN"]


# ── PROTEIN-layer corroboration quorum for the WIN axis (CPTAC + TPHP tumor-vs-normal MS) ────────────
def _rna_up_concordant_win():
    """A clean RNA window (comparator-concordant, non-discordant) so the WIN corroboration base = high —
    isolating the protein-quorum effect."""
    h = _ceacam5_headline()
    h.update({"axis_a_selectivity_class": "strong_tumor_selective", "cells_supporting": 3.0,
              "cells_ran": 3.0, "discordant": False, "comparator_concordance": "concordant"})
    return h


def test_win_corroboration_capped_when_protein_contradicts():
    """RNA-up but the protein layer is significantly DOWN (rna_protein_discordant): an active
    cross-platform contradiction caps WIN corroboration at low and flags the conflict."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "rna_protein_discordant"
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "low"
    assert "CONTRADICTS" in (vec["WIN"]["conflict"] or "")


def test_win_corroboration_capped_when_two_protein_platforms_silent():
    """Both proteomic platforms (CPTAC + TPHP) fail to confirm the RNA window → a 2-platform
    non-corroboration caps WIN corroboration at low (the EPCAM/COADREAD signature)."""
    h = _rna_up_concordant_win()
    h.update({"rna_protein_tvn_concordance": "protein_not_significant",
              "rna_protein_tvn_concordance_tphp": "protein_not_significant"})
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "low"
    assert "does NOT corroborate" in (vec["WIN"]["conflict"] or "")


def test_win_corroboration_one_silent_protein_caps_moderate():
    """A single non-corroborating platform is a weaker signal than two → caps at moderate, not low."""
    h = _rna_up_concordant_win()
    h["rna_protein_tvn_concordance"] = "protein_not_significant"
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "moderate"


def test_win_corroboration_protein_corroborated_leaves_high():
    """A fully corroborating protein layer imposes NO cap — the clean RNA window stays high."""
    h = _rna_up_concordant_win()
    h.update({"rna_protein_tvn_concordance": "rna_protein_concordant",
              "rna_protein_tvn_concordance_tphp": "rna_protein_concordant"})
    assert selectivity_claim_vector(h, [])["WIN"]["corroboration"] == "high"


def test_win_corroboration_unaffected_when_protein_unmeasured():
    """Byte-stability: no protein reads in the headline (the synthetic CEACAM5 fixture) → no cap, no
    conflict note (the enrichment is a no-op when its inputs are absent)."""
    h = _rna_up_concordant_win()          # no rna_protein_* keys
    vec = selectivity_claim_vector(h, [])
    assert vec["WIN"]["corroboration"] == "high"
    assert "protein" not in (vec["WIN"]["conflict"] or "")


def test_win_evidence_surfaces_field_effect_from_per_cell_log2fc():
    """The adjacent-vs-distant split the collapsed class hides: cell A (adjacent) flat/down + cell C
    (distant GTEx) up → a high-normal-baseline field effect, surfaced in WIN evidence + conflict."""
    h = _ceacam5_headline()
    h["axis_a_selectivity_class"] = "discordant_across_comparators"
    cards = [{"card_id": "tumor-vs-normal-selectivity",
              "summary": {"log2fc_cell_a": -0.33, "log2fc_cell_c": 2.09}}]
    vec = selectivity_claim_vector(h, cards)
    assert "field effect" in (vec["WIN"]["evidence"] or "")
    assert "field effect" in (vec["WIN"]["conflict"] or "")


# ── in-situ SPATIAL region-RNA quorum for the INT axis ───────────────────────────────────────────────
def test_int_corroboration_lifted_by_agreeing_spatial():
    """A single-cell INT read of only moderate corroboration is LIFTED to high when in-situ spatial
    region-RNA independently agrees (tumour_enriched_rna) — single-cell + spatial quorum."""
    h = _ceacam5_headline()
    h.update({"sc_caf_vs_malignant_class": "caf_low", "purity_confound_class": None,   # base = moderate
              "spatial_rna_class": "tumour_enriched_rna"})
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["corroboration"] == "high"
    assert "in-situ spatial" in (vec["INT"]["evidence"] or "")


def test_int_corroboration_capped_by_disagreeing_spatial():
    """A TME-enriched in-situ spatial read caps the INT corroboration and flags the attribution conflict."""
    h = _ceacam5_headline()
    h["spatial_rna_class"] = "tme_enriched_rna"          # base would be high (caf_low + purity_independent)
    vec = selectivity_claim_vector(h, [])
    assert vec["INT"]["corroboration"] == "low"
    assert "spatial" in (vec["INT"]["conflict"] or "")


def test_int_corroboration_unaffected_when_spatial_absent():
    """Byte-stability: no spatial read → INT corroboration is the single-cell base (high for CEACAM5)."""
    assert selectivity_claim_vector(_ceacam5_headline(), [])["INT"]["corroboration"] == "high"


# ── citable evidence atoms (values bound to {card_id, fields} + entity) ──────────────────────────────
def _selectivity_cards():
    """Minimal selectivity source-card summaries mirroring the real COADREAD package fields."""
    return [
        {"card_id": "tumor-vs-normal-selectivity", "summary": {
            "selectivity_class": "discordant_across_comparators", "max_abs_log2fc": 0.6398,
            "cells_supporting": 2, "cells_ran": 3, "comparator_concordance": "discordant"}},
        {"card_id": "tumor-vs-normal-percentile-crossing", "summary": {
            "selectivity_class": "minimally_enriched", "fraction_tumor_above_normal_p95": 0.1928,
            "distribution_overlap_tumor_normal": 0.6926, "n_tumor_samples": 669}},
        {"card_id": "sc-normal-celltype-expression", "summary": {
            "sc_normal_safety_essential_class": "critical_organ_liability",
            "sc_normal_expression_class": "HIGH_LIABILITY", "n_cell_types_above_20pct": 499}},
    ]


def test_selectivity_atoms_present_and_citable_with_cards():
    vec = selectivity_claim_vector(_ceacam5_headline(), _selectivity_cards())
    win = vec["WIN"]["evidence_atom"]
    assert win["cite"]["card_id"] == "tumor-vs-normal-selectivity"
    assert win["values"]["max_abs_log2fc"] == 0.6398           # effect size, citable
    assert vec["DIST"]["evidence_atom"]["values"]["distribution_overlap_tumor_normal"] == 0.6926
    # SAFE atom carries the normal-tissue window liability (the veto instrument's quantitative basis)
    safe = vec["SAFE"]["evidence_atom"]
    assert safe["cite"]["card_id"] == "sc-normal-celltype-expression"
    assert safe["values"]["n_cell_types_above_20pct"] == 499


def test_selectivity_atoms_absent_without_cards():
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    for ax in ("WIN", "DIST", "INT", "SAFE"):
        assert "evidence_atom" not in vec[ax], f"{ax} gained an atom with no source card"
