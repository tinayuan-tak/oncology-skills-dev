"""cis-feature-coherence — VERDICT-INERT confidence-surface unit tests (v1.4.0).

Pins the statistical-vs-causal cis-coherence CONFIDENCE surface added in v1.4.0:
  * cis_coherence_confidence_caveat — 3-tier (validated-guard / amplicon-passenger-or-CIMP / statistical-
    unconfirmed), precedence guard-first, and the byte-stable None on non-coherent verdicts.
  * causal_attribution_caveat / context_generalization_caveat — the always-informative correlation≠causation
    + bulk/patient generalization caveats (fire on the relevant coupled leg; None otherwise).
  * cis_coherence_provenance — the quorum summary (None on insufficient).
None of these read the resolver — they gate on already-emitted headline fields, so the verdict spine
(cis_coherence_verdict + driving_rule_id + resolver golden + replay) is untouched. Hermetic (no S3/network).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_run = load_run_py(Path(__file__).resolve().parent.parent, "cis_run")
(
    _cis_coherence_confidence_caveat,
    _causal_attribution_caveat,
    _context_generalization_caveat,
    _cis_coherence_provenance,
) = (
    _run._cis_coherence_confidence_caveat,
    _run._causal_attribution_caveat,
    _run._context_generalization_caveat,
    _run._cis_coherence_provenance,
)


# ── cis_coherence_confidence_caveat ─────────────────────────────────────────────────────────────
def test_confidence_none_on_non_coherent_verdict():
    """Uncoupled / inert / insufficient carry no coherent-cis over-call → None (byte-stable)."""
    for v in (
        "expressed_cis_coupled_inert",
        "dependency_without_cis_dosage",
        "cis_uncoupled_no_dependency",
        "insufficient_cis_coherence",
        None,
    ):
        assert _cis_coherence_confidence_caveat({"cis_coherence_verdict": v}, target="FOO", indication="BRCA") is None


def test_confidence_validated_guard_spares_canonical_driver_even_if_protein_buffered():
    """ERBB2 reads coherent_cis_driver with a BUFFERED protein slope (rank-noise) → guard, not demoted."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "prot_dosage_uncoupled",
        "mrna_vs_protein_dosage_slope_ratio": 0.19,
    }
    c = _cis_coherence_confidence_caveat(hl, target="ERBB2", indication="BRCA")
    assert c["reason"] == "validated_cis_driver_or_silencing"
    assert c["false_demote_guarded"] is True


def test_confidence_validated_guard_spares_canonical_silencing():
    hl = {"cis_coherence_verdict": "coherent_epigenetic_silencing"}
    for gene in ("MLH1", "MGMT", "CDKN2A"):
        c = _cis_coherence_confidence_caveat(hl, target=gene, indication="COADREAD")
        assert c["reason"] == "validated_cis_driver_or_silencing" and c["false_demote_guarded"] is True


def test_confidence_amplicon_passenger_buffered_protein():
    """A NON-guarded coherent_cis_driver with a buffered protein slope = co-amplified passenger (STARD3)."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "prot_dosage_uncoupled",
        "mrna_vs_protein_dosage_slope_ratio": 0.75,
    }
    c = _cis_coherence_confidence_caveat(hl, target="STARD3", indication="BRCA")
    assert c["reason"] == "amplicon_passenger_or_lineage_confounded"
    assert c["false_demote_guarded"] is False


def test_confidence_amplicon_passenger_low_ratio_even_if_class_coupled():
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "prot_dosage_coupled_moderate",
        "mrna_vs_protein_dosage_slope_ratio": 0.3,
    }
    c = _cis_coherence_confidence_caveat(hl, target="GRB7", indication="BRCA")
    assert c["reason"] == "amplicon_passenger_or_lineage_confounded"


def test_confidence_cimp_lineage_confound_for_nonguarded_silencing():
    """A non-guarded silencing gene in a CIMP lineage = candidate CIMP passenger."""
    hl = {"cis_coherence_verdict": "coherent_epigenetic_silencing"}
    c = _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="COADREAD")
    assert c["reason"] == "amplicon_passenger_or_lineage_confounded"
    assert c["false_demote_guarded"] is False


def test_confidence_statistical_unconfirmed_when_protein_and_patient_absent():
    """Coherent driver, protein leg unavailable, patient arm does not corroborate → statistical-unconfirmed."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "data_unavailable",
        "mrna_vs_protein_dosage_slope_ratio": None,
        "patient_dosage_agrees_with_cellline": None,
    }
    c = _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="BRCA")
    assert c["reason"] == "statistical_cis_correlation_causally_unconfirmed"


