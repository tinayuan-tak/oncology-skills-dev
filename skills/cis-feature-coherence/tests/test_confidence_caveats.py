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
_cis_coherence_confidence_caveat, _causal_attribution_caveat, _context_generalization_caveat, _cis_coherence_provenance = (
    _run._cis_coherence_confidence_caveat, _run._causal_attribution_caveat,
    _run._context_generalization_caveat, _run._cis_coherence_provenance,
)


# ── cis_coherence_confidence_caveat ─────────────────────────────────────────────────────────────
def test_confidence_none_on_non_coherent_verdict():
    """Uncoupled / inert / insufficient carry no coherent-cis over-call → None (byte-stable)."""
    for v in ("expressed_cis_coupled_inert", "dependency_without_cis_dosage",
              "cis_uncoupled_no_dependency", "insufficient_cis_coherence", None):
        assert _cis_coherence_confidence_caveat({"cis_coherence_verdict": v}, target="FOO", indication="BRCA") is None


def test_confidence_validated_guard_spares_canonical_driver_even_if_protein_buffered():
    """ERBB2 reads coherent_cis_driver with a BUFFERED protein slope (rank-noise) → guard, not demoted."""
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "prot_dosage_uncoupled",
          "mrna_vs_protein_dosage_slope_ratio": 0.19}
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
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "prot_dosage_uncoupled",
          "mrna_vs_protein_dosage_slope_ratio": 0.75}
    c = _cis_coherence_confidence_caveat(hl, target="STARD3", indication="BRCA")
    assert c["reason"] == "amplicon_passenger_or_lineage_confounded"
    assert c["false_demote_guarded"] is False


def test_confidence_amplicon_passenger_low_ratio_even_if_class_coupled():
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "prot_dosage_coupled_moderate",
          "mrna_vs_protein_dosage_slope_ratio": 0.3}
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
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "data_unavailable",
          "mrna_vs_protein_dosage_slope_ratio": None, "patient_dosage_agrees_with_cellline": None}
    c = _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="BRCA")
    assert c["reason"] == "statistical_cis_correlation_causally_unconfirmed"


def test_confidence_honest_positive_when_patient_corroborates():
    """Patient arm corroborates the coupling → honest positive (no confidence caveat) — the MYC/CRC shape."""
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "data_unavailable",
          "mrna_vs_protein_dosage_slope_ratio": None, "patient_dosage_agrees_with_cellline": True}
    assert _cis_coherence_confidence_caveat(hl, target="SOMEGENE", indication="COADREAD") is None


def test_confidence_guard_outranks_buffered_protein_precedence():
    """A guarded gene with a buffered protein slope must return the guard, NOT the amplicon-passenger tier."""
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_protein_dosage_class": "prot_dosage_uncoupled",
          "mrna_vs_protein_dosage_slope_ratio": 0.1}
    assert _cis_coherence_confidence_caveat(hl, target="ERBB2", indication="BRCA")["reason"] \
        == "validated_cis_driver_or_silencing"


# ── causal_attribution_caveat ───────────────────────────────────────────────────────────────────
def test_causal_attribution_fires_on_coupled_cis_dosage():
    c = _causal_attribution_caveat({"cis_dosage_class": "cn_dosage_coupled_strong",
                                    "mrna_vs_protein_dosage_slope_ratio": 0.9})
    assert c is not None and c["mrna_vs_protein_dosage_slope_ratio"] == 0.9


def test_causal_attribution_none_when_cis_dosage_uncoupled():
    assert _causal_attribution_caveat({"cis_dosage_class": "cn_dosage_uncoupled"}) is None
    assert _causal_attribution_caveat({"cis_dosage_class": None}) is None


# ── context_generalization_caveat ───────────────────────────────────────────────────────────────
def test_context_generalization_fires_on_coupled_or_silenced():
    assert _context_generalization_caveat({"cis_dosage_class": "cn_dosage_coupled_moderate"}) is not None
    assert _context_generalization_caveat({"methylation_silencing_class": "silencing_coupled_strong"}) is not None


def test_context_generalization_none_when_neither_leg_coupled():
    assert _context_generalization_caveat({"cis_dosage_class": "cn_dosage_uncoupled",
                                           "methylation_silencing_class": "methylation_uncoupled"}) is None


# ── cis_coherence_provenance ────────────────────────────────────────────────────────────────────
def test_provenance_none_on_insufficient():
    assert _cis_coherence_provenance({"cis_coherence_verdict": "insufficient_cis_coherence"}) is None
    assert _cis_coherence_provenance({"cis_coherence_verdict": None}) is None


def test_provenance_counts_coherent_legs_and_curated_flags():
    hl = {"cis_coherence_verdict": "coherent_cis_driver", "cis_dosage_class": "cn_dosage_coupled_strong",
          "cis_protein_dosage_class": "prot_dosage_uncoupled", "expression_dependency_correlation_class": "moderate_negative",
          "amp_expr_stratification_class": "amplified_overexpressed_moderately_dependent"}
    p = _cis_coherence_provenance(hl, target="ERBB2", indication="BRCA")
    assert p["legs_coherent"]["cn_to_mrna"] is True
    assert p["legs_coherent"]["cn_to_protein"] is False        # uncoupled = not coherent at protein
    assert p["legs_coherent"]["expression_to_dependency"] is True
    assert p["n_legs_coherent"] == 3
    assert p["validated_cis_driver_flag"] is True
