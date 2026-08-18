"""Unit tests for functional-requirement's claim vector (skills/_skills_common/dependency_claims.py),
the SECOND concrete over claim_vector_core. Pin the DEP/SEL/COND/CHEM tier mappings + the corroboration
combination (RNAi corroboration, Broad↔Sanger lift, omics-predictability, conflict caps) + the
deterministic key-signals read. Pure over a headline dict — no S3, no card reads.

The strong-case headline mirrors the frozen KRAS/COADREAD replay fixture
(functional-requirement/tests/fixtures/kras_coadread.yaml) so the unit-level expectations track the
integration replay.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]        # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.dependency_claims import (  # noqa: E402
    dependency_claim_vector, dependency_key_signals,
)


def _kras_headline():
    """KRAS/COADREAD-shaped: a selective, cross-consortium-corroborated, chemically-confirmed
    dependency with no curated SL partner (a GAP, not a negative)."""
    return {
        "crispr_call": "strongly_selective",
        "rnai_call": "strongly_selective",
        "concordance_call": "moderately_concordant_non_dependent",
        "lineage_selectivity": "lineage_selective",
        "n_lineages_evaluated": 26,
        "cross_consortium_class": "concordant_dependent",
        "predictability_class": "own_omics_driven",
        "partner_conditional_class": "no_partner_mapped",
        "partner_stratification_q": None,
        "n_partner_deficient": None,
        "prism_concordance_class": "triangulated_target_engaged",
        "n_compounds_evaluated": 21,
    }


def test_kras_claim_vector_tiers():
    vec = dependency_claim_vector(_kras_headline(), [])
    assert vec["DEP"]["signal"] == "strong"
    # base moderate (moderately_concordant_non_dependent) + RNAi corroboration + cross-consortium
    # replication + own-omics predictability → high
    assert vec["DEP"]["corroboration"] == "high"
    assert vec["DEP"]["conflict"] is None
    assert vec["SEL"] == {"signal": "strong", "corroboration": "high",
                          "evidence": vec["SEL"]["evidence"], "conflict": None,
                          "informs": vec["SEL"]["informs"]}
    assert vec["CHEM"]["signal"] == "strong" and vec["CHEM"]["corroboration"] == "high"


def test_no_partner_mapped_is_gap_not_absent():
    """COND on a target with no curated partner must be `unmeasured` (a coverage gap), NEVER `absent`
    (which would read as 'measured, not synthetic-lethal')."""
    vec = dependency_claim_vector(_kras_headline(), [])
    assert vec["COND"]["signal"] == "unmeasured"
    assert vec["COND"]["corroboration"] == "unmeasured"
    assert "GAP" in vec["COND"]["evidence"]


def test_kras_key_signals_deterministic():
    ks = dependency_key_signals(_kras_headline(), [])
    assert ks["headline"] == "Selective genetic dependency, chemically confirmed."
    # DEP, SEL, CHEM all >= moderate → all three cited; COND (gap) is gated out; top-3 cap holds
    assert len(ks["supports"]) == 3
    assert any("independently corroborated across consortia" in s for s in ks["supports"])
    # all critical claims strong → no caveat
    assert ks["caveat"] is None


def test_pan_essential_flags_broad_tox_conflict():
    h = _kras_headline()
    h["crispr_call"] = "common_essential"
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "strong"                     # strong MAGNITUDE
    assert "pan-essential" in (vec["DEP"]["conflict"] or "")    # …but flagged as a broad-tox liability


def test_rnai_disagreement_flags_conflict_and_caps_corroboration():
    h = _kras_headline()
    h["rnai_call"] = "non_dependent"
    h["cross_consortium_class"] = "single_consortium_only"      # remove the consortium lift
    h["predictability_class"] = "unpredictable"                 # remove the predictability lift
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "strong"
    assert "RNAi" in (vec["DEP"]["conflict"] or "")
    assert vec["DEP"]["corroboration"] in ("moderate", "low")     # capped, not high


def test_non_dependent_case():
    h = {
        "crispr_call": "non_dependent",
        "rnai_call": "non_dependent",
        "concordance_call": "strongly_concordant_non_dependent",
        "lineage_selectivity": "no_lineage_enrichment",
        "n_lineages_evaluated": 26,
        "cross_consortium_class": "concordant_non_dependent",
        "predictability_class": "unpredictable",
        "partner_conditional_class": "not_partner_stratified",
        "prism_concordance_class": "data_unavailable",
    }
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "absent"
    assert vec["SEL"]["signal"] == "absent"
    assert vec["CHEM"]["signal"] == "unmeasured"
    ks = dependency_key_signals(h, [])
    assert ks["headline"] == "Not a genetic dependency in the pooled panel."
    assert ks["supports"] == []                                 # nothing >= moderate
    assert ks["caveat"] is not None                             # weakest measured critical fires


def test_underpowered_is_gap_not_absent():
    h = _kras_headline()
    h["crispr_call"] = "non_dependent_underpowered"
    vec = dependency_claim_vector(h, [])
    assert vec["DEP"]["signal"] == "unmeasured"                 # admissibility gap, not a trusted floor


def test_prism_off_target_is_negative_with_conflict():
    h = _kras_headline()
    h["prism_concordance_class"] = "discordant_off_target_likely"
    vec = dependency_claim_vector(h, [])
    assert vec["CHEM"]["signal"] == "negative"
    assert "off-target" in (vec["CHEM"]["conflict"] or "")


def test_partner_conditional_strong_signal():
    h = _kras_headline()
    h["partner_conditional_class"] = "partner_conditional_moderately_dependent"
    h["n_partner_deficient"] = 40
    h["partner_stratification_q"] = 0.01
    vec = dependency_claim_vector(h, [])
    assert vec["COND"]["signal"] == "moderate"
    assert vec["COND"]["corroboration"] == "high"                 # q<0.1 AND n>=15