def test_confidence_honest_positive_when_patient_corroborates():
    """Patient arm corroborates the coupling → honest positive (no confidence caveat) — the MYC/CRC shape."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "data_unavailable",
        "mrna_vs_protein_dosage_slope_ratio": None,
        "patient_dosage_agrees_with_cellline": True,
    }
    assert _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="COADREAD") is None


def test_confidence_silencing_protein_dosage_does_not_suppress_statistical_unconfirmed():
    """Gap-1 fix: cis_protein_dosage_class is a CN→PROTEIN (GoF/amplification) concept irrelevant to
    confirming methylation causality. For a coherent_epigenetic_silencing verdict, an incidentally-
    populated protein-dosage class must NOT suppress the statistical-unconfirmed caveat when the patient
    methylation arm does not corroborate — protein dosage is gated to the DRIVER branch only."""
    hl = {
        "cis_coherence_verdict": "coherent_epigenetic_silencing",
        "cis_protein_dosage_class": "prot_dosage_coupled_moderate",  # incidentally populated
        "patient_silencing_agrees_with_cellline": None,  # patient methylation arm does NOT corroborate
    }
    # non-validated silencing gene in a NON-CIMP indication → past tier (ii), lands on tier (i)
    c = _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="BRCA")
    assert c is not None, "silencing statistical-unconfirmed caveat wrongly suppressed by protein dosage"
    assert c["reason"] == "statistical_cis_correlation_causally_unconfirmed"


def test_confidence_silencing_honest_positive_when_patient_methylation_corroborates():
    """The honest silencing confirmation is patient-methylation agreement / demethylation rescue —
    patient_silencing_agrees_with_cellline=True → honest positive (no caveat), regardless of protein."""
    hl = {
        "cis_coherence_verdict": "coherent_epigenetic_silencing",
        "cis_protein_dosage_class": "data_unavailable",
        "patient_silencing_agrees_with_cellline": True,
    }
    assert _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="BRCA") is None


def test_confidence_driver_protein_dosage_still_suppresses_statistical_unconfirmed():
    """Driver branch is UNCHANGED: a measured protein-dosage class remains a valid causal confirmation
    leg for coherent_cis_driver, so with protein measured (and not buffered) → honest positive, no caveat."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "prot_dosage_coupled_strong",
        "mrna_vs_protein_dosage_slope_ratio": 0.95,
        "patient_dosage_agrees_with_cellline": None,
    }
    assert _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="BRCA") is None


def test_confidence_guard_outranks_buffered_protein_precedence():
    """A guarded gene with a buffered protein slope must return the guard, NOT the amplicon-passenger tier."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_protein_dosage_class": "prot_dosage_uncoupled",
        "mrna_vs_protein_dosage_slope_ratio": 0.1,
    }
    assert (
        _cis_coherence_confidence_caveat(hl, target="ERBB2", indication="BRCA")["reason"]
        == "validated_cis_driver_or_silencing"
    )


# ── the coherent_cis_loss_of_function tier (resolver v1.3.0) ────────────────────────────────────
def test_confidence_lof_verdict_gets_its_own_tier():
    """coherent_cis_loss_of_function ALWAYS carries its own caveat: the verdict is a deletion-coupled
    expression drop with no dependency leg, so there is no configuration of it that is a direct-inhibition
    positive. It must NOT reuse the driver/silencing text (which is written about amplification addiction)."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_loss_of_function",
        "cis_dosage_direction": "deletion_coupled",
        "cis_dosage_direction_basis": "amplified_vs_deleted_contrast",
        "n_deleted": 41,
    }
    c = _cis_coherence_confidence_caveat(hl, target="APC", indication="COADREAD")
    assert c["reason"] == "cis_loss_of_function_not_a_direct_inhibition_target"
    assert c["tier"] == "milder" and c["false_demote_guarded"] is False
    assert c["cis_dosage_direction"] == "deletion_coupled"
    assert c["direction_basis_is_provisional"] is False
    assert c["n_deleted"] == 41


def test_confidence_lof_flags_a_provisional_direction_basis():
    """A direction inferred from the CN distribution's SHAPE (one arm underpowered) is weaker than a
    measured amplified-vs-deleted contrast — the caveat says so instead of asserting the arm flatly."""
    hl = {
        "cis_coherence_verdict": "coherent_cis_loss_of_function",
        "cis_dosage_direction": "deletion_coupled",
        "cis_dosage_direction_basis": "cn_distribution_asymmetry",
    }
    c = _cis_coherence_confidence_caveat(hl, target="STK11", indication="LUAD")
    assert c["direction_basis_is_provisional"] is True
    assert "provisional" in c["detail"]


def test_confidence_lof_is_not_guarded_by_the_validated_silencing_set():
    """PTEN/RB1 are in _VALIDATED_SILENCING, but the guard is about SILENCING calls. A deletion-coupled LoF
    read still gets the LoF framing — the guard must not silently suppress it."""
    hl = {"cis_coherence_verdict": "coherent_cis_loss_of_function", "cis_dosage_direction": "deletion_coupled"}
    for gene in ("PTEN", "RB1"):
        c = _cis_coherence_confidence_caveat(hl, target=gene, indication="BRCA")
        assert c["reason"] == "cis_loss_of_function_not_a_direct_inhibition_target"


# ── causal_attribution_caveat ───────────────────────────────────────────────────────────────────
def test_causal_attribution_fires_on_coupled_cis_dosage():
    c = _causal_attribution_caveat(
        {"cis_dosage_class": "cn_dosage_coupled_strong", "mrna_vs_protein_dosage_slope_ratio": 0.9}
    )
    assert c is not None and c["mrna_vs_protein_dosage_slope_ratio"] == 0.9


