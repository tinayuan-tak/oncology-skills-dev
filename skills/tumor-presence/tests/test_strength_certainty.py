"""tumor-presence (strength, certainty) sidecar — CERTAINTY_MODEL 5th axis (first no-resolver). Verdict-inert."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_strength")


def _cards(rna_bm=None, n_tumor=None, n_cell=None, sc=None, protein=False, fragile=None, ci_low=None, ci_high=None):
    c = []
    if n_tumor is not None:
        c.append({"card_id": "tumor-rna-distribution", "summary": {"n_tumor_samples": n_tumor}})
    if n_cell is not None:
        c.append({"card_id": "cellline-rna-distribution", "summary": {"n_cell_lines_evaluated": n_cell}})
    if sc is not None:
        c.append({"card_id": "tumor-scrna-celltype-expression", "summary": {"malignant_n_cells": sc}})
    if protein:
        c.append({"card_id": "tumor-protein-abundance-cptac", "summary": {}})
    if rna_bm is not None:
        c.append(
            {
                "card_id": "rna-protein-concordance-tumor",
                "summary": {
                    "rna_as_biomarker": rna_bm,
                    "rna_proxy_class_boundary_fragile": fragile,
                    "rna_protein_r_ci95_low": ci_low,
                    "rna_protein_r_ci95_high": ci_high,
                },
            }
        )
    return c


def test_broadly_expressed_rna_protein_concordant_high():
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=500, sc=3000), verdict_pair=("tumor_broadly_expressed", "x")
    )
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"  # n>=100 AND >=2 layers (rna tumor + sc)
    assert sc["certainty"]["corroboration"] == "high"
    assert sc["certainty"]["level"] == "high"


def test_poor_proxy_disagrees_low():
    sc = tp._strength_certainty(
        _cards(rna_bm="poor_proxy", n_tumor=500, sc=3000), verdict_pair=("tumor_broadly_expressed", "x")
    )
    assert sc["certainty"]["corroboration"] == "low"  # RNA does not predict protein
    assert sc["certainty"]["level"] == "low"


def test_proxy_unmeasured_drops_to_coverage():
    sc = tp._strength_certainty(
        _cards(rna_bm=None, n_cell=50),  # cell-line only, no proxy card
        verdict_pair=("broadly_high_expression", "x"),
    )
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"  # n=50, breadth 1


def test_not_informative_forces_low_none():
    sc = tp._strength_certainty([], verdict_pair=("not_informative", None))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"


# ── #1650 boundary-fragile proxy down-weight (rna_proxy_class_boundary_fragile wiring) ────────────
# A proxy-class call whose Fisher-z 95% CI straddles a 0.4/0.7 class cut can flip by sampling alone,
# so its corroboration is demoted ONE level (never flips the verdict token). Validated on the arc's
# confirmed panel: adequate+fragile (ERBB2/BRCA r=0.50, EGFR/LUAD r=0.63) and partial+fragile fire;
# the correct-negative poor call (KRAS r=0.008) does not.


def test_adequate_proxy_fragile_demotes_high_to_medium():
    # ERBB2/BRCA-shaped: r=0.50 adequate, CI straddles the 0.4 cut → boundary-fragile.
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=119, sc=3000, fragile=True, ci_low=0.35, ci_high=0.62),
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration"] == "medium"  # demoted from high
    assert sc["certainty"]["corroboration_boundary_fragile"] is True
    assert "boundary-fragile" in sc["certainty"]["corroboration_note"]
    assert "[0.35, 0.62]" in sc["certainty"]["corroboration_note"]


def test_partial_proxy_fragile_demotes_medium_to_low():
    # EPCAM-golden-shaped: partial_proxy, CI straddles a cut → boundary-fragile.
    sc = tp._strength_certainty(
        _cards(rna_bm="partial_proxy", n_tumor=207, sc=3000, fragile=True, ci_low=0.2464, ci_high=0.5771),
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration"] == "low"  # demoted from medium
    assert sc["certainty"]["corroboration_boundary_fragile"] is True


def test_adequate_proxy_not_fragile_byte_stable():
    # Same adequate call but NOT boundary-fragile → no demotion, and NO annotation keys (so every
    # non-fragile certainty block is byte-identical to the pre-wiring output).
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=500, sc=3000, fragile=False),
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration"] == "high"  # unchanged
    assert "corroboration_boundary_fragile" not in sc["certainty"]
    assert "corroboration_note" not in sc["certainty"]


def test_poor_proxy_not_fragile_correct_negative():
    # KRAS-shaped correct negative: r≈0.008, poor_proxy, not boundary-fragile → corroboration stays
    # low, no annotation. The caveat must NOT fire here.
    sc = tp._strength_certainty(
        _cards(rna_bm="poor_proxy", n_tumor=500, sc=3000, fragile=False),
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration"] == "low"
    assert "corroboration_boundary_fragile" not in sc["certainty"]


def test_fragile_flag_absent_is_byte_stable():
    # Flag missing entirely (older/insufficient cards) is treated as not-fragile → byte-stable.
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=500, sc=3000),  # fragile defaults to None
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration"] == "high"
    assert "corroboration_boundary_fragile" not in sc["certainty"]


def test_fragile_note_omits_ci_when_not_numeric():
    # Boundary-fragile but CI bounds absent → annotation fires WITHOUT a spurious "[None, None]" clause.
    sc = tp._strength_certainty(
        _cards(rna_bm="adequate_proxy", n_tumor=500, sc=3000, fragile=True),
        verdict_pair=("tumor_broadly_expressed", "x"),
    )
    assert sc["certainty"]["corroboration_boundary_fragile"] is True
    assert "CI" not in sc["certainty"]["corroboration_note"]
