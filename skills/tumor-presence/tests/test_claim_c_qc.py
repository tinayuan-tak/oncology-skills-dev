"""Tier-1 sc-utilization (#984): claim C consumes the single-cell QC (ambient soup-leakage) +
malignant-annotation provenance + entity purity to temper CORROBORATION and surface a caveat.

VERDICT-INERT: only the claim-vector corroboration + a qc_detail caveat move; the ladder class
(signal) is untouched, and the presence_verdict spine is unaffected.
"""
from __future__ import annotations

from _skills_common.presence_claims import presence_claim_vector

_H = {"sc_expression_class": "malignant_broadly_detected",
      "sc_malignant_detection_fraction": 0.9, "sc_malignant_n_donors": 200}   # n>=100 → baseline corrob high


def _cards(**scrna):
    s = {"sc_expression_class": "malignant_broadly_detected"}
    s.update(scrna)
    return [{"card_id": "tumor-scrna-celltype-expression", "summary": s}]


def test_qc_downgrades_on_ambient_and_proxy():
    C = presence_claim_vector(_H, _cards(ambient_contamination_risk="possible",
                                         malignant_annotation_method="phenotype_proxy",
                                         entity_purity="multi_entity_pooled"))["C"]
    assert C["signal"] == "strong"                 # ladder class unchanged (verdict-inert)
    assert C["corroboration"] == "low"             # high → moderate (ambient) → low (proxy)
    assert "ambient-contamination:possible" in C["qc_detail"]
    assert "malignant-annotation:phenotype_proxy" in C["qc_detail"]
    assert "entity:multi_entity_pooled" in C["qc_detail"]
    assert "QC[" in C["evidence"]


def test_qc_single_downgrade_on_ambient_only():
    C = presence_claim_vector(_H, _cards(ambient_contamination_risk="possible",
                                         malignant_annotation_method="curated"))["C"]
    assert C["corroboration"] == "moderate"        # high → moderate (one downgrade)
    assert "ambient-contamination:possible" in C["qc_detail"]
    assert "malignant-annotation:curated" in C["qc_detail"]   # curated is noted, no downgrade


def test_qc_clean_curated_no_downgrade():
    C = presence_claim_vector(_H, _cards(ambient_contamination_risk="low",
                                         malignant_annotation_method="curated",
                                         entity_purity="entity_specific"))["C"]
    assert C["corroboration"] == "high"            # nothing downgrades
    assert C["qc_detail"] == "malignant-annotation:curated"


def test_qc_absent_is_graceful():
    # fixture / older cards without the fields → no qc_detail, no downgrade, byte-stable
    C = presence_claim_vector(_H, _cards())["C"]
    assert C["corroboration"] == "high" and C["qc_detail"] is None
    assert "QC[" not in C["evidence"]
