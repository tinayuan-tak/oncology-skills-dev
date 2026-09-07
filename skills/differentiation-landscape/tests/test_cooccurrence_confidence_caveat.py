"""CONSOLIDATED statistical-vs-biological co-mutation confidence caveat + provenance (VERDICT-INERT).

The co-mutation analog of mechanism's actionable-MoA and tumor-presence's presence_confirmation inflation
surface. A STATISTICAL co-mutation / mutual-exclusivity association OVER-CALLS a biological / patient-
selection relationship: the panel-intersect Fisher scan carries no TMB / MSI / molecular-subtype covariate,
so a q-significant pair can be a mutation-burden (MSI-H / hypermutation) passenger co-occurrence, a
lineage/subtype restriction, a near-universal-driver marginal-frequency artifact, or a tiny-effect /
panel-ineligible pair rather than a biological interaction.

Tiers (precedence high→low): (i) cooccurrence_tmb_or_lineage_confounded (curated; BRAF/COADREAD MSI-H) >
(iii) MILDER biologically_established_pattern false-demote guard (curated; KRAS/NRAS MAPK exclusivity) >
(ii) significant_but_near_universal / significant_but_low_effect_or_panel_ineligible (near-universal curated
+ DATA-derived panel-eligibility / effect size) > None (ns / data_unavailable → byte-stable negative path).

VERDICT-INERT: the caveat gates on already-emitted headline fields, is never read by the differentiation
resolver, and returns None on the non-positive path so the differentiation_verdict spine + the KRAS/FBXW7
replay fixtures + the golden-oracle resolver are byte-identical.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent


# ── the SHARP TMB/lineage-confound tier (the BRAF/COADREAD driver) ────────────────────────────────
def test_tmb_confounded_driver_fires_sharp_on_cooccurring_component():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    cav = m._cooccurrence_confidence_caveat(hl, target="BRAF", indication="COADREAD")
    assert cav and cav["reason"] == "cooccurrence_tmb_or_lineage_confounded"
    assert cav["tier"] == "sharp" and cav["false_demote_guarded"] is False
    # names the surviving real mutual-exclusivity nuance when a mutex driver is present
    assert "MAPK" in cav["detail"] and "MSI" in cav["detail"]


def test_tmb_confound_requires_a_cooccurring_component():
    """A curated-confounded target with ONLY a mutual-exclusivity component (no co-occurring driver) does
    NOT fire the confound tier — the confound is about the co-occurrence HUB, not the exclusivity."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "strong_mutually_exclusive", "has_cooccurring_driver": False,
          "has_mutually_exclusive_driver": True}
    cav = m._cooccurrence_confidence_caveat(hl, target="BRAF", indication="COADREAD")
    assert cav is None or cav["reason"] != "cooccurrence_tmb_or_lineage_confounded"


# ── the MILDER biologically-established FALSE-DEMOTE guard (KRAS/NRAS-class canonical MAPK exclusivity) ─
def test_biologically_established_guard_spares_kras():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    cav = m._cooccurrence_confidence_caveat(hl, target="KRAS", indication="COADREAD")
    assert cav and cav["reason"] == "biologically_established_pattern"
    assert cav["tier"] == "milder" and cav["false_demote_guarded"] is True


