"""Hermetic tests for opentargets_competitor_landscape — pure aggregator + modality classifier (no S3)."""

from __future__ import annotations

from onc_methods.opentargets_competitor_landscape.read import (
    aggregate_landscape,
    classify_modality,
)

CD3D = "ENSG00000167286"


def test_classify_modality():
    assert classify_modality("Antibody drug conjugate", None, None, None) == "ADC"
    assert classify_modality("Antibody", CD3D, 2, "AGONIST") == "TCE"  # effector-engaging
    assert classify_modality("Antibody", "ENSG00000090932", 1, None) == "monoclonal_antibody"
    assert classify_modality("Antibody", "ENSG1;ENSG2", 2, None) == "bispecific_antibody"  # 2 non-effector targets
    assert classify_modality("Small molecule", None, None, None) == "small_molecule"
    assert classify_modality("Small molecule", None, None, "DEGRADER (PROTAC)") == "degrader"
    assert classify_modality("Oligonucleotide", None, None, None) == "oligonucleotide"


def _row(drug, chembl, disease, stage, dtype, approved=False, withdrawn=False, moa=None, n=1, at=None):
    return {
        "drug_name": drug,
        "drug_chembl_id": chembl,
        "disease_id": disease,
        "max_clinical_stage": stage,
        "drug_type": dtype,
        "is_approved": approved,
        "withdrawn": withdrawn,
        "all_moa_target_genes": moa,
        "n_moa_target_genes": n,
        "action_type": at,
        "mechanism_of_action": "x",
    }


# DLL3-shape rows: tarlatamab (TCE, approved, in SCLC) + rova-T (ADC, PHASE_3, SCLC) + an off-indication row.
_ROWS = [
    _row("TARLATAMAB", "CHEMBL_T", "EFO_SCLC", "APPROVAL", "Antibody", approved=True, moa=CD3D, n=2, at="AGONIST"),
    _row("ROVALPITUZUMAB TESIRINE", "CHEMBL_R", "EFO_SCLC", "PHASE_3", "Antibody drug conjugate"),
    _row("SOMEDRUG", "CHEMBL_X", "EFO_OTHER", "PHASE_2", "Small molecule"),  # off-indication
]


def test_indication_scoped_vs_target_level():
    ind = aggregate_landscape(_ROWS, ["EFO_SCLC"])
    assert ind["indication_scope"] == "indication"
    assert ind["competitor_class"] == "approved_competitor"
    assert ind["approved_agents"] == ["TARLATAMAB"]
    assert ind["late_stage_non_approved_agents"] == ["ROVALPITUZUMAB TESIRINE"]  # PHASE_3, never approved
    assert set(ind["modalities_in_development"]) == {"ADC", "TCE"}
    assert ind["n_competitor_programs"] == 2  # off-indication SM excluded
    # target-level (no efo lane) includes the off-indication SM
    tl = aggregate_landscape(_ROWS, [])
    assert tl["indication_scope"] == "target_level"
    assert tl["n_competitor_programs"] == 3


def test_no_known_competitor_and_drug_collapse():
    assert aggregate_landscape([], ["EFO_SCLC"])["competitor_class"] == "no_known_competitor"
    # same drug in two diseases within scope collapses to ONE program at the max stage
    rows = [
        _row("D", "CHEMBL_D", "EFO_SCLC", "PHASE_1", "Small molecule"),
        _row("D", "CHEMBL_D", "EFO_SCLC", "PHASE_3", "Small molecule"),
    ]
    agg = aggregate_landscape(rows, ["EFO_SCLC"])
    assert agg["n_competitor_programs"] == 1
    assert agg["competitor_class"] == "active_clinical_competitor"  # PHASE_3, not approved