def test_causal_attribution_carries_direction_and_the_within_lineage_delta():
    """The lineage confound is the round-2 find: a pan-panel amplified-vs-neutral gap can be lineage
    separation, so the caveat must quote the WITHIN-lineage contrast and which arm the coupling came off."""
    c = _causal_attribution_caveat(
        {
            "cis_dosage_class": "cn_dosage_coupled_moderate",
            "cis_dosage_direction": "amplification_coupled",
            "cis_dosage_direction_basis": "amplified_vs_deleted_contrast",
            "subset_within_lineage_delta_log2tpm": 1.34,
            "subset_n_lineages_compared": 6,
            "amplified_dominant_lineage_fraction": 0.31,
        }
    )
    assert c["cis_dosage_direction"] == "amplification_coupled"
    assert c["direction_basis_is_provisional"] is False
    assert c["subset_within_lineage_delta_log2tpm"] == 1.34
    assert c["amplified_dominant_lineage_fraction"] == 0.31
    assert "DIRECTION" in c["detail"] and "subset_within_lineage_delta_log2tpm" in c["detail"]


def test_causal_attribution_none_when_cis_dosage_uncoupled():
    assert _causal_attribution_caveat({"cis_dosage_class": "cn_dosage_uncoupled"}) is None
    assert _causal_attribution_caveat({"cis_dosage_class": None}) is None


# ── context_generalization_caveat ───────────────────────────────────────────────────────────────
def test_context_generalization_fires_on_coupled_or_silenced():
    assert _context_generalization_caveat({"cis_dosage_class": "cn_dosage_coupled_moderate"}) is not None
    assert _context_generalization_caveat({"methylation_silencing_class": "silencing_coupled_strong"}) is not None


def test_context_generalization_none_when_neither_leg_coupled():
    assert (
        _context_generalization_caveat(
            {"cis_dosage_class": "cn_dosage_uncoupled", "methylation_silencing_class": "methylation_uncoupled"}
        )
        is None
    )


# ── cis_coherence_provenance ────────────────────────────────────────────────────────────────────
def test_provenance_none_on_insufficient():
    assert _cis_coherence_provenance({"cis_coherence_verdict": "insufficient_cis_coherence"}) is None
    assert _cis_coherence_provenance({"cis_coherence_verdict": None}) is None


def test_provenance_counts_coherent_legs_and_curated_flags():
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_dosage_class": "cn_dosage_coupled_strong",
        "cis_protein_dosage_class": "prot_dosage_uncoupled",
        "expression_dependency_correlation_class": "moderate_negative",
        "amp_expr_stratification_class": "amplified_overexpressed_moderately_dependent",
    }
    p = _cis_coherence_provenance(hl, target="ERBB2", indication="BRCA")
    assert p["legs_coherent"]["cn_to_mrna"] is True
    assert p["legs_coherent"]["cn_to_protein"] is False  # uncoupled = not coherent at protein
    assert p["legs_coherent"]["expression_to_dependency"] is True
    assert p["n_legs_coherent"] == 3
    assert p["validated_cis_driver_flag"] is True


def test_provenance_names_the_direction_and_its_basis():
    hl = {
        "cis_coherence_verdict": "coherent_cis_driver",
        "cis_dosage_class": "cn_dosage_coupled_strong",
        "cis_dosage_direction": "amplification_coupled",
        "cis_dosage_direction_basis": "cn_distribution_asymmetry",
        "subset_within_lineage_delta_log2tpm": 0.92,
    }
    p = _cis_coherence_provenance(hl, target="MITF", indication="SKCM")
    assert p["cis_dosage_direction"] == "amplification_coupled"
    assert p["direction_basis_is_provisional"] is True
    assert p["subset_within_lineage_delta_log2tpm"] == 0.92


def test_provenance_distinguishes_a_confounded_silencing_leg_from_a_negative_one():
    """legs_coherent.methylation_to_expression is False for BOTH methylation_uncoupled (tested, negative)
    and silencing_lineage_confounded (measured, not interpretable). The flag is what tells them apart —
    without it a confounded leg reads as evidence against silencing."""
    base = {"cis_coherence_verdict": "cis_uncoupled_no_dependency", "cis_dosage_class": "cn_dosage_uncoupled"}
    confounded = _cis_coherence_provenance(
        {**base, "methylation_silencing_class": "silencing_lineage_confounded", "lineage_collapse_ratio": 0.1},
        target="CDH1",
        indication="BRCA",
    )
    negative = _cis_coherence_provenance(
        {**base, "methylation_silencing_class": "methylation_uncoupled"}, target="AR", indication="PRAD"
    )
    assert confounded["legs_coherent"]["methylation_to_expression"] is False
    assert confounded["methylation_lineage_confounded"] is True
    assert confounded["lineage_collapse_ratio"] == 0.1
    assert negative["legs_coherent"]["methylation_to_expression"] is False
    assert negative["methylation_lineage_confounded"] is False
