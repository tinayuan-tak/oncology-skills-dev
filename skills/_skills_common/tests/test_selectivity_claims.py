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


def test_field_names_are_corroboration_not_reliability():
    """Post reliability→corroboration rename: the claim dicts carry `corroboration`."""
    vec = selectivity_claim_vector(_ceacam5_headline(), [])
    assert "corroboration" in vec["WIN"] and "reliability" not in vec["WIN"]


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
