"""Test tumor-presence per-modality sub-verdicts (Slice-Y, MODALITY_TAXONOMY.md).

The refactor is ADDITIVE: the collapsed `presence_verdict` (the audit spine the
target-profile consumer reads as `verdict`) stays byte-stable, and a new
`presence_verdict_by_modality` map is added. These tests pin:
  1. collapsed verdict = same rank ladder as before (F1-safe / consumer contract);
  2. fired rules group by their card's measurement modality (CARD_MODALITY);
  3. within-modality ranking uses the SAME ladder as the collapsed verdict;
  4. modalities with no card in this skill (sc_rna, protein_ihc) emit an explicit
     data_unavailable — a NAMED gap, never a fabricated negative;
  5. the disagreement case (RNA-high, protein-low) is legible per-modality while
     the collapsed verdict is unchanged — the whole point of the taxonomy.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x",
            "value": "y", "signals": {}}


# --- collapsed verdict unchanged (F1-safe / consumer contract) --------------

def test_collapsed_verdict_ranks_across_all_cards():
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("expression-strong-upregulation-supportive", "expression-tumor-vs-adjacent")]
    assert tp._verdict(fired) == ("broadly_high_expression",
                                  "expression-broadly-high-supportive")


def test_collapsed_verdict_no_rules_is_insufficient():
    assert tp._verdict([]) == ("insufficient", None)


# --- per-modality grouping + within-group ranking ---------------------------

def test_bulk_rna_group_ranks_within_modality():
    fired = [_fr("expression-strong-upregulation-supportive", "expression-tumor-vs-adjacent"),
             _fr("expression-broadly-high-supportive", "expression-distribution")]
    pm = tp._per_modality_verdicts(fired)
    # both cards are bulk_rna; broadly-high outranks strong-upregulation
    assert pm["bulk_rna"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_rna"]["evidence_state"] == "measured"


def test_protein_group_is_separate_from_rna():
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("expression-broadly-low-degrader-killer", "protein-presence-cptac")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna"]["verdict"] == "broadly_high_expression"
    assert pm["bulk_protein_ms"]["verdict"] == "broadly_low_expression"
    assert pm["bulk_protein_ms"]["evidence_state"] == "measured"


def test_celline_proteomics_card_feeds_bulk_protein_ms():
    """The new protein-abundance-celline card (E3b) is bulk_protein_ms — its fired
    rule must land in the bulk_protein_ms modality group alongside CPTAC."""
    assert tp.CARD_MODALITY["protein-abundance-celline"] == "bulk_protein_ms"
    fired = [_fr("protein-abundance-broadly-high-supportive", "protein-abundance-celline")]
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_protein_ms"]["evidence_state"] == "measured"
    # bulk_rna stays data_unavailable (no RNA card fired) — modalities are independent
    assert pm["bulk_rna"]["evidence_state"] == "data_unavailable"


def test_rna_high_protein_low_disagreement_is_legible():
    """The taxonomy's core payoff: collapsed verdict unchanged, but the per-modality
    breakdown EXPOSES that protein contradicts RNA (the RNA-high/protein-absent
    false-positive the doc names)."""
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution"),
             _fr("expression-broadly-low-degrader-killer", "protein-presence-cptac")]
    assert tp._verdict(fired)[0] == "broadly_high_expression"   # collapsed unchanged
    pm = tp._per_modality_verdicts(fired)
    assert pm["bulk_rna"]["verdict"] != pm["bulk_protein_ms"]["verdict"]  # disagreement visible


# --- honest gaps: unbuilt substrates are data_unavailable, never negative ---

def test_unbuilt_substrates_are_data_unavailable():
    fired = [_fr("expression-broadly-high-supportive", "expression-distribution")]
    pm = tp._per_modality_verdicts(fired)
    for m in ("sc_rna", "protein_ihc"):
        assert pm[m]["verdict"] == "data_unavailable"
        assert pm[m]["evidence_state"] == "data_unavailable"


def test_no_fired_rules_all_modalities_data_unavailable():
    pm = tp._per_modality_verdicts([])
    assert set(pm.keys()) == set(tp.ALL_MODALITIES)
    for m in tp.ALL_MODALITIES:
        assert pm[m]["verdict"] == "data_unavailable"


def test_all_four_taxonomy_modalities_present():
    pm = tp._per_modality_verdicts([])
    assert set(pm.keys()) == {"bulk_rna", "bulk_protein_ms", "sc_rna", "protein_ihc"}


# --- drift guard: CARD_MODALITY covers exactly this skill's cards -----------

def test_card_modality_map_covers_all_skill_cards():
    """Every card in CARDS must have a modality (else it silently drops out of the
    per-modality view)."""
    for cid in tp.CARDS:
        assert cid in tp.CARD_MODALITY, f"{cid} missing from CARD_MODALITY"


def test_verdict_fn_discoverable_by_composer():
    assert hasattr(tp, "_verdict") or hasattr(tp, "_snapshot")