def test_established_guard_outranks_data_cautions_even_on_modest_or_panel_absent():
    """The canonical-relationship guard must OUTRANK the low-effect / panel-ineligible data cautions — a
    KRAS/NRAS-class pair is never mislabelled significant-but-uninformative."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "modest_mutually_exclusive",
          "n_pairs_panel_intersect_eligible": 0, "n_pairs_per_source_only": 4000}
    cav = m._cooccurrence_confidence_caveat(hl, target="NRAS", indication="COADREAD")
    assert cav and cav["reason"] == "biologically_established_pattern" and cav["false_demote_guarded"] is True


def test_confound_outranks_established_on_the_driver():
    """When a target is in BOTH the confound set (co-occurrence hub) — precedence is confound (i) > guard
    (iii). (BRAF is only in the confound set here; this pins the ordering explicitly.)"""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    assert m._cooccurrence_confidence_caveat(hl, "BRAF", "COADREAD")["reason"] == "cooccurrence_tmb_or_lineage_confounded"


# ── the SHARP significance≠actionability tier (near-universal / low-effect / panel-ineligible) ────────
def test_near_universal_driver_fires_significance_ne_actionability():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "strong_mutually_exclusive", "has_mutually_exclusive_driver": True}
    cav = m._cooccurrence_confidence_caveat(hl, target="TP53", indication="COADREAD")
    assert cav and cav["reason"] == "significant_but_near_universal" and cav["tier"] == "sharp"


def test_panel_absent_fires_low_effect_or_panel_ineligible():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "strong_cooccurring", "has_cooccurring_driver": True,
          "n_pairs_panel_intersect_eligible": 0, "n_pairs_per_source_only": 3961}
    cav = m._cooccurrence_confidence_caveat(hl, target="PCLO", indication="COADREAD")
    assert cav and cav["reason"] == "significant_but_low_effect_or_panel_ineligible"


def test_modest_uncurated_fires_low_effect():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "modest_cooccurring",
          "n_pairs_panel_intersect_eligible": 50, "n_pairs_per_source_only": 10}
    cav = m._cooccurrence_confidence_caveat(hl, target="FOO", indication="COADREAD")
    assert cav and cav["reason"] == "significant_but_low_effect_or_panel_ineligible"


# ── the None / byte-stable negative path ─────────────────────────────────────────────────────────
def test_none_on_negative_and_honest_positive_paths():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    for cls in ("ns", "data_unavailable", "insufficient", None):
        assert m._cooccurrence_confidence_caveat({"cooccurrence_class": cls}, "X", "COADREAD") is None
    # a STRONG, panel-eligible, non-confounded, non-near-universal, uncurated pattern → no caveat
    hl = {"cooccurrence_class": "strong_cooccurring", "has_cooccurring_driver": True,
          "n_pairs_panel_intersect_eligible": 80, "n_pairs_per_source_only": 10}
    assert m._cooccurrence_confidence_caveat(hl, "FOO", "LUAD") is None


def test_indication_alias_coad_read_map_to_coadread():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True}
    assert m._cooccurrence_confidence_caveat(hl, "BRAF", "COAD")["reason"] == "cooccurrence_tmb_or_lineage_confounded"
    assert m._cooccurrence_confidence_caveat(hl, "KRAS", "READ")["reason"] == "biologically_established_pattern"


# ── provenance quorum summary ────────────────────────────────────────────────────────────────────
def test_provenance_none_on_negative_and_populated_on_positive():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    assert m._cooccurrence_provenance({"cooccurrence_class": "ns"}, "X", "COADREAD") is None
    hl = {
        "cooccurrence_class": "both_patterns_present", "cooccurrence_class_prefloor": "both_patterns_present",
        "n_significant_cooccurring": 1029, "n_significant_mutually_exclusive": 17,
        "n_pairs_panel_intersect_eligible": 1219, "n_pairs_per_source_only": 3138,
        "top_cooccurring": [{"partner_gene_symbol": "ERBB4", "log2_odds_ratio": 1.69, "bh_q_value": 0.0,
                             "source": "genie_v19", "pooled_eligible": True}],
        "top_mutually_exclusive": [{"partner_gene_symbol": "KRAS", "log2_odds_ratio": -3.0, "bh_q_value": 0.0,
                                    "source": "genie_v19", "pooled_eligible": True}],
    }
    prov = m._cooccurrence_provenance(hl, "BRAF", "COADREAD")
    assert prov["tmb_or_subtype_confounder_flag"] is True
    # BRAF ∈ the pan-cancer MAPK-exclusivity gene-set → established_flag True too (its KRAS/NRAS exclusivity is
    # real); the CAVEAT still resolves to confounded because the (target,indication) confound OUTRANKS the guard.
    assert prov["biologically_established_flag"] is True and prov["near_universal_flag"] is False
    assert m._cooccurrence_confidence_caveat(hl, "BRAF", "COADREAD")["reason"] == "cooccurrence_tmb_or_lineage_confounded"
    assert prov["panel_ineligible_exceeds_eligible"] is True
    assert prov["best_cooccurring"]["partner_gene_symbol"] == "ERBB4"
    assert prov["best_mutually_exclusive"]["partner_gene_symbol"] == "KRAS"
    assert prov["sources_present"] == ["genie_v19"]


def test_field_absent_safe():
    """Empty / partial headline must not raise (verdict-inert projection is best-effort)."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    assert m._cooccurrence_confidence_caveat({}, None, None) is None
    assert m._cooccurrence_provenance({}, None, None) is None
    assert m._clonality_caveat({}) is None


