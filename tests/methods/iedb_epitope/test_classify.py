"""iedb_epitope.classify — per-protein IEDB epitope-evidence classifier (pure, no S3).

Pins the evidence bands (T-cell-recognized = strongest; presented-only; no-positive-epitope weak
negative), the assay-asymmetry rule (absent = weak-negative not_observed, never a confirmed
non-epitope), and the exact summary shape the DISPLAY card contracts against.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.iedb_epitope.classify import (  # noqa: E402
    classify_epitope_evidence,
    summarize_epitope,
)


# ── the evidence bands ────────────────────────────────────────────────────────
def test_tcell_positive_is_strongest():
    # ERBB2/NY-ESO-1 archetype: positive epitopes + a positive T-cell assay -> tcell_validated
    assert classify_epitope_evidence(151, True, True) == "tcell_validated"
    assert classify_epitope_evidence(3, True, False) == "tcell_validated"


def test_presented_without_tcell():
    # MHC-ligand presentation observed but no recorded positive T-cell assay
    assert classify_epitope_evidence(20, False, True) == "presented_not_tcell_confirmed"
    assert classify_epitope_evidence(5, None, True) == "presented_not_tcell_confirmed"


def test_no_positive_epitopes_is_weak_negative():
    assert classify_epitope_evidence(0, False, False) == "no_positive_epitopes"


def test_none_is_data_unavailable():
    assert classify_epitope_evidence(None, True, True) == "data_unavailable"


# ── summarize + assay asymmetry (absent protein = weak-negative, not data_unavailable) ──
def test_summarize_row_tcell_validated():
    row = {
        "n_epitopes": 151,
        "n_mhc_class_i_epitopes": 119,
        "n_mhc_class_ii_epitopes": 36,
        "n_hla_alleles": 43,
        "has_tcell_positive": True,
        "has_mhc_ligand_positive": True,
        "has_cancer_context": True,
        "example_hla_alleles": "HLA-A*02:01;HLA-A*01:01",
    }
    s = summarize_epitope(row)
    assert s["epitope_evidence_class"] == "tcell_validated"
    assert s["n_epitopes"] == 151
    assert s["n_mhc_class_i_epitopes"] == 119
    assert s["n_mhc_class_ii_epitopes"] == 36
    assert s["n_hla_alleles"] == 43
    assert s["has_tcell_positive"] is True
    assert s["has_cancer_context"] is True
    assert s["example_hla_alleles"] == "HLA-A*02:01;HLA-A*01:01"


def test_summarize_absent_protein_is_weak_negative_not_observed():
    # assay asymmetry: absence from IEDB is a WEAK negative (peptide-centric candidate),
    # never data_unavailable and never a confirmed non-epitope.
    s = summarize_epitope(None)
    assert s["epitope_evidence_class"] == "not_observed"
    assert s["n_epitopes"] == 0
    assert s["has_tcell_positive"] is False
    assert "WEAK-negative" in s["_note"] and "candidate" in s["_note"].lower()


def test_summary_field_keys_exact():
    """The DISPLAY card's summary_fields contract against these EXACT keys (minus provenance)."""
    row = {
        "n_epitopes": 10,
        "n_mhc_class_i_epitopes": 8,
        "n_mhc_class_ii_epitopes": 2,
        "n_hla_alleles": 5,
        "has_tcell_positive": False,
        "has_mhc_ligand_positive": True,
        "has_cancer_context": False,
        "example_hla_alleles": "HLA-A*02:01",
    }
    s = summarize_epitope(row)
    assert set(s.keys()) == {
        "epitope_evidence_class",
        "n_epitopes",
        "n_mhc_class_i_epitopes",
        "n_mhc_class_ii_epitopes",
        "n_hla_alleles",
        "has_tcell_positive",
        "has_cancer_context",
        "example_hla_alleles",
    }
