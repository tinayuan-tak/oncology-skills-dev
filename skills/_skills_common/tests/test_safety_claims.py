"""Unit tests for on-target-safety-liability's claim vector (skills/_skills_common/safety_claims.py),
the FIFTH concrete over claim_vector_core. Pins the INVERSE-valence LIABILITY tiers (strong = concern,
tolerant = absent, protective = negative) + the citable atoms + the mutant-selective-GoF conditioning
conflict. Pure over a headline dict + card summaries — no S3."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.safety_claims import safety_claim_vector  # noqa: E402


def _headline(**over):
    h = {
        "constraint_class": "highly_constrained",
        "pli_score": 0.99,
        "loeuf_score": 0.21,
        "obs_lof_count": 2,
        "exp_lof_count": 40.0,
        "burden_safety_class": "lof_risk_phenotype",
        "burden_min_pvalue": 3e-9,
        "burden_top_disease": "cardiomyopathy",
        "dosage_sensitivity_class": "autosomal_dominant_loss",
        "germline_inheritance_mode": "dominant",
        "clinvar_pathogenic_class": "germline_pathogenic",
        "clinvar_top_disease": "Noonan",
        "mouse_ko_phenotype_class": "lethal_ko",
        "mouse_ko_top_lethal": "embryonic_lethal",
        "alteration_functional_direction": "loss_of_function",
    }
    h.update(over)
    return h


def _cards():
    return [
        {
            "card_id": "gnomad-lof-constraint",
            "summary": {
                "constraint_class": "highly_constrained",
                "pli_score": 0.99,
                "loeuf_score": 0.21,
                "mis_z_score": 3.1,
                "obs_lof_count": 2,
                "exp_lof_count": 40.0,
            },
        },
        {
            "card_id": "gene-burden-safety",
            "summary": {
                "burden_safety_class": "lof_risk_phenotype",
                "min_pvalue": 3e-9,
                "top_disease": "cardiomyopathy",
            },
        },
        {
            "card_id": "clingen-dosage",
            "summary": {"dosage_sensitivity_class": "autosomal_dominant_loss", "germline_inheritance_mode": "dominant"},
        },
        {
            "card_id": "clinvar-pathogenicity-safety",
            "summary": {"clinvar_pathogenic_class": "germline_pathogenic", "top_disease": "Noonan"},
        },
        {
            "card_id": "mouse-ko-phenotype",
            "summary": {"ko_phenotype_class": "lethal_ko", "top_lethal_label": "embryonic_lethal"},
        },
    ]


def test_liability_tiers_strong_when_constrained():
    vec = safety_claim_vector(_headline(), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"  # highly_constrained = strong CONCERN
    assert vec["BURDEN"]["signal"] == "strong"  # lof_risk_phenotype
    assert vec["DOSAGE"]["signal"] == "strong"  # autosomal_dominant_loss
    assert vec["CLINVAR"]["signal"] == "strong" and vec["MOUSE_KO"]["signal"] == "strong"


def test_inverse_valence_tolerant_is_absent_protective_is_negative():
    vec = safety_claim_vector(
        _headline(
            constraint_class="tolerant",
            burden_safety_class="protective",
            dosage_sensitivity_class="dosage_sufficient",
            mouse_ko_phenotype_class="no_phenotype",
        ),
        _cards(),
    )
    assert vec["CONSTRAINT"]["signal"] == "absent"  # MEASURED LoF-tolerant → not a concern
    assert vec["BURDEN"]["signal"] == "negative"  # protective → measured opposite
    assert vec["DOSAGE"]["signal"] == "absent"
    assert vec["MOUSE_KO"]["signal"] == "absent"


def test_gap_is_unmeasured_not_absent():
    vec = safety_claim_vector(_headline(constraint_class="indeterminate"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "unmeasured"  # gap ≠ measured-tolerant


def test_atoms_present_and_citable():
    vec = safety_claim_vector(_headline(), _cards())
    a = vec["CONSTRAINT"]["evidence_atom"]
    assert a["cite"]["card_id"] == "gnomad-lof-constraint"
    assert a["values"]["pli_score"] == 0.99 and a["values"]["loeuf_score"] == 0.21
    assert a["entity"]["valence"] == "liability"
    assert vec["BURDEN"]["evidence_atom"]["values"]["min_pvalue"] == 3e-9


def test_mutant_selective_gof_conditions_constraint_conflict():
    # activating-GoF mechanism → the WT-constraint concern is flagged as MODALITY-CONDITIONAL (a conflict
    # tension pointing at the per-modality safety verdict), tier kept. The scalar downgrade was retired
    # (safety.resolver 2.0.0); the conflict must NOT claim the scalar verdict was downgraded.
    vec = safety_claim_vector(_headline(alteration_functional_direction="activating"), _cards())
    assert vec["CONSTRAINT"]["signal"] == "strong"  # tier unchanged (this is the SIGNAL)
    conflict = vec["CONSTRAINT"]["conflict"] or ""
    assert "MODALITY-CONDITIONAL" in conflict
    assert "NOT downgraded" in conflict  # scalar verdict is the raw concern


def test_atoms_absent_without_cards():
    vec = safety_claim_vector(_headline(), [])
    for ax in ("CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO"):
        assert "evidence_atom" not in vec[ax], f"{ax} atom present with no source card"


# ── 2026-09-04 signal-surfacing: PHARMACOVIGILANCE context axis + rich CLINVAR/MOUSE_KO sub-fields ──
def test_pharmacovigilance_axis_is_verdict_inert_context():
    # a black-box-warned target-engaging drug is a STRONG clinical liability SIGNAL, but corroboration is
    # CAPPED (never `high`) and the confound rides in the conflict slot — it ORIENTS, never a resolver HOLD.
    vec = safety_claim_vector(
        _headline(
            drug_warning_class="black_box_warned",
            drug_warning_has_black_box=True,
            drug_warning_toxicity_classes=["hepatotoxicity", "cardiotoxicity"],
            onsides_example_boxed_warning_terms="Hepatotoxicity",
        ),
        _cards(),
    )
    p = vec["PHARMACOVIGILANCE"]
    assert p["signal"] == "strong"
    assert p["corroboration"] == "moderate"  # capped — the on/off-target confound
    assert "hepatotoxicity" in p["evidence"]  # the rich toxicity CLASSES the capsule carried
    assert "CONFOUNDED" in (p["conflict"] or "")  # confound flagged, not the verdict
    assert "CONTEXT" in vec["_disclaimer"]  # doubly-inert note present


def test_pharmacovigilance_measured_absent_vs_unmeasured_gap():
    # engaging drug(s) exist but NONE warned = MEASURED absent; no engaging drug at all = coverage gap.
    assert (
        safety_claim_vector(_headline(drug_warning_class="no_warning"), _cards())["PHARMACOVIGILANCE"]["signal"]
        == "absent"
    )
    gap = safety_claim_vector(_headline(drug_warning_class="no_targeted_drug"), _cards())["PHARMACOVIGILANCE"]
    assert gap["signal"] == "unmeasured" and gap["corroboration"] == "unmeasured"


def test_pharmacovigilance_onsides_fallback_when_drug_warning_thin():
    # a boxed-warning ADE profile is a strong clinical signal even when the OT drug-warning leg is thin.
    v = safety_claim_vector(_headline(drug_warning_class="no_targeted_drug", onsides_has_boxed_warning=True), _cards())
    assert v["PHARMACOVIGILANCE"]["signal"] == "moderate"


def test_clinvar_evidence_surfaces_confident_variant_count():
    vec = safety_claim_vector(_headline(clinvar_n_pathogenic_germline_confident=109), _cards())
    assert "confident-germline-pathogenic-variants=109" in vec["CLINVAR"]["evidence"]
    # a zero/absent count must NOT clutter the evidence
    assert (
        "confident-germline-pathogenic-variants"
        not in safety_claim_vector(_headline(clinvar_n_pathogenic_germline_confident=0), _cards())["CLINVAR"][
            "evidence"
        ]
    )


def test_mouseko_evidence_surfaces_organ_systems():
    vec = safety_claim_vector(
        _headline(mouse_ko_organ_systems=["hematopoietic system phenotype", "cardiovascular system phenotype"]),
        _cards(),
    )
    ev = vec["MOUSE_KO"]["evidence"]
    assert "organ-systems=" in ev and "hematopoietic system phenotype" in ev


def test_pharmacovigilance_atom_cites_drug_warning_card():
    cards = _cards() + [
        {
            "card_id": "drug-warning-safety",
            "summary": {
                "drug_warning_class": "black_box_warned",
                "has_black_box": True,
                "toxicity_classes": ["hepatotoxicity"],
                "warning_types": ["black box warning"],
                "n_targeted_warned_drugs": 8,
            },
        }
    ]
    a = safety_claim_vector(_headline(drug_warning_class="black_box_warned"), cards)["PHARMACOVIGILANCE"][
        "evidence_atom"
    ]
    assert a["cite"]["card_id"] == "drug-warning-safety"
    assert a["entity"]["valence"] == "liability"