# ── clonality caveat: cohort-level ≠ same-cell / clonal (the (c) sub-inflation, #1037) ─────────────
def test_clonality_caveat_fires_on_cooccurring_path():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    for hl in (
        {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True},
        {"cooccurrence_class": "strong_cooccurring", "has_cooccurring_driver": True},
        {"cooccurrence_class": "modest_cooccurring"},          # class alone carries the co-occurring component
    ):
        cav = m._clonality_caveat(hl)
        assert cav and cav["reason"] == "cohort_not_same_cell_clonal"
        assert cav["resolves_clonality"] is False
        assert "PMID 22397650" in cav["detail"] and "subclon" in cav["detail"].lower()


def test_clonality_caveat_none_on_exclusivity_only_and_negative_paths():
    """A pure mutual-exclusivity (no co-occurring component) and the ns/data_unavailable path → None
    (byte-stable). Clonality is a co-OCCURRENCE question; an exclusivity is an ABSENCE of co-mutation."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    assert m._clonality_caveat({"cooccurrence_class": "strong_mutually_exclusive",
                                "has_cooccurring_driver": False, "has_mutually_exclusive_driver": True}) is None
    for cls in ("ns", "data_unavailable", "insufficient", None):
        assert m._clonality_caveat({"cooccurrence_class": cls}) is None


def test_clonality_caveat_is_target_indication_independent():
    """Unlike the confound/established/near-universal tiers, the clonality caveat has NO curated crosswalk —
    it applies to EVERY pooled co-occurrence (incl. the KRAS false-demote-guarded pair)."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True}
    assert m._clonality_caveat(hl)["reason"] == "cohort_not_same_cell_clonal"


# ── CROSS-INDICATION generalization (v1.10.0): the MAPK-exclusivity guard + TP53 near-universal are PAN-CANCER
#    gene-level, so the canonical signals do not vanish outside COADREAD. The TMB/lineage confound stays
#    (target,indication)-specific and OUTRANKS the pan-cancer guard. ────────────────────────────────────────
def test_mapk_exclusivity_guard_is_pan_cancer_gene_level():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    # KRAS/NRAS/BRAF are spared as biologically-established in ANY indication (not just COADREAD)
    for t, ind in [("BRAF", "SKCM"), ("KRAS", "LUAD"), ("KRAS", "PAAD"), ("NRAS", "SKCM"), ("HRAS", "HNSC")]:
        cav = m._cooccurrence_confidence_caveat(hl, target=t, indication=ind)
        assert cav and cav["reason"] == "biologically_established_pattern" and cav["false_demote_guarded"] is True, \
            f"{t}/{ind} expected biologically_established_pattern, got {cav}"


