"""Tests for the sample_context check in validate_cards.py (2026-07-21).

sample_context (cell_line | tumor | normal) is ORTHOGONAL to `measurement` (the measurement layer) but
must be CONSISTENT with the card's measurement_type prefix (cell_line_* ↔ cell_line, tumor_* ↔ tumor,
normal_tissue_* ↔ normal) — the type already fixes the sample context, so a disagreement is a real
defect that would mis-bucket the per-modality sub-verdict. Optional field: no sample_context → no
check. Hermetic (synthetic card dicts).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(m):
    spec = importlib.util.spec_from_file_location(m, REPO / "validators" / f"{m}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[m] = mod
    spec.loader.exec_module(mod)
    return mod


import importlib.util  # noqa: E402
VC = _load("validate_cards")


def _base(**ov):
    c = {
        "card_id": "synthetic-sc-card", "version": "1.0.0",
        "question": "Synthetic card for {target.symbol} in {indication.label}?",
        "applies_when": [], "required_inputs": [{"product_id": "x"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": {"summary_fields": ["f"]},
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
    }
    c.update(ov)
    return c


def _v(tmp, card):
    p = tmp / "c.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _errs(r):
    return "\n".join(r.errors)


def test_consistent_cell_line_passes(tmp_path):
    r = _v(tmp_path, _base(measurement_type="cell_line_rna_expression", sample_context="cell_line",
                           entity_grains=["target", "target_lineage"]))
    assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r)


def test_consistent_tumor_passes(tmp_path):
    r = _v(tmp_path, _base(measurement_type="tumor_vs_adjacent_expression", sample_context="tumor",
                           entity_grains=["target_indication"]))
    assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r)


def test_mismatch_is_error(tmp_path):
    # cell_line_* type but sample_context: tumor → contradiction
    r = _v(tmp_path, _base(measurement_type="cell_line_rna_expression", sample_context="tumor",
                           entity_grains=["target", "target_lineage"]))
    assert not r.ok and "SAMPLE_CONTEXT_MISMATCH" in _errs(r)


def test_normal_tissue_prefix_expects_normal(tmp_path):
    r = _v(tmp_path, _base(measurement_type="normal_tissue_protein_breadth", sample_context="tumor"))
    assert not r.ok and "SAMPLE_CONTEXT_MISMATCH" in _errs(r)
    r2 = _v(tmp_path, _base(measurement_type="normal_tissue_protein_breadth", sample_context="normal"))
    assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r2)


def test_no_sample_context_is_not_checked(tmp_path):
    # optional field absent → nothing to enforce
    r = _v(tmp_path, _base(measurement_type="cell_line_rna_expression"))
    assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r)


def test_context_without_matching_prefix_is_skipped(tmp_path):
    # a type whose prefix isn't in the map (e.g. surface_confirmation) → can't infer, no error
    r = _v(tmp_path, _base(measurement_type="surface_confirmation", sample_context="tumor"))
    assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r)


def test_bad_sample_context_value_rejected_by_schema(tmp_path):
    r = _v(tmp_path, _base(sample_context="xenograft"))   # not in the enum
    assert not r.ok and "STRUCTURAL" in _errs(r)


def test_real_stamped_cards_are_consistent():
    """The 5 cards stamped this slice validate clean on the sample_context check."""
    for cid in ["cellline-rna-distribution", "protein-abundance-celline", "expression-tumor-vs-adjacent",
                "protein-presence-cptac", "tumor-vs-normal-selectivity"]:
        r = VC.validate_card_file(REPO / "cards" / f"{cid}.card.yaml")
        assert "SAMPLE_CONTEXT_MISMATCH" not in _errs(r), f"{cid}: {_errs(r)}"
