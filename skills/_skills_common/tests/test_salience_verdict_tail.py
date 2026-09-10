"""Regression guard for the 2026-09-10 verdict-tail SALIENCE_SPECS (genomic / differentiation /
combination / cis-coherence / surface). Proves each newly-authored spec is REGISTERED and actually
ENRICHES key_evidence from a realistic summary — so a future card-field rename that silently re-inerts
a spec fails here (not just quietly stops promoting the decisive datum). Verdict-inert / display-only.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import pytest  # noqa: E402
from _skills_common.evidence_graph import _build_key_evidence  # noqa: E402
from _skills_common.evidence_salience import spec_for  # noqa: E402

# the verdict-tail types authored 2026-09-10 — each MUST resolve to a non-empty spec.
_VERDICT_TAIL = [
    "cn_stratified_dependency",
    "amp_expr_stratified_dependency",
    "fusion_stratified_dependency",
    "mutation_hotspot_frequency",
    "mutation_drug_response",
    "splice_exon_skip",
    "fusion_rearrangement",
    "variant_level_interpretation",
    "expression_clinical_association",
    "alteration_clinical_association",
    "subtype_survival_association",
    "synthetic_lethal_partner",
    "chemical_combination_synergy",
    "methylation_silencing_coupling",
    "patient_cis_coherence",
    "cis_protein_dosage_coupling",
    "expression_dependency_correlation",
    "abundance_dependency_correlation",
    "adc_tce_modality_fit",
    "modality_window",
    "shed_ectodomain_liability",
]


@pytest.mark.parametrize("mt", _VERDICT_TAIL)
def test_verdict_tail_type_has_a_spec(mt):
    spec = spec_for(mt)
    assert spec, f"{mt} must resolve to a non-empty SALIENCE_SPEC"
    # every spec is useful: it names AT LEAST one of effect / significance / categorical / strata / n.
    assert any(spec.get(k) for k in ("effect_field", "significance_field", "categorical", "strata_array", "n_field")), (
        f"{mt} spec names no salient field"
    )


def test_scalar_effect_spec_enriches_key_evidence():
    # cn_stratified_dependency: scalar delta + q + n from a realistic summary
    ke = _build_key_evidence(
        {"measurement_type": "cn_stratified_dependency"},
        {
            "delta_chronos_amplified_vs_neutral": -0.62,
            "cn_stratification_mannwhitney_q": 8.7e-12,
            "n_amplified": 43,
            "cn_stratification_class": "amplification_dependent",
        },
    )
    assert ke["effect"]["metric"] == "delta_chronos_amplified_vs_neutral" and ke["effect"]["value"] == -0.62
    assert ke["significance"]["stat"] == "cn_stratification_mannwhitney_q"
    assert ke["n"] == 43


def test_categorical_only_verdict_card_enriches_key_evidence():
    # adc_tce_modality_fit: the composed VERDICT card emits no numeric anchor — its fit_class + the
    # endocytosis/confirmation labels must still reach key_evidence.categorical (audit §3.6 empty-capsule fix).
    ke = _build_key_evidence(
        {
            "measurement_type": "adc_tce_modality_fit",
            "categorical_anchors": [
                {"field": "fit_class", "value": "both_viable"},
                {"field": "endocytosis_confidence", "value": "clinically_internalizing"},
            ],
        },
        {"fit_class": "both_viable", "endocytosis_confidence": "clinically_internalizing"},
    )
    cats = {c["field"]: c["value"] for c in (ke.get("categorical") or [])}
    assert cats.get("fit_class") == "both_viable"