def test_braf_coadread_confound_outranks_the_pan_cancer_mapk_guard():
    """BRAF ∈ the pan-cancer MAPK gene-set, but BRAF/COADREAD is still the TMB-confounded co-occurrence hub —
    the (target,indication) confound OUTRANKS the gene-level established guard."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    assert m._cooccurrence_confidence_caveat(hl, "BRAF", "COADREAD")["reason"] == "cooccurrence_tmb_or_lineage_confounded"
    # …but BRAF outside CRC is spared (not MSI-confounded there)
    assert m._cooccurrence_confidence_caveat(hl, "BRAF", "SKCM")["reason"] == "biologically_established_pattern"


def test_tp53_near_universal_is_pan_cancer_gene_level():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True}
    for ind in ["BRCA", "LUAD", "LUSC", "OV", "HNSC", "COADREAD"]:
        cav = m._cooccurrence_confidence_caveat(hl, target="TP53", indication=ind)
        assert cav and cav["reason"] == "significant_but_near_universal", f"TP53/{ind} got {cav}"


def test_nsclc_rtk_driver_exclusivity_explicit_rows():
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    for ind in ["LUAD", "LUSC", "NSCLC"]:
        assert m._cooccurrence_confidence_caveat(hl, "EGFR", ind)["reason"] == "biologically_established_pattern"
    # EGFR outside NSCLC is NOT auto-established (no gene-level EGFR rule) → falls to a data tier or None
    assert (m._cooccurrence_confidence_caveat(hl, "EGFR", "GBM") or {}).get("reason") != "biologically_established_pattern"


def test_idh1_gbm_lineage_confound_arm():
    """IDH1/GBM exercises the LINEAGE arm of the confound tier (IDH-mutant glioma is a distinct WHO-2021
    lineage) — the analog of the BRAF/COADREAD TMB arm."""
    m = load_run_py(SKILL_DIR, "_diff_run_caveat_helpers")
    hl = {"cooccurrence_class": "both_patterns_present", "has_cooccurring_driver": True,
          "has_mutually_exclusive_driver": True}
    cav = m._cooccurrence_confidence_caveat(hl, "IDH1", "GBM")
    assert cav and cav["reason"] == "cooccurrence_tmb_or_lineage_confounded"
    assert "LINEAGE" in cav["detail"] or "lineage" in cav["detail"]
    # IDH1 outside GBM is not auto-confounded
    assert (m._cooccurrence_confidence_caveat(hl, "IDH1", "AML") or {}).get("reason") != "cooccurrence_tmb_or_lineage_confounded"


# ── the TEMPORAL-context / acquired-bypass caveat (CASE-007; MET/LUAD) ─────────────────────────────
def _met_hl(cls="strong_cooccurring", partner="EGFR"):
    return {"cooccurrence_class": cls, "has_cooccurring_driver": True,
            "top_cooccurring": [{"partner_gene_symbol": partner, "log2_odds_ratio": 1.4, "bh_q_value": 1e-4}]}


def test_temporal_caveat_fires_for_met_luad_with_tki_partner():
    m = load_run_py(SKILL_DIR, "_diff_temporal_helpers")
    cav = m._cooccurrence_temporal_context_caveat(_met_hl(partner="EGFR"), target="MET", indication="LUAD")
    assert cav and cav["reason"] == "cooccurrence_acquired_bypass_temporal_context"
    assert cav["tier"] == "sharp" and cav["false_demote_guarded"] is False
    assert cav["tki_partners"] == ["EGFR"]
    assert "bypass" in cav["detail"].lower() and "17463250" in cav["detail"]


def test_temporal_caveat_indication_alias_coad_read():
    m = load_run_py(SKILL_DIR, "_diff_temporal_helpers")
    # MET is curated for LUAD/NSCLC only — COADREAD must NOT fire
    assert m._cooccurrence_temporal_context_caveat(_met_hl(), target="MET", indication="COADREAD") is None


def test_temporal_caveat_none_without_tki_partner():
    m = load_run_py(SKILL_DIR, "_diff_temporal_helpers")
    hl = _met_hl(partner="FBXW7")   # co-occurs, but not with a first-line-TKI driver → not the tell
    assert m._cooccurrence_temporal_context_caveat(hl, target="MET", indication="LUAD") is None


def test_temporal_caveat_none_outside_curated_set():
    m = load_run_py(SKILL_DIR, "_diff_temporal_helpers")
    assert m._cooccurrence_temporal_context_caveat(_met_hl(), target="KRAS", indication="LUAD") is None


def test_temporal_caveat_none_on_negative_and_absent_paths():
    m = load_run_py(SKILL_DIR, "_diff_temporal_helpers")
    # ns / data_unavailable → byte-stable None
    assert m._cooccurrence_temporal_context_caveat(
        {"cooccurrence_class": "ns"}, target="MET", indication="LUAD") is None
    # a clean mutual-exclusivity read (no co-occurring component) → None
    assert m._cooccurrence_temporal_context_caveat(
        {"cooccurrence_class": "strong_mutually_exclusive"}, target="MET", indication="LUAD") is None
    # field-absent-safe
    assert m._cooccurrence_temporal_context_caveat({}, target="MET", indication="LUAD") is None
