"""#993 pt1 — the VERDICT-INERT minority_allele_coverage_caveat backtest panel.

A positive SM-tractability snapshot resting on an approved ALLELE-SELECTIVE drug that covers only a
MINORITY of the indication's mutant-allele spectrum (the dominant hotspot allele is uncovered) must be
flagged; but the same target in an indication where the covered allele IS dominant must NOT fire, and a
gene with no curated allele-selective entry never fires. The caveat is verdict-inert (bins byte-stable)."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run")

# KRAS in COADREAD: G12D/G12V/G13D-dominant, G12C a ~3% minority (the motivating case).
_KRAS_COADREAD = [
    {"protein_change": "G12D", "frequency": 0.109},
    {"protein_change": "G12V", "frequency": 0.093},
    {"protein_change": "G13D", "frequency": 0.072},
    {"protein_change": "G12C", "frequency": 0.030},
]
# KRAS in LUAD: G12C is the DOMINANT allele — the indication-conditioning control (must NOT fire).
_KRAS_LUAD = [
    {"protein_change": "G12C", "frequency": 0.40},
    {"protein_change": "G12V", "frequency": 0.10},
    {"protein_change": "G12D", "frequency": 0.05},
]


def test_kras_coadread_minority_allele_fires_993():
    c = tp._minority_allele_coverage_caveat("well_covered", "KRAS", _KRAS_COADREAD)
    assert c is not None
    assert "well_covered_for_minority_allele" in c
    assert "G12D" in c  # names the uncovered dominant allele
    assert "G12C" in c  # names what the approved drug covers


def test_kras_luad_dominant_covered_allele_does_not_fire_993():
    # SAME target + approved drug, but G12C is dominant in LUAD → NOT a minority concern → no caveat.
    assert tp._minority_allele_coverage_caveat("well_covered", "KRAS", _KRAS_LUAD) is None


def test_braf_v600e_dominant_covered_does_not_fire_993():
    braf = [{"protein_change": "V600E", "frequency": 0.45}, {"protein_change": "V600K", "frequency": 0.05}]
    assert tp._minority_allele_coverage_caveat("well_covered", "BRAF", braf) is None


def test_gene_without_curated_allele_entry_never_fires_993():
    # EGFR is deliberately OMITTED from the curated map (broad activating-spectrum TKIs) → never fires,
    # even if the top hotspot looks uncovered.
    egfr = [{"protein_change": "L858R", "frequency": 0.4}, {"protein_change": "T790M", "frequency": 0.1}]
    assert tp._minority_allele_coverage_caveat("well_covered", "EGFR", egfr) is None


def test_non_positive_snapshot_does_not_fire_993():
    assert tp._minority_allele_coverage_caveat("chemically_unhit", "KRAS", _KRAS_COADREAD) is None


def test_no_hotspot_spectrum_is_graceful_993():
    # indication without a mutation-hotspot-frequency card → no allele spectrum → no caveat (never raises).
    assert tp._minority_allele_coverage_caveat("well_covered", "KRAS", None) is None
    assert tp._minority_allele_coverage_caveat("well_covered", "KRAS", []) is None
