"""Unit tests for tractability-small-molecule's claim vector (skills/_skills_common/tractability_claims.py),
the SIXTH concrete over claim_vector_core. Pins the POSITIVE-valence tiers + citable atoms per axis
(POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER). Pure over card summaries — no S3."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.tractability_claims import (  # noqa: E402
    small_molecule_claim_vector, small_molecule_key_signals)


def _cards():
    return [
        {"card_id": "measured-potency-tractability", "summary": {
            "measured_bioactivity_class": "potent_measured_ligand", "chembl_best_pchembl": 8.4,
            "chembl_n_potent_ligands": 37, "best_measured_potency_neglog_m": 8.4}},
        {"card_id": "prism-compound-activity", "summary": {
            "prism_activity_class": "clinical_precedent_only", "n_compounds_targeting": 4,
            "highest_clinical_phase": 4.0}},
        {"card_id": "structure-features-static", "summary": {
            "structural_ligandability_class": "experimental_ligandable", "pdb_coverage_class": "strong",
            "alphafold_confidence_class": "high", "alphafold_plddt_mean": 92.1}},
        {"card_id": "known-drug-tractability", "summary": {
            "known_drug_tractability_class": "approved_drug_tractable", "druggability_tier": "Tclin",
            "has_approved_drug": True, "n_antineoplastic_interactions": 12}},
        {"card_id": "degradation-feasibility", "summary": {
            "degradability_feasibility_class": "ubiquitination_substrate", "e3_substrate_evidence": "curated",
            "n_e3_ligases_literature": 3, "degrader_precedent": "none"}},
    ]


def test_positive_valence_tiers():
    vec = small_molecule_claim_vector({}, _cards())
    assert vec["POTENCY"]["signal"] == "strong"        # potent_measured_ligand
    assert vec["ACTIVITY"]["signal"] == "moderate"     # clinical_precedent_only
    assert vec["STRUCT"]["signal"] == "strong"         # experimental_ligandable
    assert vec["DRUG"]["signal"] == "strong"           # approved_drug_tractable
    assert vec["DEGRADER"]["signal"] == "moderate"     # ubiquitination_substrate


def test_atoms_present_and_citable():
    vec = small_molecule_claim_vector({}, _cards())
    pot = vec["POTENCY"]["evidence_atom"]
    assert pot["cite"]["card_id"] == "measured-potency-tractability"
    assert pot["values"]["chembl_best_pchembl"] == 8.4
    assert vec["STRUCT"]["evidence_atom"]["values"]["alphafold_plddt_mean"] == 92.1
    assert vec["DRUG"]["evidence_atom"]["values"]["druggability_tier"] == "Tclin"


def test_disordered_is_negative_and_gaps_unmeasured():
    vec = small_molecule_claim_vector({}, [
        {"card_id": "structure-features-static", "summary": {"structural_ligandability_class": "disordered_low"}},
        {"card_id": "measured-potency-tractability", "summary": {"measured_bioactivity_class": "data_unavailable"}},
    ])
    assert vec["STRUCT"]["signal"] == "negative"       # disordered → measured-against
    assert vec["POTENCY"]["signal"] == "unmeasured"    # gap


def test_atoms_absent_without_cards():
    vec = small_molecule_claim_vector({}, [])
    for ax in ("POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"):
        assert "evidence_atom" not in vec[ax]


from _skills_common.tractability_claims import small_molecule_key_signals  # noqa: E402


def _discordant_cards():
    # A real chemical hit that is OFF-TARGET: activity + potency light up, but the concordance is
    # discordant, so the resolver lands druggability_snapshot=discordant (a NEGATIVE verdict).
    return [
        {"card_id": "measured-potency-tractability", "summary": {"measured_bioactivity_class": "potent_measured_ligand"}},
        {"card_id": "prism-compound-activity", "summary": {"prism_activity_class": "clinically_active"}},
        {"card_id": "structure-features-static", "summary": {"structural_ligandability_class": "experimental_ligandable"}},
    ]


def test_key_signals_negative_verdict_does_not_read_tractable():
    # Regression: key_signals used to headline "Small-molecule tractable." off the positive-valence
    # claim axes even when the resolved verdict was discordant/intractable/unhit (a NEGATIVE call),
    # contradicting the spine. Mirrors FR #874 / selectivity #862.
    for verdict in ("discordant", "structurally_intractable", "chemically_unhit"):
        h = {"druggability_snapshot": verdict, "prism_crispr_concord": "discordant_off_target_likely"}
        ks = small_molecule_key_signals(h, _discordant_cards())
        assert "tractable." not in ks["headline"].lower(), (verdict, ks["headline"])
    # discordant surfaces the off-target caveat even though the positive claim axes have no weak-critical
    disc = small_molecule_key_signals(
        {"druggability_snapshot": "discordant", "prism_crispr_concord": "discordant_off_target_likely"},
        _discordant_cards())
    assert "off-target" in disc["headline"].lower()
    assert disc["caveat"] and "off-target" in disc["caveat"].lower()


def test_key_signals_positive_verdict_byte_identical():
    # POSITIVE / insufficient paths are unchanged (byte-identical to the prior binary headline).
    pos = small_molecule_key_signals({"druggability_snapshot": "well_covered"}, _cards())
    assert pos["headline"] == "Small-molecule tractable."
    gap = small_molecule_key_signals({"druggability_snapshot": "insufficient"}, [])
    assert gap["headline"] == "Limited small-molecule tractability evidence."
    # a missing snapshot (open-world) still uses the support-driven binary headline
    none = small_molecule_key_signals({}, _cards())
    assert none["headline"] == "Small-molecule tractable."


def test_key_signals_positive_headline_byte_stable():
    """A resolved POSITIVE snapshot keeps the prior binary headline (no regression on the happy path)."""
    ks = small_molecule_key_signals({"druggability_snapshot": "well_covered"}, _cards())
    assert ks["headline"] == "Small-molecule tractable."
    assert ks["supports"]                                    # strong axes surface


def test_key_signals_discordant_does_not_read_tractable():
    """A discordant (off-target, NEGATIVE) verdict must NOT read as "Small-molecule tractable." even
    though the positive-valence ACTIVITY/POTENCY/DRUG axes light up (the compound IS active, just
    off-target). key_signals must track the resolved negative verdict + surface the off-target caveat.
    Regression guard for the FR #874 / selectivity #862 head()-over-claim analog."""
    h = {"druggability_snapshot": "discordant", "prism_crispr_concord": "discordant_off_target_likely"}
    ks = small_molecule_key_signals(h, _cards())
    assert "tractable" not in ks["headline"].lower()
    assert ks["headline"].startswith("Chemical activity is off-target")
    assert ks["caveat"] and "off-target" in ks["caveat"]
    assert "discordant_off_target_likely" in ks["caveat"]


def test_key_signals_intractable_and_unhit_are_negative():
    """structurally_intractable / chemically_unhit also must not read tractable."""
    for tok, frag in (("structurally_intractable", "intractable"),
                      ("chemically_unhit", "No compound found")):
        ks = small_molecule_key_signals({"druggability_snapshot": tok}, _cards())
        assert "tractable" not in ks["headline"].lower() or frag.lower() in ks["headline"].lower()
        assert frag.lower() in ks["headline"].lower()
